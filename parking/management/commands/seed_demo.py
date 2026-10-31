"""Seed Parkwise with sample places around Kochi, their parking lots and slots.

Safe to re-run: places are matched by slug, lots and slots are only created when
missing, and sample reservations are only added to an empty bookings table.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from parking.models import Booking, Lot, ParkingSlot, Place

PLACES = [
    {
        'name': 'Lulu Mall', 'category': 'mall', 'area': 'Edappally', 'city': 'Kochi',
        'address': '34/1000 N.H. Bypass, Edappally, Kochi', 'pincode': '682024',
        'lat': 10.027000, 'lng': 76.308700, 'rating': '4.5', 'price': 25,
        'open': '10:00', 'close': '23:00', 'note': 'Valet available at the north entrance',
        'keywords': 'lulu mall edappally shopping pvr cinema multiplex hypermarket',
        'lots': [
            ('A', 'Basement 1', '2 min walk to the mall atrium', 'CARS + EV CHARGING', {'car': 10, 'ev': 3}),
            ('B', 'Basement 2', '4 min walk to the atrium', 'CARS + ACCESSIBLE', {'car': 9, 'accessible': 2}),
            ('C', 'Rooftop deck', '6 min walk, lift available', 'TWO-WHEELERS', {'bike': 10}),
        ],
    },
    {
        'name': 'Oberon Mall', 'category': 'mall', 'area': 'Edappally North', 'city': 'Kochi',
        'address': 'NH 47 Bypass, Edappally North, Kochi', 'pincode': '682024',
        'lat': 10.032100, 'lng': 76.307600, 'rating': '4.2', 'price': 20,
        'open': '10:00', 'close': '22:00', 'note': '',
        'keywords': 'oberon mall edappally north shopping food court cinema',
        'lots': [
            ('A', 'Front apron', '1 min walk to the main door', 'CARS + ACCESSIBLE', {'car': 9, 'accessible': 2}),
            ('B', 'Side lot', '3 min walk to the main door', 'CARS + EV CHARGING', {'car': 8, 'ev': 2}),
            ('C', 'Two-wheeler bay', '2 min walk', 'TWO-WHEELERS', {'bike': 8}),
        ],
    },
    {
        'name': 'Centre Square Mall', 'category': 'mall', 'area': 'MG Road', 'city': 'Kochi',
        'address': '40/2045 M.G. Road, Ernakulam, Kochi', 'pincode': '682035',
        'lat': 9.972900, 'lng': 76.283200, 'rating': '4.1', 'price': 30,
        'open': '09:30', 'close': '22:30', 'note': 'Central Kochi — busiest between 6 and 9 PM',
        'keywords': 'centre square mall mg road ernakulam cinepolis shopping metro',
        'lots': [
            ('A', 'Basement parking', '2 min walk to the escalator', 'CARS + EV CHARGING', {'car': 8, 'ev': 2}),
            ('B', 'Multi-level 1', '3 min walk', 'CARS + ACCESSIBLE', {'car': 8, 'accessible': 1}),
            ('C', 'Two-wheeler deck', '1 min walk', 'TWO-WHEELERS', {'bike': 9}),
        ],
    },
    {
        'name': 'PVR Lulu Edappally', 'category': 'theatre', 'area': 'Edappally', 'city': 'Kochi',
        'address': 'Lulu Mall, 4th floor, Edappally, Kochi', 'pincode': '682024',
        'lat': 10.027400, 'lng': 76.309000, 'rating': '4.4', 'price': 25,
        'open': '09:00', 'close': '23:30', 'note': 'Evening shows fill up first',
        'keywords': 'pvr lulu cinema theatre movie multiplex edappally shows',
        'lots': [
            ('A', 'Cinema level parking', '2 min walk to the box office', 'CARS + EV CHARGING', {'car': 10, 'ev': 2}),
            ('B', 'Show-day overflow', '5 min walk to the box office', 'CARS + ACCESSIBLE', {'car': 8, 'accessible': 1}),
            ('C', 'Two-wheeler bay', '3 min walk', 'TWO-WHEELERS', {'bike': 8}),
        ],
    },
    {
        'name': 'Shenoys Theatre', 'category': 'theatre', 'area': 'MG Road', 'city': 'Kochi',
        'address': 'Shenoys Junction, M.G. Road, Kochi', 'pincode': '682016',
        'lat': 9.970800, 'lng': 76.286300, 'rating': '4.0', 'price': 15,
        'open': '09:00', 'close': '23:00', 'note': 'No underground parking — surface lot only',
        'keywords': 'shenoys theatre cinema mg road movie shows screen',
        'lots': [
            ('A', 'Theatre front lot', '1 min walk to the gate', 'CARS', {'car': 8}),
            ('B', 'Shenoys side street', '3 min walk to the gate', 'CARS + TWO-WHEELERS', {'car': 4, 'bike': 6}),
            ('C', 'Overflow ground', '5 min walk', 'TWO-WHEELERS', {'bike': 6}),
        ],
    },
    {
        'name': 'Vanitha Cineplex', 'category': 'theatre', 'area': 'MG Road', 'city': 'Kochi',
        'address': 'M.G. Road, Ernakulam, Kochi', 'pincode': '682035',
        'lat': 9.973600, 'lng': 76.282500, 'rating': '3.9', 'price': 15,
        'open': '10:00', 'close': '22:30', 'note': '',
        'keywords': 'vanitha cineplex movie theatre mg road ernakulam cinema',
        'lots': [
            ('A', 'Main lot', '2 min walk to the ticket counter', 'CARS', {'car': 7}),
            ('B', 'Annexe lot', '4 min walk', 'CARS + ACCESSIBLE', {'car': 5, 'accessible': 1}),
            ('C', 'Two-wheeler bay', '2 min walk', 'TWO-WHEELERS', {'bike': 6}),
        ],
    },
    {
        'name': 'Paragon Restaurant, MG Road', 'category': 'restaurant', 'area': 'MG Road', 'city': 'Kochi',
        'address': 'Banerji Road, M.G. Road, Kochi', 'pincode': '682031',
        'lat': 9.975400, 'lng': 76.283600, 'rating': '4.6', 'price': 30,
        'open': '11:00', 'close': '23:00', 'note': 'Short stays only — 2 hours recommended',
        'keywords': 'paragon restaurant biryani malabar food mg road dining lunch dinner',
        'lots': [
            ('A', 'Restaurant valet bay', '1 min walk to the entrance', 'VALET + CARS', {'car': 6}),
            ('B', 'Banerji Road side', '3 min walk to the entrance', 'CARS + ACCESSIBLE', {'car': 5, 'accessible': 1}),
            ('C', 'Two-wheeler parking', '1 min walk', 'TWO-WHEELERS', {'bike': 8}),
        ],
    },
    {
        'name': 'Dhe Puttu, Kaloor', 'category': 'restaurant', 'area': 'Kaloor', 'city': 'Kochi',
        'address': 'Kaloor Kadavanthra Road, Kaloor, Kochi', 'pincode': '682017',
        'lat': 9.995100, 'lng': 76.293300, 'rating': '4.3', 'price': 20,
        'open': '11:00', 'close': '22:30', 'note': '',
        'keywords': 'dhe puttu restaurant kerala food kaloor dinner lunch dining',
        'lots': [
            ('A', 'Front lot', '1 min walk', 'CARS', {'car': 6}),
            ('B', 'Rear lot', '2 min walk', 'CARS + EV CHARGING', {'car': 4, 'ev': 2}),
            ('C', 'Two-wheeler bay', '1 min walk', 'TWO-WHEELERS', {'bike': 6}),
        ],
    },
    {
        'name': 'Oceanos Restaurant', 'category': 'restaurant', 'area': 'Fort Kochi', 'city': 'Kochi',
        'address': 'Elphinstone Road, Fort Kochi', 'pincode': '682001',
        'lat': 9.965800, 'lng': 76.242200, 'rating': '4.4', 'price': 40,
        'open': '11:30', 'close': '22:30', 'note': 'Heritage street — narrow parking, arrive early',
        'keywords': 'oceanos seafood restaurant fort kochi heritage dining tourist',
        'lots': [
            ('A', 'Seafront lot', '2 min walk to the restaurant', 'CARS', {'car': 6}),
            ('B', 'Elphinstone street', '3 min walk', 'CARS + ACCESSIBLE', {'car': 4, 'accessible': 1}),
            ('C', 'Scooter parking', '1 min walk', 'TWO-WHEELERS', {'bike': 6}),
        ],
    },
    {
        'name': 'CUSAT Main Campus', 'category': 'college', 'area': 'Kalamassery', 'city': 'Kochi',
        'address': 'South Kalamassery, Kochi', 'pincode': '682022',
        'lat': 10.046600, 'lng': 76.321800, 'rating': '4.3', 'price': 10,
        'open': '07:00', 'close': '20:00', 'note': 'Visitors report at the main gate',
        'keywords': 'cusat cochin university science technology college campus kalamassery students',
        'lots': [
            ('A', 'Administrative block', '3 min walk to the admin office', 'CARS + ACCESSIBLE', {'car': 9, 'accessible': 2}),
            ('B', 'Library quadrangle', '5 min walk to the library', 'CARS + EV CHARGING', {'car': 8, 'ev': 2}),
            ('C', 'Student two-wheeler stand', '2 min walk to the canteen', 'TWO-WHEELERS', {'bike': 12}),
        ],
    },
    {
        'name': "Maharaja's College", 'category': 'college', 'area': 'Ernakulam', 'city': 'Kochi',
        'address': 'Park Avenue, Ernakulam, Kochi', 'pincode': '682011',
        'lat': 9.973700, 'lng': 76.279500, 'rating': '4.2', 'price': 10,
        'open': '07:30', 'close': '19:00', 'note': '',
        'keywords': 'maharajas college ernakulam campus park avenue students arts science',
        'lots': [
            ('A', 'Main gate lot', '2 min walk to the main block', 'CARS', {'car': 8}),
            ('B', 'Ground annexe', '4 min walk', 'CARS + TWO-WHEELERS', {'car': 5, 'bike': 5}),
            ('C', 'Cycle and scooter stand', '3 min walk', 'TWO-WHEELERS', {'bike': 8}),
        ],
    },
    {
        'name': 'Amrita Hospital, Edappally', 'category': 'hospital', 'area': 'Edappally', 'city': 'Kochi',
        'address': 'AIMS Ponekkara, Edappally, Kochi', 'pincode': '682041',
        'lat': 10.033600, 'lng': 76.287400, 'rating': '4.5', 'price': 15,
        'open': '06:00', 'close': '23:00', 'note': 'Emergency bays are never sold as reservations',
        'keywords': 'amrita hospital aims edappally medical emergency patients clinic',
        'lots': [
            ('A', 'OP block parking', '2 min walk to the OP counter', 'CARS + ACCESSIBLE', {'car': 10, 'accessible': 3}),
            ('B', 'Tower parking', '5 min walk to the tower', 'CARS + EV CHARGING', {'car': 8, 'ev': 2}),
            ('C', 'Two-wheeler shelter', '3 min walk', 'TWO-WHEELERS', {'bike': 10}),
        ],
    },
    {
        'name': 'Aster Medcity', 'category': 'hospital', 'area': 'Kuttisahib Road', 'city': 'Kochi',
        'address': 'Kuttisahib Road, South Chittoor, Kochi', 'pincode': '682027',
        'lat': 10.029900, 'lng': 76.258900, 'rating': '4.4', 'price': 20,
        'open': '06:00', 'close': '23:00', 'note': '',
        'keywords': 'aster medcity hospital chittoor medical clinic emergency health',
        'lots': [
            ('A', 'Main block parking', '2 min walk to reception', 'CARS + ACCESSIBLE', {'car': 9, 'accessible': 2}),
            ('B', 'Annexe parking', '4 min walk', 'CARS', {'car': 8}),
            ('C', 'Two-wheeler bay', '2 min walk', 'TWO-WHEELERS', {'bike': 8}),
        ],
    },
    {
        'name': 'Infopark Phase 1', 'category': 'office', 'area': 'Kakkanad', 'city': 'Kochi',
        'address': 'Infopark Campus, Kakkanad, Kochi', 'pincode': '682042',
        'lat': 10.010700, 'lng': 76.360000, 'rating': '4.2', 'price': 25,
        'open': '08:00', 'close': '21:00', 'note': 'Visitor passes are validated at the gate',
        'keywords': 'infopark phase 1 kakkanad office tech park campus work visitors',
        'lots': [
            ('A', 'Athulya block', '3 min walk to Athulya', 'CARS + EV CHARGING', {'car': 10, 'ev': 3}),
            ('B', 'Jyothirmaya block', '4 min walk to Jyothirmaya', 'CARS + ACCESSIBLE', {'car': 9, 'accessible': 2}),
            ('C', 'Two-wheeler shed', '2 min walk to the food court', 'TWO-WHEELERS', {'bike': 12}),
        ],
    },
    {
        'name': 'Jawaharlal Nehru Stadium', 'category': 'stadium', 'area': 'Kaloor', 'city': 'Kochi',
        'address': 'Stadium Link Road, Kaloor, Kochi', 'pincode': '682017',
        'lat': 9.997300, 'lng': 76.298900, 'rating': '4.3', 'price': 20,
        'open': '09:00', 'close': '22:00', 'note': 'Match days switch the venue to event pricing',
        'keywords': 'jawaharlal nehru stadium kaloor match football cricket event kaloor',
        'lots': [
            ('A', 'North stand lot', '3 min walk to the north stand', 'CARS', {'car': 10}),
            ('B', 'South stand lot', '4 min walk to the south stand', 'CARS + ACCESSIBLE', {'car': 8, 'accessible': 2}),
            ('C', 'Two-wheeler ground', '2 min walk to the gate', 'TWO-WHEELERS', {'bike': 12}),
        ],
    },
]


class Command(BaseCommand):
    help = 'Initialize sample places, parking lots, slots and clearly labeled demo accounts.'

    @transaction.atomic
    def handle(self, *args, **options):
        for spec in PLACES:
            place, created = Place.objects.get_or_create(
                slug=spec['name'].lower().replace(' ', '-').replace(',', '').replace("'", ''),
                defaults={
                    'name': spec['name'], 'category': spec['category'], 'area': spec['area'],
                    'city': spec['city'], 'address': spec['address'], 'pincode': spec['pincode'],
                    'latitude': Decimal(str(spec['lat'])), 'longitude': Decimal(str(spec['lng'])),
                    'rating': Decimal(spec['rating']), 'price_per_hour': spec['price'],
                    'open_time': spec['open'], 'close_time': spec['close'],
                    'open_note': spec['note'], 'keywords': spec['keywords'],
                })
            if created:
                self.stdout.write(f'  + {place.name}')
            for code, name, walk, tagline, plan in spec['lots']:
                lot, lot_created = Lot.objects.get_or_create(
                    place=place, code=code,
                    defaults={'name': name, 'walk': walk, 'tagline': tagline})
                if not lot_created:
                    continue
                number = 1
                for vehicle_type, count in plan.items():
                    for _ in range(count):
                        ParkingSlot.objects.create(place=place, lot=lot,
                                                   code=f'{code}{number:02d}', vehicle_type=vehicle_type)
                        number += 1

        users = self.create_demo_users()
        self.seed_sample_bookings(users)
        self.stdout.write(self.style.SUCCESS(
            f'Parkwise ready: {Place.objects.count()} places, {Lot.objects.count()} lots, '
            f'{ParkingSlot.objects.count()} slots, {Booking.objects.count()} reservations.'))

    def create_demo_users(self):
        accounts = [
            {'email': 'driver@parkwise.demo', 'first_name': 'Diya', 'last_name': 'Driver', 'is_staff': False},
            {'email': 'admin@parkwise.demo', 'first_name': 'Venue', 'last_name': 'Admin', 'is_staff': True},
        ]
        accounts += [{'email': f'visitor{i}@parkwise.demo', 'first_name': 'Sample', 'last_name': f'Driver {i}',
                      'is_staff': False} for i in range(1, 7)]
        created = []
        for account in accounts:
            user, _ = User.objects.get_or_create(
                username=account['email'],
                defaults={'email': account['email'], 'first_name': account['first_name'],
                          'last_name': account['last_name'], 'is_staff': account['is_staff']})
            user.set_password('ParkwiseAdmin123!' if account['is_staff'] else 'ParkwiseDemo123!')
            user.is_staff = account['is_staff']
            user.save()
            created.append(user)
        # Only the extra sample drivers hold seeded reservations — the shared
        # driver demo account must start with a clean booking list.
        return [u for u in created if u.username.startswith('visitor')]

    def seed_sample_bookings(self, users):
        """Make availability look lived-in on a fresh install."""
        if Booking.objects.exists():
            self.stdout.write('  · Existing reservations kept, no sample bookings added.')
            return
        now = timezone.localtime()
        hour = now.replace(minute=0, second=0, microsecond=0)
        plates = ['KL07AB1234', 'KL11CD5678', 'KL39EF9012', 'KL05GH3456', 'KL43IJ7890', 'KL01KL2345']
        added = 0
        for index, place in enumerate(Place.objects.order_by('id')):
            slots = list(place.slots.filter(vehicle_type='car')[:8])
            for offset, slot in enumerate(slots[:2]):
                start = hour + timedelta(minutes=30 * offset)
                if start.time() < place.open_time:
                    start = hour.replace(hour=place.open_time.hour)
                end = start + timedelta(hours=2)
                if end.time() > place.close_time:
                    continue
                user = users[(index + offset) % len(users)]
                Booking.objects.create(user=user, slot=slot, vehicle_plate=plates[(index + offset) % len(plates)],
                                       starts_at=start, ends_at=end,
                                       fee=place.price_per_hour * 2 if place.price_per_hour <= 20 else place.price_per_hour * 2)
                added += 1
            # One reservation further ahead, so the bookings screens are not all "today".
            future_slot = place.slots.filter(vehicle_type='car').last()
            if future_slot:
                start = (hour + timedelta(days=1)).replace(hour=max(place.open_time.hour + 2, 10), minute=0)
                if start.time() < place.open_time:
                    start = start.replace(hour=place.open_time.hour + 1)
                end = start + timedelta(hours=1)
                if end.time() <= place.close_time:
                    Booking.objects.create(user=users[index % len(users)], slot=future_slot,
                                           vehicle_plate=plates[index % len(plates)],
                                           starts_at=start, ends_at=end, fee=place.price_per_hour)
                    added += 1
        self.stdout.write(f'  + {added} sample reservations for a realistic demo.')
