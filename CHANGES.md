# What changed in this version

**Request:** the current site only let people book a parking slot when they were on the local
Wi-Fi / LAN setup. Replace that with **searching a place** — mall, theatre, restaurant, college,
hospital, etc. — and booking parking there.

## 1. Local Wi-Fi requirement removed

- There is no network gate left anywhere: no server-side check, no UI copy telling drivers to join
  a campus hotspot, no "connect to the LAN" modal, no `http://192.168.x.x:8000` instructions.
- `README.md` no longer documents the LAN experiment; it documents a normal web deployment that
  works over the internet, mobile data, or localhost.
- The old "Main campus" pill in the top bar is now a location pill (**Near Kochi**) that sorts
  places by distance from the driver.

## 2. Place search is now the home page

- Free-text search across place name, area, city, address, category and keywords
  (`lulu`, `edappally`, `cinema`, `college`, `hospital`…).
- Category chips: All places / Malls / Theatres / Restaurants / Colleges / Hospitals / Offices /
  Stadiums.
- Arrival date, arrival time and stay length drive every result, with sorting by
  **nearest · most slots free · lowest price · top rated**.
- Each card shows: category, name, area, rating, distance in km, price per hour, opening hours,
  number of lots/slots and `N of M slots free` for the exact window.
- A venue shut at the chosen hour shows **Closed at 10:00 AM** instead of a misleading count.

## 3. New data model

`Place → Lot → ParkingSlot → Booking`

- **Place**: name, category, address, area, city, pincode, latitude/longitude, rating,
  price per hour, opening/closing time, note, keywords, active flag.
- **Lot**: a parking area inside a place (lot A/B/C) with its own name, walk time and tagline.
- **ParkingSlot**: belongs to a place *and* a lot; car / two-wheeler / EV / accessible; can be closed.
- **Booking**: now stores the fee (`price × hours`) and is scoped to a place through its slot.

## 4. Booking page per place

- Place hero with category, rating, distance, address, hours, hourly price, lot count and
  live free-slot count.
- Lot map (the original zone map, now per venue) with lot filter, vehicle filter and slot statuses.
- Reservation panel with arrival date/time, stay length, vehicle number, live fee calculation and
  per-venue opening-hours validation.
- If your chosen arrival time is outside that venue's hours, the form snaps to the nearest window
  that fits.

## 5. Bookings + admin

- **My bookings**: every reservation across every venue, with place, category, area, lot, fee,
  pass, calendar download and cancellation.
- **Admin console**: reservations (search/filter/cancel), **places** (search, add a new place,
  pause/reopen a venue) and **slots** (add slot, close/reopen slot), plus CSV export that now
  includes place, category, area, lot and fee.

## 6. New endpoints

`GET /api/places/`, `GET /api/places/<slug>/`, `POST /api/admin/places/`,
`POST /api/admin/places/<id>/`, `POST /api/admin/slots/` — full table in `README.md`.

## 7. Tests

45 backend tests cover search, sorting, availability, booking rules, per-venue hours, fees,
ownership, cancellation, admin permissions, venue pausing, slot management, CSV export and CSRF.
All pass, plus a browser pass over search → place → sign in → book → bookings → admin.

---

# 2.1 — "the CSS file doesn't work" fix

**Report:** running locally at `127.0.0.1:8000`, the page rendered with no styling.

**Cause:** `runserver` only serves `/static/` when `DEBUG=1`. With `DJANGO_DEBUG=0` the page and
the API answer `200` while **every** CSS/JS/font request returns `404`, so the HTML arrives
unstyled. A stale browser cache from an earlier run makes it look even more broken (old JS still
running, new CSS never loading).

**Fixed:**

- `parking_project/urls.py` — `/static/` is now served by Django whenever `DEBUG=0` too
  (disable with `PARKWISE_SERVE_STATIC=0` for a real nginx/WhiteNoise deployment).
- `STATIC_VERSION = '2.1'` — CSS/JS are requested as `styles.css?v=2.1`, `app.js?v=2.1`, so a
  browser cache from an earlier build can never be reused.
- `manage.py doctor` — new command that checks settings, migrations, seed data and each static
  file over HTTP, and prints the exact fix.
- Front-end resilience: the stay-length selects have options in the HTML itself, the client never
  sends an invalid duration, a failed `/api/overview/` falls back to a browser-computed visit
  window instead of leaving the page half-dead, and submitting the search box can no longer fall
  back to a native `/?q=` page reload (which is why the empty search lost all state).
