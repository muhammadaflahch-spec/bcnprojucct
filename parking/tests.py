import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.utils import timezone

from .models import Booking, Lot, ParkingSlot, Place


class BaseParkingTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.place = Place.objects.create(
            slug='lulu-mall', name='Lulu Mall', category='mall', address='Bypass Road, Edappally',
            area='Edappally', city='Kochi', latitude=10.027, longitude=76.3087, rating='4.5',
            price_per_hour=25, open_time='09:00', close_time='22:00', keywords='mall shopping cinema')
        self.college = Place.objects.create(
            slug='cusat', name='CUSAT', category='college', address='Kalamassery', area='Kalamassery',
            city='Kochi', latitude=10.0466, longitude=76.3218, rating='4.3', price_per_hour=10,
            open_time='07:00', close_time='20:00', keywords='college campus university')
        self.lot_a = Lot.objects.create(place=self.place, code='A', name='Basement 1', walk='2 min walk')
        self.lot_c = Lot.objects.create(place=self.place, code='C', name='Rooftop', walk='6 min walk')
        self.slot = ParkingSlot.objects.create(place=self.place, lot=self.lot_a, code='A01')
        self.slot_two = ParkingSlot.objects.create(place=self.place, lot=self.lot_a, code='A02')
        self.bike = ParkingSlot.objects.create(place=self.place, lot=self.lot_c, code='C01', vehicle_type='bike')
        college_lot = Lot.objects.create(place=self.college, code='A', name='Main gate', walk='3 min walk')
        self.college_slot = ParkingSlot.objects.create(place=self.college, lot=college_lot, code='A01')
        self.user = User.objects.create_user(username='driver@example.com', email='driver@example.com',
                                             password='StrongPass123!', first_name='Dia')
        self.admin = User.objects.create_user(username='admin@example.com', email='admin@example.com',
                                              password='StrongPass123!', is_staff=True)
        tomorrow = (timezone.localtime() + timedelta(days=1)).strftime('%Y-%m-%d')
        self.window = {'date': tomorrow, 'start_time': '10:00', 'duration': 2}


class PublicPagesTests(BaseParkingTest):
    def test_discover_page_renders(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Parkwise')

    def test_place_page_renders(self):
        response = self.client.get('/place/lulu-mall/')
        self.assertEqual(response.status_code, 200)

    def test_unknown_place_returns_404(self):
        self.assertEqual(self.client.get('/place/not-a-place/').status_code, 404)

    def test_bookings_and_admin_shells_render(self):
        self.assertEqual(self.client.get('/bookings/').status_code, 200)
        self.assertEqual(self.client.get('/admin-panel/').status_code, 200)


class SearchApiTests(BaseParkingTest):
    def search(self, **params):
        response = self.client.get('/api/places/', params)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_all_places_listed(self):
        data = self.search()
        self.assertEqual(data['result_count'], 2)
        self.assertEqual({p['slug'] for p in data['places']}, {'lulu-mall', 'cusat'})

    def test_search_by_name_area_and_keyword(self):
        self.assertEqual([p['slug'] for p in self.search(q='lulu')['places']], ['lulu-mall'])
        self.assertEqual([p['slug'] for p in self.search(q='kalamassery')['places']], ['cusat'])
        self.assertEqual([p['slug'] for p in self.search(q='cinema')['places']], ['lulu-mall'])

    def test_search_is_case_insensitive_and_multi_word(self):
        self.assertEqual([p['slug'] for p in self.search(q='LULU MALL')['places']], ['lulu-mall'])

    def test_category_filter(self):
        data = self.search(category='college')
        self.assertEqual([p['slug'] for p in data['places']], ['cusat'])
        self.assertEqual(data['places'][0]['category_label'], 'College')

    def test_no_results(self):
        data = self.search(q='airport terminal')
        self.assertEqual(data['result_count'], 0)

    def test_inactive_place_is_hidden(self):
        self.place.is_active = False
        self.place.save()
        self.assertNotIn('lulu-mall', [p['slug'] for p in self.search()['places']])

    def test_availability_counts(self):
        data = self.search()
        lulu = next(p for p in data['places'] if p['slug'] == 'lulu-mall')
        self.assertEqual(lulu['total'], 3)
        self.assertEqual(lulu['available'], 3)

    def test_sorting_by_price(self):
        data = self.search(sort='price')
        self.assertEqual([p['slug'] for p in data['places']], ['cusat', 'lulu-mall'])

    def test_sorting_by_distance(self):
        data = self.search(sort='nearby', lat='10.05', lng='76.32')
        self.assertEqual(data['places'][0]['slug'], 'cusat')
        self.assertIsNotNone(data['places'][0]['distance_km'])

    def test_invalid_window_rejected(self):
        response = self.client.get('/api/places/', {'duration': 7})
        self.assertEqual(response.status_code, 400)

    def test_place_detail(self):
        response = self.client.get('/api/places/lulu-mall/', self.window)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['place']['name'], 'Lulu Mall')
        self.assertEqual(len(data['slots']), 3)
        self.assertEqual(data['available'], 3)
        self.assertEqual(len(data['place']['lots']), 2)

    def test_place_detail_unknown_slug(self):
        self.assertEqual(self.client.get('/api/places/nope/').status_code, 404)


class BookingTests(BaseParkingTest):
    def book(self, **overrides):
        payload = {'slot_id': self.slot.id, 'vehicle_plate': 'KL 07 AB 1234', **self.window, **overrides}
        return self.client.post('/api/bookings/', json.dumps(payload), content_type='application/json')

    def test_booking_requires_sign_in(self):
        self.assertEqual(self.book().status_code, 401)

    def test_booking_succeeds_and_computes_fee(self):
        self.client.force_login(self.user)
        response = self.book()
        self.assertEqual(response.status_code, 201)
        booking = response.json()['booking']
        self.assertEqual(booking['place_name'], 'Lulu Mall')
        self.assertEqual(booking['fee'], 50)
        self.assertEqual(booking['duration'], 2)
        self.assertTrue(booking['reference'].startswith('PW-'))

    def test_availability_drops_after_booking(self):
        self.client.force_login(self.user)
        self.book()
        data = self.client.get('/api/places/lulu-mall/', self.window).json()
        self.assertEqual(data['available'], 2)
        slot = next(s for s in data['slots'] if s['id'] == self.slot.id)
        self.assertEqual(slot['status'], 'booked')

    def test_double_booking_blocked(self):
        self.client.force_login(self.user)
        self.book()
        other = User.objects.create_user(username='other@example.com', email='other@example.com',
                                         password='StrongPass123!')
        self.client.force_login(other)
        self.assertEqual(self.book().status_code, 409)

    def test_overlapping_stay_blocked_partial(self):
        self.client.force_login(self.user)
        self.book()
        other = User.objects.create_user(username='other@example.com', password='StrongPass123!')
        self.client.force_login(other)
        response = self.book(slot_id=self.slot.id, start_time='11:00', duration=3)
        self.assertEqual(response.status_code, 409)

    def test_adjacent_stay_allowed(self):
        self.client.force_login(self.user)
        self.book()
        other = User.objects.create_user(username='other@example.com', password='StrongPass123!')
        self.client.force_login(other)
        self.assertEqual(self.book(slot_id=self.slot.id, start_time='12:00', duration=1).status_code, 201)

    def test_same_driver_cannot_double_book_place(self):
        self.client.force_login(self.user)
        self.book()
        self.assertEqual(self.book(slot_id=self.slot_two.id).status_code, 409)

    def test_booking_outside_place_hours_rejected(self):
        self.client.force_login(self.user)
        response = self.book(slot_id=self.college_slot.id, start_time='19:00', duration=4)
        self.assertEqual(response.status_code, 400)
        self.assertIn('CUSAT', response.json()['error'])

    def test_booking_in_past_rejected(self):
        self.client.force_login(self.user)
        yesterday = (timezone.localtime() - timedelta(days=1)).strftime('%Y-%m-%d')
        self.assertEqual(self.book(date=yesterday).status_code, 400)

    def test_invalid_plate_rejected(self):
        self.client.force_login(self.user)
        self.assertEqual(self.book(vehicle_plate='X').status_code, 400)

    def test_missing_slot_rejected(self):
        self.client.force_login(self.user)
        self.assertEqual(self.book(slot_id=None).status_code, 400)

    def test_closed_slot_rejected(self):
        self.client.force_login(self.user)
        self.slot.is_disabled = True
        self.slot.save()
        self.assertEqual(self.book().status_code, 409)

    def test_cancel_releases_slot(self):
        self.client.force_login(self.user)
        booking_id = self.book().json()['booking']['id']
        response = self.client.post(f'/api/bookings/{booking_id}/cancel/')
        self.assertEqual(response.status_code, 200)
        data = self.client.get('/api/places/lulu-mall/', self.window).json()
        self.assertEqual(data['available'], 3)

    def test_other_driver_cannot_cancel(self):
        self.client.force_login(self.user)
        booking_id = self.book().json()['booking']['id']
        other = User.objects.create_user(username='other@example.com', password='StrongPass123!')
        self.client.force_login(other)
        self.assertEqual(self.client.post(f'/api/bookings/{booking_id}/cancel/').status_code, 404)

    def test_calendar_download_mentions_place(self):
        self.client.force_login(self.user)
        booking_id = self.book().json()['booking']['id']
        response = self.client.get(f'/api/bookings/{booking_id}/calendar/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/calendar', response['Content-Type'])
        self.assertIn('Lulu Mall', response.content.decode())

    def test_csrf_is_enforced(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        response = strict.post('/api/bookings/', json.dumps({'slot_id': self.slot.id, 'vehicle_plate': 'KL 07 AB 1234',
                                                             **self.window}), content_type='application/json')
        self.assertEqual(response.status_code, 403)


class AuthTests(BaseParkingTest):
    def test_register_and_overview(self):
        response = self.client.post('/api/auth/register/', json.dumps(
            {'name': 'New Driver', 'email': 'new@example.com', 'password': 'StrongPass123!'}),
            content_type='application/json')
        self.assertEqual(response.status_code, 201)
        data = self.client.get('/api/overview/').json()
        self.assertEqual(data['user']['email'], 'new@example.com')
        self.assertEqual(data['categories'][0]['value'], 'mall')
        self.assertIn('totals', data)

    def test_duplicate_email_rejected(self):
        response = self.client.post('/api/auth/register/', json.dumps(
            {'name': 'Dia', 'email': 'driver@example.com', 'password': 'StrongPass123!'}),
            content_type='application/json')
        self.assertEqual(response.status_code, 409)

    def test_bad_password_rejected(self):
        response = self.client.post('/api/auth/login/', json.dumps(
            {'email': 'driver@example.com', 'password': 'nope'}), content_type='application/json')
        self.assertEqual(response.status_code, 401)


class AdminTests(BaseParkingTest):
    def test_admin_api_requires_staff(self):
        self.assertEqual(self.client.get('/api/admin/overview/').status_code, 401)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get('/api/admin/overview/').status_code, 403)

    def test_admin_overview_lists_places(self):
        self.client.force_login(self.admin)
        data = self.client.get('/api/admin/overview/').json()
        self.assertEqual(len(data['places']), 2)
        self.assertEqual(data['total_slots'], 4)

    def test_add_place_creates_lots_and_slots(self):
        self.client.force_login(self.admin)
        response = self.client.post('/api/admin/places/', json.dumps(
            {'name': 'Marine Drive Mall', 'category': 'mall', 'area': 'Marine Drive', 'city': 'Kochi',
             'price_per_hour': 30, 'open_time': '09:00', 'close_time': '22:00'}), content_type='application/json')
        self.assertEqual(response.status_code, 201)
        place = Place.objects.get(slug='marine-drive-mall')
        self.assertEqual(place.lots.count(), 2)
        self.assertEqual(place.slots.count(), 16)
        self.assertTrue(self.client.get('/api/places/', {'q': 'marine'}).json()['result_count'] == 1)

    def test_add_place_validation(self):
        self.client.force_login(self.admin)
        response = self.client.post('/api/admin/places/', json.dumps(
            {'name': 'X', 'category': 'mall', 'area': 'A'}), content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_pause_place_removes_it_from_search(self):
        self.client.force_login(self.admin)
        response = self.client.post(f'/api/admin/places/{self.place.id}/', json.dumps({'is_active': False}),
                                    content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get('/api/places/', {'q': 'lulu'}).json()['result_count'], 0)

    def test_add_slot(self):
        self.client.force_login(self.admin)
        response = self.client.post('/api/admin/slots/', json.dumps(
            {'place_id': self.place.id, 'code': 'A09', 'vehicle_type': 'ev'}), content_type='application/json')
        self.assertEqual(response.status_code, 201)
        self.assertTrue(ParkingSlot.objects.filter(place=self.place, code='A09', vehicle_type='ev').exists())

    def test_add_slot_rejects_bad_code(self):
        self.client.force_login(self.admin)
        response = self.client.post('/api/admin/slots/', json.dumps(
            {'place_id': self.place.id, 'code': 'Z99'}), content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_close_and_reopen_slot(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(f'/api/admin/slots/{self.slot.id}/',
                                          json.dumps({'is_disabled': True}),
                                          content_type='application/json').status_code, 200)
        self.slot.refresh_from_db()
        self.assertTrue(self.slot.is_disabled)

    def test_export_csv_includes_place_column(self):
        self.client.force_login(self.user)
        self.client.post('/api/bookings/', json.dumps({'slot_id': self.slot.id, 'vehicle_plate': 'KL 07 AB 1234',
                                                       **self.window}), content_type='application/json')
        self.client.force_login(self.admin)
        response = self.client.get('/api/admin/export/')
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn('Lulu Mall', body)
        self.assertIn('Place', body.splitlines()[0])

    def test_admin_can_cancel_booking(self):
        self.client.force_login(self.user)
        booking_id = self.client.post('/api/bookings/', json.dumps(
            {'slot_id': self.slot.id, 'vehicle_plate': 'KL 07 AB 1234', **self.window}),
            content_type='application/json').json()['booking']['id']
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(f'/api/admin/bookings/{booking_id}/cancel/').status_code, 200)
        self.assertEqual(Booking.objects.get(pk=booking_id).status, 'cancelled')
