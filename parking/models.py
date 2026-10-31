"""Data model for the Parkwise place-search parking app.

Hierarchy:  Place  ->  Lot (a parking area inside the place)  ->  ParkingSlot
A Booking belongs to one ParkingSlot, so it implicitly belongs to a lot and a place.
"""
import math
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


def haversine_km(lat1, lng1, lat2, lng2):
    """Great-circle distance in kilometres between two points."""
    if None in (lat1, lng1, lat2, lng2):
        return None
    radius = 6371.0088
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dp = p2 - p1
    dl = math.radians(float(lng2) - float(lng1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class Place(models.Model):
    """A venue a driver can search for and park at: mall, theatre, restaurant…"""

    class Category(models.TextChoices):
        MALL = 'mall', 'Mall'
        THEATRE = 'theatre', 'Theatre'
        RESTAURANT = 'restaurant', 'Restaurant'
        COLLEGE = 'college', 'College'
        HOSPITAL = 'hospital', 'Hospital'
        OFFICE = 'office', 'Office park'
        STADIUM = 'stadium', 'Stadium'

    slug = models.SlugField(max_length=80, unique=True)
    name = models.CharField(max_length=120)
    category = models.CharField(max_length=12, choices=Category.choices, default=Category.MALL)
    address = models.CharField(max_length=200)
    area = models.CharField(max_length=80, help_text='Locality, e.g. Edappally')
    city = models.CharField(max_length=80, default='Kochi')
    pincode = models.CharField(max_length=10, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    rating = models.DecimalField(max_digits=2, decimal_places=1, default=Decimal('4.0'))
    price_per_hour = models.PositiveIntegerField(default=20, help_text='Rupees per hour')
    open_time = models.TimeField(default='09:00')
    close_time = models.TimeField(default='23:00')
    open_note = models.CharField(max_length=80, blank=True, help_text='e.g. Valet available after 6 PM')
    keywords = models.CharField(max_length=240, blank=True, help_text='Extra search words, comma separated')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        indexes = [models.Index(fields=['category', 'is_active'])]

    def __str__(self):
        return self.name

    @property
    def hours_label(self):
        def fmt(value):
            return value.strftime('%I:%M %p').lstrip('0')
        return f'{fmt(self.open_time)} – {fmt(self.close_time)}'

    @property
    def category_label(self):
        return self.get_category_display()

    def distance_from(self, lat, lng):
        return haversine_km(lat, lng, self.latitude, self.longitude)

    def as_dict(self, start=None, end=None, origin=None, counts=None):
        now = timezone.now()
        start = start or now
        end = end or now + timezone.timedelta(hours=2)
        counts = counts or {}
        distance = None
        if origin and origin[0] is not None and origin[1] is not None:
            distance = self.distance_from(origin[0], origin[1])
        return {
            'id': self.id, 'slug': self.slug, 'name': self.name,
            'category': self.category, 'category_label': self.category_label,
            'address': self.address, 'area': self.area, 'city': self.city,
            'pincode': self.pincode, 'rating': float(self.rating),
            'price_per_hour': self.price_per_hour,
            'open_time': self.open_time.strftime('%H:%M'),
            'close_time': self.close_time.strftime('%H:%M'),
            'hours_label': self.hours_label, 'open_note': self.open_note,
            'is_active': self.is_active,
            'latitude': float(self.latitude), 'longitude': float(self.longitude),
            'distance_km': round(distance, 1) if distance is not None else None,
            'total': counts.get('total', 0), 'available': counts.get('available', 0),
            'lot_count': counts.get('lot_count', self.lots.count()),
        }


class Lot(models.Model):
    """A parking area inside a place (basement 1, rooftop, north lawn…)."""

    place = models.ForeignKey(Place, on_delete=models.CASCADE, related_name='lots')
    code = models.CharField(max_length=1, choices=[('A', 'A'), ('B', 'B'), ('C', 'C')])
    name = models.CharField(max_length=60)
    description = models.CharField(max_length=120, blank=True)
    walk = models.CharField(max_length=40, default='2 min walk to entrance')
    tagline = models.CharField(max_length=60, blank=True)

    class Meta:
        ordering = ['code']
        unique_together = [('place', 'code')]

    def __str__(self):
        return f'{self.place.name} · Lot {self.code}'

    def as_dict(self):
        slots = list(self.slots.all())
        return {
            'code': self.code, 'name': self.name, 'description': self.description,
            'walk': self.walk, 'tagline': self.tagline,
            'slot_count': len(slots),
        }


class ParkingSlot(models.Model):
    class Vehicle(models.TextChoices):
        CAR = 'car', 'Car'
        BIKE = 'bike', 'Two-wheeler'
        EV = 'ev', 'Electric vehicle'
        ACCESSIBLE = 'accessible', 'Accessible'

    place = models.ForeignKey(Place, on_delete=models.CASCADE, related_name='slots')
    lot = models.ForeignKey(Lot, on_delete=models.CASCADE, related_name='slots')
    code = models.CharField(max_length=6)
    vehicle_type = models.CharField(max_length=12, choices=Vehicle.choices, default=Vehicle.CAR)
    is_disabled = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['code']
        unique_together = [('place', 'code')]
        indexes = [models.Index(fields=['place', 'lot'])]

    def __str__(self):
        return f'{self.place.slug}/{self.code}'

    def status_at(self, start, end):
        if self.is_disabled:
            return 'unavailable'
        now = timezone.now()
        live = self.bookings.filter(status=Booking.Status.CONFIRMED, starts_at__lte=now, ends_at__gt=now).exists()
        if start <= now < end and live:
            return 'occupied'
        if self.bookings.filter(status=Booking.Status.CONFIRMED, starts_at__lt=end, ends_at__gt=start).exists():
            return 'booked'
        return 'available'

    def as_dict(self, start=None, end=None):
        now = timezone.now()
        start = start or now
        end = end or now + timezone.timedelta(hours=2)
        return {
            'id': self.id, 'code': self.code, 'lot': self.lot.code, 'lot_name': self.lot.name,
            'vehicle_type': self.vehicle_type, 'vehicle_label': self.get_vehicle_type_display(),
            'is_disabled': self.is_disabled, 'status': self.status_at(start, end),
        }


class Booking(models.Model):
    class Status(models.TextChoices):
        CONFIRMED = 'confirmed', 'Confirmed'
        CANCELLED = 'cancelled', 'Cancelled'
        COMPLETED = 'completed', 'Completed'

    reference = models.CharField(max_length=12, unique=True, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bookings')
    slot = models.ForeignKey(ParkingSlot, on_delete=models.PROTECT, related_name='bookings')
    vehicle_plate = models.CharField(max_length=20)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    fee = models.PositiveIntegerField(default=0, help_text='Rupees charged for this stay')
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.CONFIRMED)
    created_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-starts_at', '-id']
        indexes = [models.Index(fields=['slot', 'status', 'starts_at', 'ends_at'], name='slot_availability_idx')]

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = 'PW-' + uuid.uuid4().hex[:8].upper()
        super().save(*args, **kwargs)

    @property
    def place(self):
        return self.slot.place

    def effective_status(self):
        if self.status == self.Status.CONFIRMED and self.ends_at <= timezone.now():
            return self.Status.COMPLETED
        return self.status

    def as_dict(self):
        local_start = timezone.localtime(self.starts_at)
        local_end = timezone.localtime(self.ends_at)
        place = self.slot.place
        return {
            'id': self.id, 'reference': self.reference,
            'slot_id': self.slot_id, 'slot_code': self.slot.code, 'lot': self.slot.lot.code,
            'lot_name': self.slot.lot.name,
            'vehicle_type': self.slot.vehicle_type, 'vehicle_plate': self.vehicle_plate,
            'place_slug': place.slug, 'place_name': place.name,
            'place_category': place.category, 'place_category_label': place.category_label,
            'place_area': place.area, 'place_city': place.city, 'place_address': place.address,
            'starts_at': self.starts_at.isoformat(), 'ends_at': self.ends_at.isoformat(),
            'date': local_start.strftime('%Y-%m-%d'), 'start_time': local_start.strftime('%H:%M'),
            'end_time': local_end.strftime('%H:%M'),
            'duration': int((self.ends_at - self.starts_at).total_seconds() / 3600),
            'fee': self.fee,
            'status': self.effective_status(),
            'can_cancel': self.status == self.Status.CONFIRMED and self.starts_at > timezone.now(),
            'user_name': self.user.get_full_name() or self.user.username,
            'user_email': self.user.email,
        }

    def __str__(self):
        return f'{self.reference} · {self.slot.place.name} {self.slot.code}'
