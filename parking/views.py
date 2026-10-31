import csv
import json
import re
from datetime import datetime, timedelta
from functools import wraps
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .models import Booking, Lot, ParkingSlot, Place

CATEGORIES = [
    {'value': Place.Category.MALL, 'label': 'Malls', 'singular': 'Mall'},
    {'value': Place.Category.THEATRE, 'label': 'Theatres', 'singular': 'Theatre'},
    {'value': Place.Category.RESTAURANT, 'label': 'Restaurants', 'singular': 'Restaurant'},
    {'value': Place.Category.COLLEGE, 'label': 'Colleges', 'singular': 'College'},
    {'value': Place.Category.HOSPITAL, 'label': 'Hospitals', 'singular': 'Hospital'},
    {'value': Place.Category.OFFICE, 'label': 'Offices', 'singular': 'Office park'},
    {'value': Place.Category.STADIUM, 'label': 'Stadiums', 'singular': 'Stadium'},
]
CATEGORY_LABELS = {item['value']: item['singular'] for item in CATEGORIES}
DURATIONS = [1, 2, 3, 4, 8]
SORTS = ['nearby', 'availability', 'price', 'rating']
# Fallback origin (Marine Drive, Kochi) when the browser does not share a location.
DEFAULT_ORIGIN = (9.9312, 76.2673)
MAX_SLOTS_PER_PLACE = 300


def api(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except (json.JSONDecodeError, ValueError, TypeError, OverflowError) as exc:
            message = str(exc) if isinstance(exc, ValueError) else ''
            return JsonResponse({'error': message or 'Please check the information you entered and try again.'}, status=400)
    return wrapped


def body(request):
    if not request.body:
        return {}
    data = json.loads(request.body)
    if not isinstance(data, dict):
        raise ValueError('Expected an object')
    return data


def staff_api(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Please sign in with an administrator account.'}, status=401)
        if not request.user.is_staff:
            return JsonResponse({'error': 'Administrator access is required.'}, status=403)
        return view(request, *args, **kwargs)
    return wrapped


def user_data(user):
    if not user.is_authenticated:
        return None
    name = user.get_full_name() or user.username
    return {'name': name, 'email': user.email, 'is_staff': user.is_staff,
            'initials': ''.join(p[0] for p in name.split()[:2]).upper()}


def now_local():
    return timezone.localtime()


def default_window(now=None):
    now = now or now_local()
    start = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    if start.hour < 6:
        start = start.replace(hour=9)
    if start.hour >= 22:
        start = (start + timedelta(days=1)).replace(hour=10)
    return start, start + timedelta(hours=2)


def parse_window(getter):
    """Read date / start_time / duration from a dict-like object.

    Returns (datetime_start, datetime_end, duration_hours). Raises ValueError on
    anything a driver could get wrong, so the API can answer with a useful message.
    """
    now = now_local()
    default_start, _ = default_window(now)
    date_string = str(getter.get('date', default_start.strftime('%Y-%m-%d')))
    time_string = str(getter.get('start_time', default_start.strftime('%H:%M')))
    raw_duration = getter.get('duration', 2)
    try:
        duration = int(raw_duration)
    except (TypeError, ValueError):
        raise ValueError('Choose a parking duration of 1, 2, 3, 4, or 8 hours.')
    if isinstance(raw_duration, bool) or duration not in DURATIONS:
        raise ValueError('Choose a parking duration of 1, 2, 3, 4, or 8 hours.')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date_string) or not re.fullmatch(r'\d{2}:\d{2}', time_string):
        raise ValueError('Enter a valid date and arrival time.')
    try:
        naive = datetime.strptime(date_string + ' ' + time_string, '%Y-%m-%d %H:%M')
        start = naive.replace(tzinfo=ZoneInfo(settings.TIME_ZONE))
    except ValueError:
        raise ValueError('Enter a valid date and arrival time.')
    end = start + timedelta(hours=duration)
    if start < now - timedelta(minutes=1):
        raise ValueError('Your arrival time is in the past. Please choose a future time.')
    if start > now + timedelta(days=30):
        raise ValueError('Reservations can be made up to 30 days in advance.')
    return start, end, duration


def fit_window(place, start, duration):
    """Return the closest visit window that fits inside a place's opening hours.

    Used to pre-fill the booking form when a driver opens a venue that is closed
    at the time they picked on the search screen.
    """
    now = now_local()
    candidate = start
    if candidate.date() == now.date() and candidate < now:
        candidate = now.replace(second=0, microsecond=0)
        candidate += timedelta(minutes=-(candidate.minute % 5) + 5)
    if candidate.time() < place.open_time:
        candidate = candidate.replace(hour=place.open_time.hour, minute=place.open_time.minute)
    for _ in range(3):
        fits = [d for d in DURATIONS
                if (candidate + timedelta(hours=d)).date() == candidate.date()
                and (candidate + timedelta(hours=d)).time() <= place.close_time]
        if fits:
            chosen = duration if duration in fits else max(fits)
            return candidate, candidate + timedelta(hours=chosen), chosen
        candidate = (candidate + timedelta(days=1)).replace(hour=place.open_time.hour, minute=place.open_time.minute)
    return candidate, candidate + timedelta(hours=1), 1


def window_fits(place, start, end):
    return (start.time() >= place.open_time and end.time() <= place.close_time
            and end.date() == start.date())


def validate_place_window(place, start, end):
    """A place keeps its own opening hours; a stay must fit inside them."""
    if not place.is_active:
        raise ValueError(f'{place.name} is not accepting parking reservations right now.')
    if start.time() < place.open_time or end.time() > place.close_time or end.date() != start.date():
        raise ValueError(
            f'{place.name} takes parking from {place.hours_label}. '
            'Choose an arrival time and duration that fit inside those hours.')


def origin_from(getter):
    try:
        lat = float(getter.get('lat'))
        lng = float(getter.get('lng'))
    except (TypeError, ValueError):
        return DEFAULT_ORIGIN
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return DEFAULT_ORIGIN
    return lat, lng


def counts_for(place_ids, start, end):
    """Bulk availability: {place_id: {'total': n, 'available': n}} for a window."""
    place_ids = list(place_ids)
    total_rows = (ParkingSlot.objects
                  .filter(place_id__in=place_ids, is_disabled=False)
                  .values('place_id').annotate(n=Count('id')))
    booked_rows = (Booking.objects
                   .filter(slot__place_id__in=place_ids, status=Booking.Status.CONFIRMED,
                           starts_at__lt=end, ends_at__gt=start)
                   .values('slot__place_id').annotate(n=Count('slot_id', distinct=True)))
    lots = (Lot.objects.filter(place_id__in=place_ids)
            .values('place_id').annotate(n=Count('id')))
    totals = {row['place_id']: row['n'] for row in total_rows}
    booked = {row['slot__place_id']: row['n'] for row in booked_rows}
    lot_counts = {row['place_id']: row['n'] for row in lots}
    return {pid: {'total': totals.get(pid, 0),
                  'available': max(0, totals.get(pid, 0) - booked.get(pid, 0)),
                  'lot_count': lot_counts.get(pid, 0)} for pid in place_ids}


def search_places(query, category):
    places = Place.objects.filter(is_active=True)
    if category and category in CATEGORY_LABELS:
        places = places.filter(category=category)
    for token in query.split()[:6]:
        token = token.strip()
        if not token:
            continue
        places = places.filter(
            Q(name__icontains=token) | Q(area__icontains=token) | Q(city__icontains=token) |
            Q(address__icontains=token) | Q(keywords__icontains=token) |
            Q(category__icontains=token))
    return places


def sort_places(places, sort, origin, counts):
    if sort == 'price':
        return sorted(places, key=lambda p: (p.price_per_hour, p.name))
    if sort == 'rating':
        return sorted(places, key=lambda p: (-float(p.rating), p.name))
    if sort == 'nearby':
        return sorted(places, key=lambda p: (p.distance_from(*origin) or 0, p.name))
    return sorted(places, key=lambda p: (-counts[p.id]['available'], p.distance_from(*origin) or 0))


def place_payload(place, start, end, origin, counts=None):
    counts = counts or counts_for([place.id], start, end)
    data = place.as_dict(start, end, origin, counts=counts[place.id])
    data['lots'] = [lot.as_dict() for lot in place.lots.all()]
    return data


@ensure_csrf_cookie
@xframe_options_exempt
def index(request, page='dashboard', slug=None):
    context = {'page': page, 'demo_mode': settings.DEMO_MODE, 'place_slug': slug or '',
               'static_version': getattr(settings, 'STATIC_VERSION', '1')}
    if slug:
        place = Place.objects.filter(slug=slug, is_active=True).first()
        if place is None:
            return render(request, 'parking/index.html', {**context, 'page': 'notfound'}, status=404)
        context['place_name'] = place.name
    return render(request, 'parking/index.html', context)


@require_GET
@api
def overview(request):
    start, end, duration = parse_window(request.GET)
    data = {
        'user': user_data(request.user),
        'demo_mode': settings.DEMO_MODE,
        'categories': CATEGORIES,
        'durations': DURATIONS,
        'sorts': SORTS,
        'timezone': settings.TIME_ZONE,
        'server_time': timezone.now().isoformat(),
        'hours': {'open': '06:00', 'close': '23:59'},
        'window': {'starts_at': start.isoformat(), 'ends_at': end.isoformat(), 'duration': duration},
        'suggestions': ['Lulu Mall', 'Theatre on MG Road', 'Restaurant parking', 'College', 'Hospital'],
        'totals': {
            'places': Place.objects.filter(is_active=True).count(),
            'slots': ParkingSlot.objects.filter(is_disabled=False).count(),
            'cities': Place.objects.filter(is_active=True).values('city').distinct().count(),
        },
    }
    if request.user.is_authenticated:
        bookings = request.user.bookings.select_related('slot', 'slot__lot', 'slot__place', 'user')
        data['bookings'] = [b.as_dict() for b in bookings]
        data['upcoming_count'] = sum(b.effective_status() == 'confirmed' for b in bookings)
    else:
        data['bookings'] = []
        data['upcoming_count'] = 0
    return JsonResponse(data)


@require_GET
@api
def places(request):
    start, end, duration = parse_window(request.GET)
    query = str(request.GET.get('q', '')).strip()[:80]
    category = str(request.GET.get('category', '')).strip()
    sort = str(request.GET.get('sort', 'nearby')).strip()
    if sort not in SORTS:
        sort = 'nearby'
    origin = origin_from(request.GET)
    found = list(search_places(query, category))
    counts = counts_for([p.id for p in found], start, end)
    found = sort_places(found, sort, origin, counts)
    return JsonResponse({
        'places': [place_payload(p, start, end, origin, counts) for p in found],
        'query': query, 'category': category, 'sort': sort,
        'origin': {'lat': origin[0], 'lng': origin[1], 'default': origin == DEFAULT_ORIGIN},
        'categories': CATEGORIES,
        'window': {'starts_at': start.isoformat(), 'ends_at': end.isoformat(), 'duration': duration},
        'result_count': len(found),
    })


@require_GET
@api
def place_detail(request, slug):
    place = get_object_or_404(Place, slug=slug, is_active=True)
    start, end, duration = parse_window(request.GET)
    origin = origin_from(request.GET)
    fits = window_fits(place, start, end)
    suggested_start, suggested_end, suggested_duration = fit_window(place, start, duration)
    slots = [s.as_dict(start, end) for s in place.slots.select_related('lot').all()]
    counts = counts_for([place.id], start, end)[place.id]
    return JsonResponse({
        'place': place_payload(place, start, end, origin, {place.id: counts}),
        'slots': slots,
        'available': counts['available'], 'total': counts['total'],
        'fits': fits,
        'durations': [d for d in DURATIONS if _fits(d, place, start)],
        'window': {'starts_at': start.isoformat(), 'ends_at': end.isoformat(), 'duration': duration},
        'suggested': {
            'date': suggested_start.strftime('%Y-%m-%d'),
            'start_time': suggested_start.strftime('%H:%M'),
            'duration': suggested_duration,
            'starts_at': suggested_start.isoformat(), 'ends_at': suggested_end.isoformat(),
        },
    })


def _fits(duration, place, start):
    return (start + timedelta(hours=duration)).time() <= place.close_time


def auth_allowed(request):
    key = 'auth-attempts-' + str(request.META.get('REMOTE_ADDR', 'local'))
    attempts = cache.get(key, 0)
    if attempts >= 20:
        return False
    cache.set(key, attempts + 1, 300)
    return True


@require_POST
@api
def sign_in(request):
    if not auth_allowed(request):
        return JsonResponse({'error': 'Too many sign-in attempts. Please try again in five minutes.'}, status=429)
    data = body(request)
    email = str(data.get('email', '')).strip().lower()
    password = str(data.get('password', ''))
    user = authenticate(request, username=email, password=password)
    if user is None:
        return JsonResponse({'error': 'That email and password do not match. Please try again.'}, status=401)
    login(request, user)
    return JsonResponse({'user': user_data(user)})


@require_POST
@api
def register(request):
    if not auth_allowed(request):
        return JsonResponse({'error': 'Too many attempts. Please try again in five minutes.'}, status=429)
    data = body(request)
    name = ' '.join(str(data.get('name', '')).split())
    email = str(data.get('email', '')).strip().lower()
    password = str(data.get('password', ''))
    if len(name) < 2 or len(name) > 100:
        return JsonResponse({'error': 'Please enter your name (2–100 characters).'}, status=400)
    if len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        return JsonResponse({'error': 'Please enter a valid email address.'}, status=400)
    try:
        validate_password(password)
    except ValidationError as exc:
        return JsonResponse({'error': ' '.join(exc.messages)}, status=400)
    try:
        with transaction.atomic():
            parts = name.split(' ', 1)
            user = User.objects.create_user(username=email, email=email, password=password,
                                            first_name=parts[0], last_name=parts[1] if len(parts) > 1 else '')
    except IntegrityError:
        return JsonResponse({'error': 'An account with that email already exists. Try signing in.'}, status=409)
    login(request, user)
    return JsonResponse({'user': user_data(user)}, status=201)


@require_POST
@api
def demo_sign_in(request):
    if not settings.DEMO_MODE:
        return JsonResponse({'error': 'Demo access is disabled.'}, status=403)
    if not auth_allowed(request):
        return JsonResponse({'error': 'Please try again in five minutes.'}, status=429)
    role = body(request).get('role', 'driver')
    if role not in ['driver', 'admin']:
        return JsonResponse({'error': 'Choose a valid demo account.'}, status=400)
    email = 'driver@parkwise.demo' if role == 'driver' else 'admin@parkwise.demo'
    user = User.objects.filter(username=email).first()
    if user is None:
        return JsonResponse({'error': 'Demo data has not been initialized. Run python manage.py seed_demo.'}, status=503)
    login(request, user)
    return JsonResponse({'user': user_data(user)})


@require_POST
def sign_out(request):
    logout(request)
    return JsonResponse({'ok': True})


@require_POST
@api
def create_booking(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Please sign in to reserve your parking slot.'}, status=401)
    data = body(request)
    start, end, duration = parse_window(data)
    plate = ' '.join(str(data.get('vehicle_plate', '')).upper().split())
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9 -]{2,18}[A-Z0-9]', plate):
        return JsonResponse({'error': 'Enter a vehicle number using 4–20 letters, numbers, spaces, or hyphens.'}, status=400)
    slot_id = data.get('slot_id')
    if type(slot_id) is not int:
        return JsonResponse({'error': 'Select a parking slot on the map.'}, status=400)
    with transaction.atomic():
        # Take the SQLite write lock before reading availability so two drivers
        # cannot reserve the same slot at the same moment.
        updated = ParkingSlot.objects.filter(pk=slot_id).update(updated_at=timezone.now())
        if not updated:
            return JsonResponse({'error': 'That parking slot no longer exists. Refresh the map.'}, status=404)
        slot = ParkingSlot.objects.select_related('place').get(pk=slot_id)
        place = slot.place
        validate_place_window(place, start, end)
        if slot.is_disabled:
            return JsonResponse({'error': 'This slot is temporarily unavailable. Please choose another.'}, status=409)
        if Booking.objects.filter(slot=slot, status=Booking.Status.CONFIRMED, starts_at__lt=end, ends_at__gt=start).exists():
            return JsonResponse({'error': 'Someone just reserved this slot for that time. Choose another green slot.'}, status=409)
        if Booking.objects.filter(slot__place=place, user=request.user, status=Booking.Status.CONFIRMED,
                                  starts_at__lt=end, ends_at__gt=start).exists():
            return JsonResponse({'error': f'You already have a reservation at {place.name} during this time. '
                                          'Cancel it before booking another.'}, status=409)
        fee = place.price_per_hour * duration
        booking = Booking.objects.create(user=request.user, slot=slot, vehicle_plate=plate,
                                         starts_at=start, ends_at=end, fee=fee)
    return JsonResponse({'booking': booking.as_dict()}, status=201)


@require_POST
@api
def cancel_booking(request, booking_id):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Please sign in to manage your reservations.'}, status=401)
    with transaction.atomic():
        booking = get_object_or_404(Booking.objects.select_related('slot'), pk=booking_id, user=request.user)
        if booking.status != Booking.Status.CONFIRMED or booking.starts_at <= timezone.now():
            return JsonResponse({'error': 'Only upcoming reservations can be cancelled.'}, status=409)
        booking.status = Booking.Status.CANCELLED
        booking.cancelled_at = timezone.now()
        booking.save(update_fields=['status', 'cancelled_at'])
    return JsonResponse({'booking': booking.as_dict()})


def escape_ics(value):
    return str(value).replace('\\', '\\\\').replace('\r', '').replace('\n', '\\n').replace(',', '\\,').replace(';', '\\;')


@require_GET
def booking_calendar(request, booking_id):
    if not request.user.is_authenticated:
        return HttpResponse('Sign in required.', status=401)
    booking = get_object_or_404(Booking.objects.select_related('slot', 'slot__place'), pk=booking_id, user=request.user)
    if booking.status != Booking.Status.CONFIRMED:
        return HttpResponse('This reservation is no longer active.', status=409)
    place = booking.slot.place
    stamp = timezone.now().strftime('%Y%m%dT%H%M%SZ')
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Parkwise//Place Parking//EN', 'CALSCALE:GREGORIAN',
             'BEGIN:VEVENT', f'UID:{booking.reference}@parkwise.local', f'DTSTAMP:{stamp}',
             'DTSTART:' + booking.starts_at.strftime('%Y%m%dT%H%M%SZ'),
             'DTEND:' + booking.ends_at.strftime('%Y%m%dT%H%M%SZ'),
             f'SUMMARY:{escape_ics("Parking · " + place.name + " · " + booking.slot.code)}',
             f'LOCATION:{escape_ics(place.address + ", " + place.area + ", " + place.city)}',
             f'DESCRIPTION:{escape_ics("Reservation " + booking.reference + " · Lot " + booking.slot.lot.code +
                                       " · Vehicle " + booking.vehicle_plate)}',
             'END:VEVENT', 'END:VCALENDAR', '']
    response = HttpResponse('\r\n'.join(lines), content_type='text/calendar; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{booking.reference}.ics"'
    return response


# ---------------------------------------------------------------- admin console

@require_GET
@staff_api
def admin_overview(request):
    now = timezone.now()
    end = now + timedelta(hours=1)
    bookings = Booking.objects.select_related('slot', 'slot__lot', 'slot__place', 'user')[:500]
    place_list = list(Place.objects.all())
    counts = counts_for([p.id for p in place_list], now, end)
    return JsonResponse({
        'bookings': [b.as_dict() for b in bookings],
        'places': [p.as_dict(now, end, None, counts=counts[p.id]) for p in place_list],
        'slots': [s.as_dict(now, end) for s in ParkingSlot.objects.select_related('place', 'lot')[:600]],
        'categories': CATEGORIES,
        'user_count': User.objects.count(),
        'active_count': Booking.objects.filter(status=Booking.Status.CONFIRMED, ends_at__gt=now).count(),
        'total_bookings': Booking.objects.count(),
        'total_slots': ParkingSlot.objects.count(),
    })


@require_POST
@staff_api
@api
def admin_add_place(request):
    data = body(request)
    name = ' '.join(str(data.get('name', '')).split())
    category = str(data.get('category', '')).strip()
    area = ' '.join(str(data.get('area', '')).split())
    city = ' '.join(str(data.get('city', 'Kochi')).split()) or 'Kochi'
    address = ' '.join(str(data.get('address', '')).split()) or f'{area}, {city}'
    try:
        price = int(data.get('price_per_hour', 20))
        open_time = datetime.strptime(str(data.get('open_time', '09:00')), '%H:%M').time()
        close_time = datetime.strptime(str(data.get('close_time', '22:00')), '%H:%M').time()
    except (TypeError, ValueError):
        raise ValueError('Check the price and opening hours you entered.')
    if not 2 <= len(name) <= 120:
        raise ValueError('Enter a place name (2–120 characters).')
    if category not in CATEGORY_LABELS:
        raise ValueError('Choose a valid place type.')
    if not 1 <= len(area) <= 80:
        raise ValueError('Enter the area or locality for this place.')
    if not 0 <= price <= 2000:
        raise ValueError('Set an hourly price between ₹0 and ₹2000.')
    if open_time >= close_time:
        raise ValueError('Opening time must be before closing time.')
    slug = slugify(name)[:70] or 'place'
    base_slug, counter = slug, 2
    while Place.objects.filter(slug=slug).exists():
        slug = f'{base_slug}-{counter}'
        counter += 1
    with transaction.atomic():
        place = Place.objects.create(
            slug=slug, name=name, category=category, area=area, city=city, address=address,
            latitude=data.get('latitude') or 9.9312, longitude=data.get('longitude') or 76.2673,
            price_per_hour=price, open_time=open_time, close_time=close_time,
            keywords=f'{name} {area} {city} {CATEGORY_LABELS[category]}'.lower())
        for code, lot_name, walk in [('A', 'Main lot', '2 min walk'), ('B', 'Overflow lot', '4 min walk')]:
            lot = Lot.objects.create(place=place, code=code, name=lot_name, walk=walk)
            for index in range(1, 9):
                ParkingSlot.objects.create(place=place, lot=lot, code=f'{code}{index:02d}')
    return JsonResponse({'place': place.as_dict(counts={'total': 16, 'available': 16})}, status=201)


@require_POST
@staff_api
@api
def admin_update_place(request, place_id):
    place = get_object_or_404(Place, pk=place_id)
    data = body(request)
    if not isinstance(data.get('is_active'), bool):
        return JsonResponse({'error': 'Choose whether this place is open for bookings.'}, status=400)
    place.is_active = data['is_active']
    place.save(update_fields=['is_active'])
    return JsonResponse({'place': place.as_dict(), 'message': 'Existing reservations are preserved.'})


@require_POST
@staff_api
@api
def admin_add_slot(request):
    data = body(request)
    place = get_object_or_404(Place, pk=data.get('place_id'))
    code = str(data.get('code', '')).strip().upper()
    vehicle_type = str(data.get('vehicle_type', 'car'))
    if not re.fullmatch(r'[A-C][0-9]{2,3}', code):
        return JsonResponse({'error': 'Use a lot letter followed by 2–3 digits, for example A09.'}, status=400)
    lot = get_object_or_404(Lot, place=place, code=code[0])
    if vehicle_type not in ParkingSlot.Vehicle.values:
        return JsonResponse({'error': 'Choose a valid vehicle type.'}, status=400)
    if place.slots.count() >= MAX_SLOTS_PER_PLACE:
        return JsonResponse({'error': f'A place supports up to {MAX_SLOTS_PER_PLACE} slots in this prototype.'}, status=400)
    try:
        with transaction.atomic():
            slot = ParkingSlot.objects.create(place=place, lot=lot, code=code, vehicle_type=vehicle_type)
    except IntegrityError:
        return JsonResponse({'error': 'That slot number already exists at this place.'}, status=409)
    return JsonResponse({'slot': slot.as_dict()}, status=201)


@require_POST
@staff_api
@api
def admin_update_slot(request, slot_id):
    slot = get_object_or_404(ParkingSlot, pk=slot_id)
    data = body(request)
    if not isinstance(data.get('is_disabled'), bool):
        return JsonResponse({'error': 'Choose whether the slot is open or closed.'}, status=400)
    slot.is_disabled = data['is_disabled']
    slot.save(update_fields=['is_disabled', 'updated_at'])
    return JsonResponse({'slot': slot.as_dict(), 'message': 'Existing reservations are preserved. Cancel them separately if needed.'})


@require_POST
@staff_api
def admin_cancel_booking(request, booking_id):
    with transaction.atomic():
        booking = get_object_or_404(Booking, pk=booking_id)
        if booking.status != Booking.Status.CONFIRMED or booking.ends_at <= timezone.now():
            return JsonResponse({'error': 'Only current or upcoming reservations can be cancelled.'}, status=409)
        booking.status = Booking.Status.CANCELLED
        booking.cancelled_at = timezone.now()
        booking.save(update_fields=['status', 'cancelled_at'])
    return JsonResponse({'booking': booking.as_dict()})


@require_GET
@staff_api
def export_bookings(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="parkwise-reservations.csv"'
    writer = csv.writer(response)
    writer.writerow(['Reference', 'Driver', 'Email', 'Place', 'Category', 'Area', 'Lot', 'Slot',
                     'Vehicle', 'Arrival (UTC)', 'Departure (UTC)', 'Fee (INR)', 'Status'])
    for b in Booking.objects.select_related('slot', 'slot__lot', 'slot__place', 'user'):
        place = b.slot.place
        writer.writerow([b.reference, b.user.get_full_name(), b.user.email, place.name,
                         place.get_category_display(), place.area, b.slot.lot.code, b.slot.code,
                         b.vehicle_plate, b.starts_at.isoformat(), b.ends_at.isoformat(),
                         b.fee, b.effective_status()])
    return response
