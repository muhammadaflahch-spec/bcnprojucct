# Parkwise — Smart Parking Slot Booking System

Parkwise is a working, responsive parking reservation app built from the **BCN Phase 1 project
(proposal + abstract)**. The first version booked slots at a single campus and only worked for
drivers connected to the same local Wi-Fi as the server laptop.

**This version drops that local-network setup.** Drivers now search for a *place* — a mall,
theatre, restaurant, college, hospital, office park or stadium — see how many parking slots are
free there for their arrival time, and book a specific slot before they drive.

**Stack:** HTML5, CSS3, vanilla JavaScript, Python, Django, SQLite. All fonts and icons are
served locally; the running app needs no CDN, external API, map key or internet connection.

---

## What changed from the campus-only version

| Before | Now |
|---|---|
| One campus, three zones, 36 slots | 15 sample places across Kochi, 45 lots, 405 slots |
| Map was the home page | Home page is a **place search**: free-text search + category chips + distance/price/rating sorting |
| Booking only made sense on the campus LAN | Booking works from any network — mobile data, home Wi-Fi, hosted server |
| Fixed 6 AM–10 PM campus hours | Every place has its own opening hours, hourly price and lots |
| Zones A/B/C on one campus | Each place has its own lots A/B/C, each with its own walk time and vehicle mix |
| "Campus admin" console | Venue admin console: manage places, pause bookings, add slots, cancel, export |
| Wi-Fi/LAN instructions baked into the UI copy | Removed. No network gate anywhere in the app or the interface |

The design language, typography, map interaction, booking rules and admin console behaviour are
carried over from the original build.

---

## Quick start

Requires **Python 3.11 or newer**. Run these inside this folder.

### Windows

```powershell
py -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo
python manage.py runserver 0.0.0.0:8000
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo
python manage.py runserver 0.0.0.0:8000
```

Open **http://127.0.0.1:8000**. `seed_demo` is safe to rerun: places are matched by slug, lots and
slots are only created when missing, and sample reservations are only added to an empty bookings
table.

### If the page loads without any styling (no CSS)

That is almost always one of these two things:

1. **`DJANGO_DEBUG=0` is set.** `runserver` only auto-serves static files when `DEBUG=1`, so every
   `/static/...` request 404s and the page renders unstyled. For local work leave `DJANGO_DEBUG`
   unset. This build now also serves `/static/` itself when `DEBUG=0` (unless you set
   `PARKWISE_SERVE_STATIC=0`), so a local run stays styled either way.
2. **A stale browser cache** from an earlier run. CSS/JS URLs carry `?v=<STATIC_VERSION>`
   (currently `2.1`), so a normal reload picks up new files; do one hard refresh
   (Ctrl/Cmd + Shift + R) if you edited the CSS yourself.

Run the built-in check — it tests settings, migrations, seed data **and each static file over HTTP**:

```bash
python manage.py doctor                    # add --url http://127.0.0.1:8000 if you use another port
```

Expected tail:

```text
4. Serving over HTTP
   ok   200 http://127.0.0.1:8000/static/parking/css/styles.css
   ok   200 http://127.0.0.1:8000/static/parking/js/app.js
   ...
All checks passed — Parkwise looks healthy.
```

Other quick checks:

```bash
python manage.py migrate          # tables must exist, or API calls return 500
python manage.py seed_demo        # 15 places / 405 slots
python manage.py runserver --insecure   # only needed if you must run with DEBUG=0
```

### Try the whole flow in two minutes

1. On **Find parking**, type `theatre` — or tap a category chip such as **Restaurants**.
2. Set an arrival date, time and stay length. Cards show `N of M slots free` for exactly that window.
   A venue that is shut at that hour shows **Closed at 10:00 AM** instead of a fake count.
3. Open a place, pick a green slot on its lot map, then **Sign in to reserve → Try driver demo**.
4. Confirm the reservation. You get a pass, an `.ics` download and a row in **My bookings**.
5. Open **Admin console → Explore admin demo** to pause a place, add a slot, cancel a booking or
   export CSV.

### Demo accounts

| Role | Email / username | Password |
|---|---|---|
| Driver | `driver@parkwise.demo` | `ParkwiseDemo123!` |
| Administrator | `admin@parkwise.demo` | `ParkwiseAdmin123!` |

The one-click demo buttons only work when `PARKWISE_DEMO_MODE=1` (the default in DEBUG). These are
**shared demonstration accounts** — never enter real sensitive data in a hosted demo.

For Django's built-in admin at `/django-admin/`, create your own superuser with
`python manage.py createsuperuser`.

---

## How the app is put together

```
Place         a venue: mall, theatre, restaurant, college, hospital, office park, stadium
  └─ Lot      a parking area inside it (lot A / B / C, with a name and walk time)
       └─ ParkingSlot   one bookable space (car, two-wheeler, EV, accessible)
            └─ Booking  a driver's reservation for a time window, with a stored fee
```

Everything is relational in SQLite, so one driver account works across every venue and the admin
console sees a single pool of reservations.

### API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/overview/` | Session user, their bookings, categories, durations, defaults |
| GET | `/api/places/` | **Search**: `?q=&category=&sort=nearby\|availability\|price\|rating&date=&start_time=&duration=&lat=&lng=` |
| GET | `/api/places/<slug>/` | One place, its lots and slot statuses for the window |
| POST | `/api/bookings/` | Create a reservation (`slot_id`, date, arrival time, duration, vehicle) |
| POST | `/api/bookings/<id>/cancel/` | Cancel before arrival |
| GET | `/api/bookings/<id>/calendar/` | `.ics` calendar file |
| POST | `/api/admin/places/` | Add a place (creates 2 lots + 16 slots ready to book) |
| POST | `/api/admin/places/<id>/` | Pause / reopen a place |
| POST | `/api/admin/slots/` | Add a slot (`code` like `A09`) |
| POST | `/api/admin/slots/<id>/` | Close / reopen a slot |
| GET | `/api/admin/export/` | CSV of every reservation, including the place |

Search matches place name, area, city, address, category and a `keywords` field, token by token,
case-insensitively — so `lulu mall`, `edappally`, `cinema` and `kollam` style queries all behave.

### Place search without a map API

Venues carry latitude/longitude. The browser asks for an optional geolocation fix (the
**Near Kochi** pill in the top bar) and the server sorts by haversine distance from those
coordinates. If permission is denied, it falls back to Marine Drive, Kochi — no Google Maps key,
no network dependency. Swap `DEFAULT_ORIGIN` in `parking/views.py` to change the fallback centre.

---

## Product rules enforced server-side

- Reservations up to **30 days ahead**, in **1, 2, 3, 4 or 8-hour** stays.
- The stay must fit **inside that venue's opening hours**; the search screen also pre-fits the
  arrival time when you open a venue that is closed at your chosen hour.
- One active reservation per driver **per venue** for an overlapping window.
- No double-booking of a slot, including two drivers clicking at once — the SQLite write lock is
  taken before the availability check.
- Fee = `price_per_hour × hours`, stored on the booking so later price changes don't rewrite history.
- Closed slots and paused venues disappear from new bookings immediately; existing reservations are
  kept.

## Files worth knowing

```
parking/models.py                     Place, Lot, ParkingSlot, Booking
parking/views.py                      Search API, booking rules, admin API
parking/management/commands/seed_demo.py   15 Kochi venues, 405 slots, demo accounts
templates/parking/index.html          App shell: search, place, bookings, admin, dialogs
static/parking/js/app.js              Search, map, booking, admin interactions
static/parking/css/styles.css         Original design system + place-search layer at the end
parking/tests.py                      45 backend tests
```

## Tests

```bash
python manage.py test parking --verbosity 2
python manage.py check
```

Coverage includes: search by name/area/keyword/category, sorting, availability counts, place
details, sign-in/registration, booking persistence, fee calculation, overlap and adjacency,
per-venue opening hours, past-time rejection, ownership checks, cancellation, calendar downloads,
admin authorization, adding places/slots, pausing venues, CSV export and CSRF enforcement.

## Prototype assumptions

- Venues, prices, ratings, opening hours and lots are **sample data for Kochi**, not the venues'
  published details. Edit them in `seed_demo.py`, in `/django-admin/` or via the admin console.
- Free-text search is a database `icontains` filter, not a geocoder.
- No physical sensors, cameras, number-plate recognition, payments or emails.
- "Available" means *no overlapping reservation and the slot is not closed* — a reservation system,
  not an occupancy sensor.

## Before any real-world use

- Disable demo mode and retire the shared accounts:

  ```bash
  python manage.py retire_demo
  ```

- Set `PARKWISE_DEMO_MODE=0`, `DJANGO_DEBUG=0`, a strong `DJANGO_SECRET_KEY` and an explicit
  `DJANGO_ALLOWED_HOSTS`.
- Deploy behind HTTPS with a production WSGI server, hosted static files, backups and monitoring —
  Django's development server is not a production server. `PREVIEW_MODE=1` is only for HTTPS
  preview proxies such as this sandbox; leave it off for normal use.
- Move to PostgreSQL and real rate limiting before running more than one process.
- Agree real venue data, tariffs, opening hours and cancellation policies with each venue.

## Source material and credits

Based on the user-provided:

- [Smart Parking Slot Booking System — BCN Project Phase 1 presentation](https://docs.google.com/presentation/d/1m9lJZNv-3tXPUV-HwCyXIpRjUdzLbOxT/edit)
- `Smart_Parking_Slot_Booking_System_Abstract.pdf`

Proposal team: **Aflah, Ajo, Hilda, Shahma, Ameeshah** — Department of Computer Science & Engineering,
B.Tech. Parkwise branding and interface were created for this implementation. DM Sans and Plus
Jakarta Sans are distributed under the SIL Open Font License; licence files sit beside the fonts.
