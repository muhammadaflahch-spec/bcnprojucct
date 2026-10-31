/* Parkwise — place-search parking prototype. All bookings live in Django + SQLite. */
(() => {
  'use strict';

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const icon = (name, extra = '') => `<svg class="icon ${extra}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

  const VEHICLE_ICONS = {car:'car', bike:'bike', ev:'bolt', accessible:'access'};
  const VEHICLE_LABELS = {car:'Car parking', bike:'Two-wheeler parking', ev:'Electric vehicle parking', accessible:'Accessible parking'};
  const STATUS_LABELS = {available:'Available', booked:'Reserved for this time', occupied:'Occupied now', unavailable:'Temporarily closed'};
  const CATEGORY_META = {
    mall:{icon:'store', label:'Mall'}, theatre:{icon:'film', label:'Theatre'},
    restaurant:{icon:'food', label:'Restaurant'}, college:{icon:'graduation', label:'College'},
    hospital:{icon:'medical', label:'Hospital'}, office:{icon:'briefcase', label:'Office park'},
    stadium:{icon:'stadium', label:'Stadium'},
  };

  const state = {
    page: window.PARKWISE_PAGE || 'dashboard',
    slug: window.PARKWISE_SLUG || '',
    user: null,
    q: '', category: '', sort: 'nearby',
    window: {date:'', time:'', duration:2},
    origin: null,
    places: [], placesBusy: false, categories: [],
    place: null, slots: [], selectedId: null,
    lot: 'all', vehicle: 'all',
    bookings: [], upcoming: 0,
    bookingFilter: 'upcoming',
    adminData: null, adminTab: 'reservations', adminSearch: '', adminStatus: 'all',
    modalOpen: false, lastFocus: null, authContext: null,
    bookingBusy: false, refreshing: false,
  };
  let searchTimer, refreshTimer, toastIndex = 0, placesRequestId = 0, placeRequestId = 0;

  /* ------------------------------------------------------------------ helpers */

  function cookie(name) {
    return document.cookie.split('; ').find(row => row.startsWith(name + '='))?.split('=').slice(1).join('=') || '';
  }
  async function api(url, options = {}) {
    const headers = {'Accept':'application/json', ...options.headers};
    if (options.body !== undefined) headers['Content-Type'] = 'application/json';
    if (!['GET', 'HEAD'].includes(options.method || 'GET')) headers['X-CSRFToken'] = decodeURIComponent(cookie('csrftoken'));
    let response;
    try {
      response = await fetch(url, {credentials:'same-origin', ...options, headers});
    } catch (_) {
      throw new Error('We couldn’t reach the Parkwise server. Check your connection and try again.');
    }
    let data;
    try { data = await response.json(); }
    catch (_) { throw new Error('The server returned an unexpected response. Please refresh and try again.'); }
    if (!response.ok) {
      const error = new Error(data.error || 'Something went wrong. Please try again.');
      error.status = response.status;
      throw error;
    }
    return data;
  }
  const post = (url, data = {}) => api(url, {method:'POST', body:JSON.stringify(data)});
  function prettyDate(value, options = {}) {
    const date = String(value).length === 10 ? new Date(value + 'T12:00:00') : new Date(value);
    return date.toLocaleDateString('en-IN', {day:'numeric', month:'short', ...options});
  }
  function prettyTime(value) {
    const [hours, minutes] = String(value).split(':').map(Number);
    return `${hours % 12 || 12}:${String(minutes).padStart(2,'0')} ${hours >= 12 ? 'PM' : 'AM'}`;
  }
  function dateString(date) {
    return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
  }
  function rupee(amount) { return '₹' + Number(amount || 0).toLocaleString('en-IN'); }
  function money(amount) { return '₹' + Number(amount); }

  function toast(message, error = false) {
    const node = document.createElement('div');
    node.className = 'toast' + (error ? ' error' : '');
    node.innerHTML = `${icon(error ? 'info' : 'check')}<span>${escapeHTML(message)}</span><button class="toast-close" aria-label="Dismiss notification">${icon('close')}</button>`;
    $('#toast-region').append(node);
    $('button', node).addEventListener('click', () => node.remove());
    setTimeout(() => node.remove(), error ? 8000 : 5000);
  }

  /* --------------------------------------------------------------- session/load */

  async function loadSession() {
    const params = new URLSearchParams(windowPayload());
    const data = await api('/api/overview/?' + params);
    state.user = data.user;
    state.bookings = data.bookings || [];
    state.upcoming = data.upcoming_count || 0;
    if (!state.window.date) {
      state.window.date = data.window.starts_at.slice(0, 10);
      state.window.time = data.window.starts_at.slice(11, 16);
      state.window.duration = data.window.duration || 2;
    }
    renderProfile();
    $('#booking-count').textContent = state.upcoming;
    if ($('#search-date')) {
      const minDate = new Intl.DateTimeFormat('en-CA', {timeZone:data.timezone, year:'numeric', month:'2-digit', day:'2-digit'}).format(new Date(data.server_time));
      const maxDate = new Date(minDate + 'T12:00:00');
      maxDate.setDate(maxDate.getDate() + 30);
      $('#search-date').min = minDate; $('#search-date').max = dateString(maxDate);
      $('#search-date').value = state.window.date;
      $('#search-time').value = state.window.time;
      $('#search-duration').innerHTML = data.durations.map(d => `<option value="${d}" ${d === state.window.duration ? 'selected' : ''}>${d} hour${d > 1 ? 's' : ''}</option>`).join('');
      state.categories = data.categories;
      renderCategoryChips();
    }
    return data;
  }

  function windowPayload(extra = {}) {
    // Never send empty strings: the API expects a real date/time or nothing at all.
    const source = {...state.window, ...extra};
    const payload = {};
    Object.entries(source).forEach(([key, value]) => {
      if (value !== '' && value !== null && value !== undefined) payload[key] = value;
    });
    // Guard rails: a stale or empty <select> must never poison the whole page.
    const duration = Number(payload.duration);
    payload.duration = [1, 2, 3, 4, 8].includes(duration) ? duration : 2;
    if (payload.date && !/^\d{4}-\d{2}-\d{2}$/.test(payload.date)) delete payload.date;
    if (payload.time && !/^\d{2}:\d{2}$/.test(payload.time)) delete payload.time;
    return payload;
  }

  // If the first API call fails (server error, empty database, stale cache) the
  // search screen must still be usable, so derive the visit window in the browser.
  function applyFallbackWindow() {
    if (state.window.date && state.window.time) return;
    const soon = new Date(Date.now() + 60 * 60 * 1000);
    soon.setMinutes(0, 0, 0);
    state.window = {date: dateString(soon), time: `${String(soon.getHours()).padStart(2, '0')}:00`, duration: 2};
    if ($('#search-date')) {
      $('#search-date').value = state.window.date;
      $('#search-time').value = state.window.time;
      $('#search-duration').value = String(state.window.duration);
    }
    if ($('#booking-date')) {
      $('#booking-date').value = state.window.date;
      $('#booking-time').value = state.window.time;
      $('#booking-duration').value = String(state.window.duration);
    }
  }

  /* --------------------------------------------------------------- discover page */

  function renderCategoryChips() {
    const root = $('#category-chips');
    if (!root || !state.categories.length) return;
    const all = [{value:'', label:'All places', icon:'grid'}, ...state.categories.map(c => ({value:c.value, label:c.label, icon:(CATEGORY_META[c.value]||{}).icon || 'pin'}))];
    root.innerHTML = all.map(item => `<button type="button" class="chip ${state.category === item.value ? 'active' : ''}" data-category="${item.value}" aria-pressed="${state.category === item.value}">${icon(item.icon)}${escapeHTML(item.label)}</button>`).join('');
  }

  async function loadPlaces(manual = false) {
    const requestId = ++placesRequestId;
    state.placesBusy = true;
    $('.refresh-button')?.classList.add('loading');
    if (!state.places.length) $('#place-grid').innerHTML = '<div class="place-skeleton"></div><div class="place-skeleton"></div><div class="place-skeleton"></div>';
    const params = new URLSearchParams({...windowPayload(), q:state.q, category:state.category, sort:state.sort});
    if (state.origin) { params.set('lat', state.origin.lat); params.set('lng', state.origin.lng); }
    try {
      const data = await api('/api/places/?' + params);
      if (requestId !== placesRequestId) return;
      state.places = data.places;
      renderPlaces(data);
      if (manual) toast(`${data.result_count} place${data.result_count === 1 ? '' : 's'} updated for your arrival time.`);
      $('#map-updated').textContent = 'Updated just now';
    } catch (error) {
      if (requestId !== placesRequestId) return;
      if (manual || !state.places.length) {
        $('#place-grid').innerHTML = `<div class="empty-state"><span class="empty-state-icon">${icon('info')}</span><h2>We couldn’t load places.</h2><p>${escapeHTML(error.message)}</p><button class="button button-primary" data-action="refresh-places">Try again</button></div>`;
        $('#map-updated').textContent = 'Not connected';
      }
      if (manual) toast(error.message, true);
    } finally {
      if (requestId === placesRequestId) {
        state.placesBusy = false;
        $('.refresh-button')?.classList.remove('loading');
      }
    }
  }

  function renderPlaces(data) {
    const grid = $('#place-grid');
    const title = $('#results-title');
    const sub = $('#results-sub');
    const meta = $('#results-meta');
    const label = state.q ? `Results for “${state.q}”` : state.category ? `${(CATEGORY_META[state.category]||{}).label || 'Place'} parking near you` : 'Places near you';
    title.textContent = label;
    if (!data.places.length) {
      const tips = ['Malls', 'Theatres', 'Restaurants', 'Colleges', 'Hospitals'];
      sub.textContent = 'No places matched that search.';
      meta.innerHTML = '<span class="muted-text">Try a different word or place type</span>';
      grid.innerHTML = `<div class="empty-state"><span class="empty-state-icon">${icon('search')}</span><h2>Nothing here. Yet.</h2><p>We couldn’t match that search. Try a place name like “Lulu Mall”, or browse by type.</p><div class="chip-row center">${tips.map(t => `<button class="chip" data-quick="${t}">${icon((CATEGORY_META[t.toLowerCase()]||{}).icon || 'pin')}${t}</button>`).join('')}</div></div>`;
      return;
    }
    const totalFree = data.places.reduce((sum, p) => sum + p.available, 0);
    const totalSlots = data.places.reduce((sum, p) => sum + p.total, 0);
    sub.textContent = `${data.result_count} place${data.result_count === 1 ? '' : 's'} · ${totalFree} of ${totalSlots} slots free for ${data.window.duration}-hour stays from ${prettyTime(state.window.time)}`;
    meta.innerHTML = `<span class="status-dot"></span><span id="map-updated">Updated just now</span>`;
    grid.innerHTML = data.places.map(placeCard).join('');
    grid.classList.add('loaded');
  }

  function windowFitsPlace(place) {
    if (!state.window.time) return true;
    const [openH, openM] = place.open_time.split(':').map(Number);
    const [closeH, closeM] = place.close_time.split(':').map(Number);
    const [hour, minute] = state.window.time.split(':').map(Number);
    const start = hour * 60 + minute;
    return start >= openH * 60 + openM && start + state.window.duration * 60 <= closeH * 60 + closeM;
  }

  function placeCard(place) {
    const meta = CATEGORY_META[place.category] || {icon:'pin', label:place.category};
    const pct = place.total ? Math.round((place.available / place.total) * 100) : 0;
    const full = place.available === 0;
    const tight = !full && pct <= 25;
    const closed = !windowFitsPlace(place);
    const note = closed ? `Closed at ${prettyTime(state.window.time)}` : full ? 'Full for this time' : `${place.available} free`;
    const tone = closed || full ? 'is-full' : tight ? 'is-tight' : '';
    return `<article class="place-card${closed ? ' is-closed' : ''}" data-place="${escapeHTML(place.slug)}" tabindex="0" role="button" aria-label="${escapeHTML(place.name)}, ${escapeHTML(meta.label)} in ${escapeHTML(place.area)}. ${closed ? 'Closed at your arrival time, opens ' + escapeHTML(place.hours_label) : place.available + ' of ' + place.total + ' slots free'}. Open parking">
      <div class="place-cover tone-${place.category}">
        <span class="cover-icon">${icon(meta.icon)}</span>
        <span class="cover-cat">${escapeHTML(meta.label)}</span>
        <span class="rating-chip">${icon('star')}${place.rating.toFixed(1)}</span>
        ${place.distance_km !== null ? `<span class="distance-chip">${icon('navigate')}${place.distance_km} km</span>` : ''}
      </div>
      <div class="place-body">
        <div class="place-title-row"><h3>${escapeHTML(place.name)}</h3><span class="price-tag">${money(place.price_per_hour)}<small>/hr</small></span></div>
        <p class="place-loc">${icon('pin')}${escapeHTML(place.area)} · ${escapeHTML(place.city)}</p>
        <p class="place-hours">${icon('clock')}${escapeHTML(place.hours_label)}<span class="dot-sep"></span>${place.lot_count} lot${place.lot_count === 1 ? '' : 's'} · ${place.total} slots</p>
        <div class="avail-row">
          <div class="avail-bar"><i class="${tone}" style="width:${closed || full ? 100 : pct}%"></i></div>
          <span class="avail-text ${tone}">${note}</span>
        </div>
        <div class="place-cta-row"><span class="place-cta">${closed ? 'See opening times' : full ? 'See other times' : 'Book a slot'}${icon('arrow')}</span><span class="place-open">${icon(closed ? 'clock' : 'shield')}${closed ? 'Opens ' + escapeHTML(place.open_time.slice(0,5)) : full ? 'Try another time' : 'Reservation-based'}</span></div>
      </div>
    </article>`;
  }

  /* ------------------------------------------------------------------ place page */

  async function loadPlace(slug, options = {}) {
    const requestId = ++placeRequestId;
    if (!slug) return;
    try {
      const params = new URLSearchParams(windowPayload());
      if (state.origin) { params.set('lat', state.origin.lat); params.set('lng', state.origin.lng); }
      const data = await api(`/api/places/${encodeURIComponent(slug)}/?` + params);
      if (requestId !== placeRequestId) return;
      // The arrival time chosen on the search screen may fall outside this venue's
      // opening hours — snap to the nearest window that fits, then load again.
      if (!data.fits && options.autoFit !== false && data.suggested) {
        state.window = {date:data.suggested.date, time:data.suggested.start_time, duration:data.suggested.duration};
        return loadPlace(slug, {...options, autoFit:false, keepSelection:false});
      }
      const previous = state.place;
      state.place = data.place;
      state.slots = data.slots;
      if (!options.keepSelection) {
        if (state.selectedId && !state.slots.some(slot => slot.id === state.selectedId && slot.status === 'available')) state.selectedId = null;
      }
      state.selectedId = state.slots.find(slot => slot.id === state.selectedId && slot.status === 'available')?.id || null;
      renderPlaceHeader(data);
      renderBookingForm(data);
      renderMap();
      renderSelection();
      $('#crumb-place').textContent = data.place.name;
      $('#breadcrumb-current').textContent = data.place.name;
      $('#map-updated').textContent = 'Updated just now';
      document.title = `Parkwise — ${data.place.name}`;
      if (previous && previous.slug !== slug) window.scrollTo({top:0, behavior:'instant'});
    } catch (error) {
      if (requestId !== placeRequestId) return;
      toast(error.message, true);
      $('#map-zones').innerHTML = `<div class="map-empty">${icon('info')}<strong>We couldn’t load this parking lot.</strong><br>${escapeHTML(error.message)}<br><button class="button button-white" data-action="retry-place">Try again</button></div>`;
    }
  }

  function renderPlaceHeader(data) {
    const place = data.place;
    const meta = CATEGORY_META[place.category] || {icon:'pin', label:place.category};
    $('#place-heading')?.setAttribute('aria-label', place.name);
    $('#place-hero').innerHTML = `<div class="place-hero">
      <div class="hero-cover tone-${place.category}">${icon(meta.icon)}</div>
      <div class="hero-body">
        <div class="hero-top">
          <span class="cat-badge">${icon(meta.icon)}${escapeHTML(meta.label)}</span>
          <span class="hero-rating">${icon('star')}${place.rating.toFixed(1)}</span>
          ${place.distance_km !== null ? `<span class="hero-distance">${icon('navigate')}${place.distance_km} km away</span>` : ''}
        </div>
        <h1 id="place-heading">${escapeHTML(place.name)}</h1>
        <p class="hero-address">${icon('pin')}${escapeHTML(place.address)}, ${escapeHTML(place.area)}, ${escapeHTML(place.city)}${place.pincode ? ' ' + escapeHTML(place.pincode) : ''}</p>
        <div class="hero-chips">
          <span class="hero-chip">${icon('clock')}${escapeHTML(place.hours_label)}</span>
          <span class="hero-chip">${icon('car')}${money(place.price_per_hour)} per hour</span>
          <span class="hero-chip">${icon('layers')}${place.lot_count} parking lots</span>
          <span class="hero-chip live">${icon('grid')}${data.available} of ${data.total} free now</span>
        </div>
        ${place.open_note ? `<p class="hero-note">${icon('info')}${escapeHTML(place.open_note)}</p>` : ''}
      </div>
    </div>`;
    $('#map-building-label').textContent = place.name.toUpperCase();
    $('#map-building-walk').textContent = 'Walk times shown for each lot';
    $('#lot-title').textContent = `Parking at ${place.name}`;
    $('#lot-subtitle').textContent = `Choose a green slot for ${prettyDate(state.window.date)} at ${prettyTime(state.window.time)}.`;
    $('#price-note').textContent = `${money(place.price_per_hour)} per hour at ${place.name}`;
    $('#duration-hint').textContent = `Open ${place.hours_label}. Your stay must end before closing.`;
  }

  function renderBookingForm(data) {
    const dateInput = $('#booking-date'), timeInput = $('#booking-time'), durationInput = $('#booking-duration');
    if (!dateInput.value) {
      const minDate = state.window.date;
      const maxDate = new Date(minDate + 'T12:00:00');
      maxDate.setDate(maxDate.getDate() + 30);
      dateInput.min = minDate; dateInput.max = dateString(maxDate);
    }
    dateInput.value = state.window.date;
    timeInput.value = state.window.time;
    const durations = data.durations && data.durations.length ? data.durations : [1,2,3,4,8];
    durationInput.innerHTML = durations.map(d => `<option value="${d}" ${d === state.window.duration ? 'selected' : ''}>${d} hour${d > 1 ? 's' : ''}</option>`).join('');
    if (!durations.includes(state.window.duration)) {
      state.window.duration = durations[0];
      durationInput.value = durations[0];
    }
  }

  function selectedSlot() { return state.slots.find(slot => slot.id === state.selectedId); }
  function lotInfo(code) { return state.place?.lots.find(lot => lot.code === code); }

  function renderMap() {
    const root = $('#map-zones');
    if (!root) return;
    if (!state.place) return;
    const lots = state.place.lots.filter(lot => state.lot === 'all' || lot.code === state.lot);
    const matching = state.slots.filter(slot => state.vehicle === 'all' || slot.vehicle_type === state.vehicle);
    root.classList.toggle('single-zone', state.lot !== 'all');
    $$('.zone-tabs button').forEach(button => {
      const active = button.dataset.lot === state.lot;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
    });
    if (!matching.length) {
      root.innerHTML = `<div class="map-empty">${icon('search')}<strong>No ${escapeHTML(VEHICLE_LABELS[state.vehicle] || 'matching')} slots here.</strong><br>Try another vehicle filter.<br><button class="button button-white" data-action="reset-filters">Show all parking</button></div>`;
      return;
    }
    root.innerHTML = lots.map(lot => {
      const lotSlots = state.slots.filter(slot => slot.lot === lot.code);
      const available = lotSlots.filter(slot => slot.status === 'available').length;
      return `<section class="zone-lot zone-${lot.code.toLowerCase()}" aria-label="Lot ${lot.code}, ${escapeHTML(lot.name)}">
        <div class="zone-heading"><span class="zone-badge">${lot.code}</span><div><strong>${escapeHTML(lot.name)}</strong><small>${escapeHTML(lot.tagline || (lot.slot_count + ' SLOTS'))}</small></div><span class="zone-count">${available} free</span></div>
        <div class="zone-spaces">${lotSlots.map(slot => {
          const isSelected = slot.id === state.selectedId;
          const filtered = state.vehicle !== 'all' && slot.vehicle_type !== state.vehicle;
          const disabled = slot.status !== 'available' || filtered;
          return `<button class="parking-slot is-${isSelected ? 'selected' : slot.status}${filtered ? ' is-filtered' : ''}" data-slot="${slot.id}" ${disabled ? 'disabled' : ''} aria-label="${slot.code}, ${escapeHTML(slot.vehicle_label)}, ${filtered ? 'excluded by vehicle filter' : STATUS_LABELS[slot.status]}" aria-pressed="${isSelected}" title="${slot.code} · ${escapeHTML(slot.vehicle_label)} · ${filtered ? 'Change vehicle filter to select' : STATUS_LABELS[slot.status]}">${icon(isSelected ? 'car' : VEHICLE_ICONS[slot.vehicle_type])}<span class="slot-code">${slot.code}</span></button>`;
        }).join('')}</div>
        <div class="zone-walkway">${icon('pin')}${escapeHTML(lot.walk)}${lot.description ? ' · ' + escapeHTML(lot.description) : ''}</div></section>`;
    }).join('');
  }

  function renderSelection() {
    const slot = selectedSlot();
    const button = $('#book-button');
    if (!button) return;
    const place = state.place;
    if (slot && slot.status === 'available') {
      const lot = lotInfo(slot.lot);
      $('#selected-slot-summary').className = 'selected-slot-summary';
      $('#selected-slot-summary').innerHTML = `<span class="selected-slot-number">${slot.code}</span><div class="selected-slot-info"><strong>Lot ${slot.lot} · ${escapeHTML(lot?.name || 'Parking')}</strong><p>${icon('pin')}${escapeHTML(lot?.walk || 'Short walk')} to the entrance</p></div><span class="available-tag"><span class="status-dot"></span>Free</span>`;
      $('#vehicle-type-hint').innerHTML = `${icon(VEHICLE_ICONS[slot.vehicle_type])}${escapeHTML(slot.vehicle_label)}${slot.vehicle_type === 'ev' ? ' · Charging availability not guaranteed' : ''}`;
      button.disabled = false;
      button.innerHTML = `<span>${state.user ? 'Confirm reservation' : 'Sign in to reserve'}</span>${icon('arrow')}`;
      $('#mobile-reserve-link').classList.remove('hidden');
      $('#mobile-reserve-link').innerHTML = `Continue with ${slot.code}${icon('down')}`;
      const hours = Number($('#booking-duration').value || state.window.duration);
      const fee = (place?.price_per_hour || 0) * hours;
      $('#price-total').innerHTML = `${rupee(fee)}<span id="price-detail">${hours} hour${hours > 1 ? 's' : ''}</span>`;
    } else {
      $('#mobile-reserve-link').classList.add('hidden');
      $('#selected-slot-summary').className = 'selected-slot-summary empty';
      $('#selected-slot-summary').innerHTML = `${icon('pin')}<span>Your next spot is waiting.<br>Select an available slot on the map.</span>`;
      $('#vehicle-type-hint').textContent = 'Select a slot to see its vehicle type.';
      button.disabled = true;
      button.innerHTML = `<span>Select a parking slot</span>${icon('arrow')}`;
      $('#price-total').innerHTML = `₹0<span id="price-detail">—</span>`;
    }
  }

  function selectSlot(id) {
    const slot = state.slots.find(item => item.id === id);
    if (!slot || slot.status !== 'available') return;
    state.selectedId = id;
    $('#booking-error').classList.add('hidden');
    renderMap();
    renderSelection();
    if (window.innerWidth <= 760) toast(`Slot ${slot.code} selected. Your reservation details are below the map.`);
  }

  /* ------------------------------------------------------------------- bookings */

  function renderBookings() {
    const root = $('#bookings-content');
    if (!state.user) {
      root.innerHTML = emptyState('ticket', 'Your next visit starts here.', 'Sign in to see your reservations, download a parking pass, or make a little change of plans.', '<button class="button button-primary" data-action="login">Sign in to your account</button>');
      return;
    }
    const all = state.bookings || [];
    const upcoming = all.filter(b => b.status === 'confirmed');
    const past = all.filter(b => b.status === 'completed');
    const cancelled = all.filter(b => b.status === 'cancelled');
    const groups = {upcoming, past, cancelled, all};
    const bookings = groups[state.bookingFilter] || upcoming;
    root.innerHTML = `<div class="content-toolbar"><div class="segmented" role="group" aria-label="Filter reservations">${[['upcoming','Upcoming',upcoming.length],['past','Completed',past.length],['cancelled','Cancelled',cancelled.length],['all','All bookings',all.length]].map(([key,label,count]) => `<button data-booking-filter="${key}" class="${state.bookingFilter === key ? 'active' : ''}" aria-pressed="${state.bookingFilter === key}">${label} <span>(${count})</span></button>`).join('')}</div><span class="muted-text">A little planning. A lot less circling.</span></div>`;
    if (!bookings.length) {
      const messages = {
        upcoming:['ticket','Nothing on the calendar. Yet.','Search a place, pick a free slot, and your next visit is sorted.'],
        past:['clock','Fresh starts look good on you.','Your completed reservations will appear here once the parking time ends.'],
        cancelled:['calendar','A change of plans.','Cancelled reservations stay here for your records.'],
        all:['calendar','Let’s find your first spot.','Book parking at any place and it will appear right here.'],
      };
      const [symbol, title, description] = messages[state.bookingFilter] || messages.all;
      root.innerHTML += emptyState(symbol, title, description, '<button class="button button-primary" data-nav="dashboard">Find parking ' + icon('arrow') + '</button>');
      return;
    }
    root.innerHTML += `<div class="booking-list">${bookings.map(booking => `<article class="booking-ticket">
      <div class="ticket-top">
        <span class="ticket-slot">${icon(VEHICLE_ICONS[booking.vehicle_type])}${booking.slot_code}</span>
        <div class="ticket-info"><h3>${escapeHTML(booking.place_name)}</h3><p>${escapeHTML(booking.place_category_label)} · ${escapeHTML(booking.place_area)}, ${escapeHTML(booking.place_city)}</p></div>
        <span class="status-badge ${booking.status}">${booking.status[0].toUpperCase() + booking.status.slice(1)}</span>
      </div>
      <dl class="ticket-details">
        <div><dt>PARKING DATE</dt><dd>${prettyDate(booking.date, {year:'numeric'})}</dd></div>
        <div><dt>ARRIVAL – DEPARTURE</dt><dd>${prettyTime(booking.start_time)} – ${prettyTime(booking.end_time)}</dd></div>
        <div><dt>LOT &amp; VEHICLE</dt><dd>Lot ${booking.lot} · ${escapeHTML(booking.vehicle_plate)}</dd></div>
      </dl>
      <div class="ticket-actions"><span class="ticket-reference">${booking.reference}${booking.fee ? ' · ' + rupee(booking.fee) : ''}</span><div class="ticket-actions-right"><button class="text-button" data-pass="${booking.id}">View pass ${icon('up-right')}</button>${booking.can_cancel ? `<button class="text-button cancel-link" data-cancel="${booking.id}">Cancel</button>` : ''}</div></div>
    </article>`).join('')}</div>`;
  }

  function emptyState(symbol, title, description, action = '') {
    return `<div class="empty-state"><span class="empty-state-icon">${icon(symbol)}</span><h2>${escapeHTML(title)}</h2><p>${escapeHTML(description)}</p>${action}</div>`;
  }

  /* ---------------------------------------------------------------------- modals */

  function openModal(html, wide = false) {
    if (!state.modalOpen) state.lastFocus = document.activeElement;
    $('#modal-content').innerHTML = html;
    $('#modal').classList.toggle('wide', wide);
    $('#modal-overlay').classList.remove('hidden');
    document.body.style.overflow = 'hidden';
    state.modalOpen = true;
    requestAnimationFrame(() => {
      const autofocus = $('[autofocus]', $('#modal-content'));
      (autofocus || $('#modal')).focus();
    });
  }
  function closeModal() {
    if (!state.modalOpen) return;
    $('#modal-overlay').classList.add('hidden');
    document.body.style.overflow = '';
    state.modalOpen = false;
    if (state.lastFocus?.isConnected) state.lastFocus.focus({preventScroll:true});
  }

  function showAuth(tab = 'login', context = null) {
    state.authContext = context;
    const register = tab === 'register';
    openModal(`<div class="modal-logo"><span class="brand-mark">P<span></span></span></div><div class="modal-eyebrow">ONE ACCOUNT, EVERY PLACE</div><h2 id="modal-title">${register ? 'Make yourself at home.' : 'Welcome back.'}</h2><p class="modal-description">${context === 'admin' ? 'Sign in with a venue administrator account to manage places, lots and reservations.' : register ? 'Create an account and book parking at any place in the network.' : 'Sign in to reserve your spot. We’ll keep your selection right here.'}</p><div class="segmented auth-tabs"><button data-auth-tab="login" class="${!register ? 'active' : ''}">Sign in</button><button data-auth-tab="register" class="${register ? 'active' : ''}">Create account</button></div><form class="auth-form" id="auth-form" data-mode="${tab}">${register ? '<div class="form-field"><label for="auth-name">Full name</label><input id="auth-name" name="name" placeholder="Your name" autocomplete="name" minlength="2" maxlength="100" required autofocus></div>' : ''}<div class="form-field"><label for="auth-email">Email address</label><input id="auth-email" name="email" type="email" placeholder="you@example.com" autocomplete="email" maxlength="254" required ${!register ? 'autofocus' : ''}></div><div class="form-field"><label for="auth-password">Password</label><div class="password-wrap"><input id="auth-password" name="password" type="password" placeholder="${register ? 'At least 8 characters' : 'Your password'}" autocomplete="${register ? 'new-password' : 'current-password'}" minlength="${register ? '8' : '1'}" required><button type="button" class="icon-button password-toggle" data-action="toggle-password" aria-label="Show password">${icon('eye')}</button></div></div><div class="inline-error hidden" id="auth-error" role="alert"></div><button class="button button-primary" type="submit">${register ? 'Create my account' : 'Sign in'}${icon('arrow')}</button></form>${window.PARKWISE_DEMO ? `<div class="auth-divider">JUST LOOKING AROUND?</div><div class="demo-buttons"><button class="button button-white" data-demo="driver">${icon('car')}Try driver demo</button><button class="button button-white" data-demo="admin">${icon('settings')}Try admin demo</button></div><p class="demo-notice">Explore with sample data. Demo accounts are shared.</p>` : ''}<p class="auth-footnote">This is a Phase 1 prototype. Please don’t reuse a sensitive password.</p>`);
  }

  async function completeSignIn(result) {
    const context = state.authContext;
    closeModal();
    await loadSession();
    if (state.page === 'bookings') renderBookings();
    if (context === 'admin' || (result.user.is_staff && state.page === 'admin')) navigate('admin');
    toast(`Welcome, ${result.user.name.split(' ')[0]}. ${context === 'admin' ? 'Your venue console is ready.' : 'Your next spot is waiting.'}`);
  }

  async function submitAuth(form) {
    const button = $('button[type="submit"]', form);
    const errorBox = $('#auth-error');
    button.disabled = true;
    errorBox.classList.add('hidden');
    const values = Object.fromEntries(new FormData(form));
    try {
      const result = await post(form.dataset.mode === 'register' ? '/api/auth/register/' : '/api/auth/login/', values);
      await completeSignIn(result);
    } catch (error) {
      errorBox.textContent = error.message;
      errorBox.classList.remove('hidden');
    } finally { button.disabled = false; }
  }

  async function demoSignIn(role) {
    const buttons = $$('[data-demo]');
    buttons.forEach(button => button.disabled = true);
    try {
      const result = await post('/api/auth/demo/', {role});
      await completeSignIn(result);
    } catch (error) { toast(error.message, true); }
    finally { buttons.forEach(button => button.disabled = false); }
  }

  function renderProfile() {
    const user = state.user;
    $('#profile-avatar').textContent = user?.initials || 'G';
    $('#top-avatar').textContent = user?.initials || 'G';
    $('#profile-name').textContent = user?.name || 'Guest driver';
    $('#profile-caption').textContent = user ? (user.is_staff ? 'Venue administrator' : 'Your Parkwise account') : 'Sign in to get started';
    $('#top-avatar').setAttribute('aria-label', user ? `Account: ${user.name}` : 'Sign in to your account');
  }

  function showProfile() {
    if (!state.user) return showAuth();
    openModal(`<div class="modal-eyebrow">YOUR PARKWISE ACCOUNT</div><h2 id="modal-title">Hello, ${escapeHTML(state.user.name.split(' ')[0])}.</h2><p class="modal-description">Every reservation, in one account.</p><div class="profile-details"><span class="avatar">${escapeHTML(state.user.initials)}</span><div><strong>${escapeHTML(state.user.name)}</strong><small>${escapeHTML(state.user.email)}</small></div></div><button class="button button-primary modal-full-button" data-nav="bookings">${icon('calendar')}My reservations${icon('arrow')}</button>${state.user.is_staff ? '<button class="button button-white modal-full-button" style="margin-top:10px" data-nav="admin">' + icon('settings') + 'Open admin console</button>' : ''}<button class="button button-ghost modal-full-button" style="margin-top:10px" data-action="logout">${icon('logout')}Sign out</button>`);
  }

  async function signOut() {
    try {
      await post('/api/auth/logout/');
      state.user = null;
      state.bookings = [];
      state.adminData = null;
      closeModal();
      if (state.page === 'admin') navigate('dashboard');
      await loadSession();
      renderBookings();
      toast('You’re signed out. See you soon.');
    } catch (error) { toast(error.message, true); }
  }

  /* --------------------------------------------------------------------- booking */

  async function submitBooking() {
    if (state.bookingBusy) return;
    if (!state.user) return showAuth('login', 'booking');
    if (!selectedSlot()) return toast('Select an available parking slot first.', true);
    const form = $('#booking-form');
    if (!form.reportValidity()) return;
    state.bookingBusy = true;
    const button = $('#book-button');
    const errorBox = $('#booking-error');
    button.disabled = true;
    button.innerHTML = '<span>Reserving your spot…</span><span class="spinner"></span>';
    errorBox.classList.add('hidden');
    try {
      const result = await post('/api/bookings/', {...getBookingWindow(), slot_id:state.selectedId, vehicle_plate:$('#vehicle-plate').value.trim()});
      await loadSession();
      await loadPlace(state.slug, {keepSelection:true});
      showConfirmation(result.booking);
    } catch (error) {
      errorBox.textContent = error.message;
      errorBox.classList.remove('hidden');
      if (error.status === 409) await loadPlace(state.slug);
      if (error.status === 401) showAuth('login', 'booking');
    } finally {
      state.bookingBusy = false;
      renderSelection();
    }
  }

  function getBookingWindow() {
    return {
      date: $('#booking-date').value || state.window.date,
      start_time: $('#booking-time').value || state.window.time,
      duration: Number($('#booking-duration').value || state.window.duration),
    };
  }

  function confirmationDetails(booking) {
    return `<div class="confirmation-ticket"><div class="confirmation-ticket-head"><strong>${booking.slot_code}</strong><span>Lot ${booking.lot} · ${escapeHTML(booking.place_name)}</span><span class="status-badge ${booking.status}">${booking.status[0].toUpperCase() + booking.status.slice(1)}</span></div><dl class="confirmation-grid"><div><dt>PARKING DATE</dt><dd>${prettyDate(booking.date, {year:'numeric'})}</dd></div><div><dt>YOUR TIME</dt><dd>${prettyTime(booking.start_time)} – ${prettyTime(booking.end_time)}</dd></div><div><dt>VEHICLE NUMBER</dt><dd>${escapeHTML(booking.vehicle_plate)}</dd></div><div><dt>BOOKING REFERENCE</dt><dd>${booking.reference}${booking.fee ? ' · ' + rupee(booking.fee) : ''}</dd></div></dl><p class="confirmation-address">${icon('pin')}${escapeHTML(booking.place_address)}, ${escapeHTML(booking.place_area)}</p></div>`;
  }

  function showConfirmation(booking) {
    openModal(`<div class="confirmation"><span class="success-icon">${icon('check')}</span><div class="modal-eyebrow">A LITTLE LESS DRIVING AROUND</div><h2 id="modal-title">Your spot is sorted.</h2><p class="modal-description">Head to ${escapeHTML(booking.place_name)} and park in slot ${booking.slot_code}, lot ${booking.lot}.</p>${confirmationDetails(booking)}<div class="confirmation-actions"><button class="button button-white" data-action="close-modal">Back to place</button><button class="button button-primary" data-nav="bookings">View my bookings${icon('arrow')}</button></div><a class="text-button confirmation-calendar" href="/api/bookings/${booking.id}/calendar/" download>${icon('calendar')}Add to my calendar</a><p class="auth-footnote">Your reservation is saved on the Parkwise server.<br>Please arrive and leave within your reserved time.</p></div>`);
  }

  function showPass(id) {
    const booking = state.bookings.find(item => item.id === id);
    if (!booking) return;
    openModal(`<div class="modal-eyebrow">YOUR PARKING PASS</div><h2 id="modal-title">A spot with your name on it.</h2><p class="modal-description">Keep this reference handy when you arrive.</p>${confirmationDetails(booking)}<div class="confirmation-actions"><button class="button button-white" data-action="close-modal">Close pass</button>${booking.status === 'confirmed' ? `<a class="button button-primary" href="/api/bookings/${booking.id}/calendar/" download>${icon('download')}Add to calendar</a>` : '<button class="button button-primary" data-nav="dashboard">Find a new spot</button>'}</div>${booking.can_cancel ? `<button class="text-button cancel-link" style="margin-top:20px" data-cancel="${booking.id}">Need to cancel this reservation?</button>` : ''}`);
  }

  function confirmCancel(id, admin = false) {
    const booking = (admin ? state.adminData?.bookings : state.bookings)?.find(item => item.id === id);
    if (!booking) return;
    openModal(`<div class="modal-eyebrow">A CHANGE OF PLANS</div><h2 id="modal-title">Release this spot?</h2><p class="modal-description">Cancel your ${booking.slot_code} reservation at ${escapeHTML(booking.place_name)} on ${prettyDate(booking.date)} at ${prettyTime(booking.start_time)}? The slot becomes available to someone else.</p><div class="admin-notice">${icon('info')}There’s no cancellation fee in this prototype.</div><div class="modal-button-row"><button class="button button-white" data-action="close-modal">Keep my spot</button><button class="button button-danger" data-confirm-cancel="${id}" data-admin-cancel="${admin}">Yes, cancel booking</button></div>`);
  }

  async function cancelBooking(id, admin, button) {
    button.disabled = true;
    try {
      await post(admin ? `/api/admin/bookings/${id}/cancel/` : `/api/bookings/${id}/cancel/`);
      closeModal();
      await loadSession();
      if (state.page === 'bookings') renderBookings();
      if (state.place) await loadPlace(state.slug, {keepSelection:true});
      if (admin) await loadAdmin();
      toast('Reservation cancelled. The parking slot is available again.');
    } catch (error) { toast(error.message, true); button.disabled = false; }
  }

  /* ----------------------------------------------------------------------- admin */

  async function loadAdmin() {
    const root = $('#admin-content');
    $('#admin-export').classList.toggle('hidden', !state.user?.is_staff);
    if (!state.user?.is_staff) {
      root.innerHTML = emptyState('shield', 'A little behind-the-scenes access.', state.user ? 'This is a driver account. Sign in with an administrator account to manage places, lots and reservations.' : 'The admin console is for venue administrators. Manage places, parking slots and reservations in one place.', `<button class="button button-primary" data-action="admin-login">${icon('lock')}${state.user ? 'Switch to an admin account' : 'Sign in as an administrator'}</button>${window.PARKWISE_DEMO ? '<button class="button button-white" style="margin-left:10px" data-demo="admin">Explore admin demo</button>' : ''}`);
      return;
    }
    if (!state.adminData) root.innerHTML = '<div class="empty-state"><span class="spinner"></span><p>Getting the network overview…</p></div>';
    try {
      state.adminData = await api('/api/admin/overview/');
      renderAdmin();
    } catch (error) {
      root.innerHTML = emptyState('info', 'We couldn’t load the console.', error.message, '<button class="button button-primary" data-action="retry-admin">Try again</button>');
    }
  }

  function renderAdmin() {
    const data = state.adminData;
    if (!data || !state.user?.is_staff) return;
    const freeNow = data.slots.filter(slot => slot.status === 'available').length;
    const activePlaces = data.places.filter(place => place.is_active).length;
    $('#admin-content').innerHTML = `<div class="admin-notice">${icon('shield')}Administrator workspace · Changes are saved to the central Parkwise database.</div><div class="stats-grid admin-stats">${[['Places taking bookings', activePlaces, 'store', 'mint'], ['Parking slots', data.total_slots, 'grid', 'blue'], ['Active reservations', data.active_count, 'calendar', 'peach'], ['Registered drivers', data.user_count, 'access', 'lilac']].map(([label, value, symbol, color]) => `<article class="stat-card"><div class="stat-top"><span>${label}</span><span class="stat-icon ${color}">${icon(symbol)}</span></div><div class="stat-value"><strong>${String(value).padStart(2, '0')}</strong></div><div class="stat-bottom">${label === 'Parking slots' ? freeNow + ' free right now' : 'Central Parkwise records'}</div></article>`).join('')}</div><div class="segmented admin-tabs"><button data-admin-tab="reservations" class="${state.adminTab === 'reservations' ? 'active' : ''}">Reservations</button><button data-admin-tab="places" class="${state.adminTab === 'places' ? 'active' : ''}">Places</button><button data-admin-tab="slots" class="${state.adminTab === 'slots' ? 'active' : ''}">Parking slots</button></div><section class="card"><div class="table-heading"><h2>${state.adminTab === 'reservations' ? 'All reservations' : state.adminTab === 'places' ? 'Places on the network' : 'Parking slot directory'}</h2><div class="table-tools"><label class="admin-search">${icon('search')}<input id="admin-search" placeholder="${state.adminTab === 'reservations' ? 'Search driver, place, reference…' : state.adminTab === 'places' ? 'Search place, area, city…' : 'Search slot or place…'}" aria-label="Search admin records" value="${escapeHTML(state.adminSearch)}"></label><select class="admin-filter" id="admin-status" aria-label="Filter record status">${(state.adminTab === 'reservations' ? [['all','All statuses'],['confirmed','Confirmed'],['completed','Completed'],['cancelled','Cancelled']] : state.adminTab === 'places' ? [['all','All places'],['active','Taking bookings'],['paused','Paused']] : [['all','All slots'],['available','Available'],['reserved','Reserved / occupied'],['unavailable','Closed']]).map(([value, label]) => `<option value="${value}" ${state.adminStatus === value ? 'selected' : ''}>${label}</option>`).join('')}</select>${state.adminTab === 'places' ? `<button class="button button-primary" data-action="add-place">${icon('plus')}Add place</button>` : state.adminTab === 'slots' ? `<button class="button button-primary" data-action="add-slot">${icon('plus')}Add slot</button>` : ''}</div></div><div id="admin-table"></div></section>`;
    renderAdminTable();
  }

  function renderAdminTable() {
    const data = state.adminData;
    if (!data || !state.user?.is_staff) return;
    const query = state.adminSearch.trim().toLowerCase();
    const match = (...fields) => !query || fields.join(' ').toLowerCase().includes(query);
    let html;
    if (state.adminTab === 'reservations') {
      const rows = data.bookings.filter(b => match(b.reference, b.user_name, b.user_email, b.slot_code, b.place_name, b.vehicle_plate) && (state.adminStatus === 'all' || b.status === state.adminStatus));
      html = `<table class="data-table"><thead><tr><th>Reservation</th><th>Driver</th><th>Place &amp; slot</th><th>Date &amp; time</th><th>Status</th><th>Action</th></tr></thead><tbody>${rows.length ? rows.map(b => `<tr><td><span class="table-primary">${b.reference}</span><span class="table-secondary">${escapeHTML(b.vehicle_plate)}${b.fee ? ' · ' + rupee(b.fee) : ''}</span></td><td><span class="table-primary">${escapeHTML(b.user_name)}</span><span class="table-secondary">${escapeHTML(b.user_email)}</span></td><td><span class="table-primary">${escapeHTML(b.place_name)}</span><span class="table-secondary">Lot ${b.lot} · ${b.slot_code} · ${escapeHTML(b.place_area)}</span></td><td><span class="table-primary">${prettyDate(b.date)}</span><span class="table-secondary">${prettyTime(b.start_time)} – ${prettyTime(b.end_time)}</span></td><td><span class="status-badge ${b.status}">${b.status[0].toUpperCase() + b.status.slice(1)}</span></td><td>${b.status === 'confirmed' ? `<button class="text-button cancel-link" data-admin-booking-cancel="${b.id}">Cancel</button>` : '<span class="table-secondary">—</span>'}</td></tr>`).join('') : `<tr><td colspan="6" class="table-empty">No reservations match this view.</td></tr>`}</tbody></table>`;
    } else if (state.adminTab === 'places') {
      const rows = data.places.filter(p => match(p.name, p.area, p.city, p.category_label) && (state.adminStatus === 'all' || (state.adminStatus === 'active' ? p.is_active : !p.is_active)));
      html = `<table class="data-table"><thead><tr><th>Place</th><th>Type</th><th>Location</th><th>Price &amp; hours</th><th>Slots</th><th>Action</th></tr></thead><tbody>${rows.length ? rows.map(p => `<tr><td><span class="table-primary">${escapeHTML(p.name)}</span><span class="table-secondary">${p.is_active ? 'Taking bookings' : 'Paused'}</span></td><td><span class="table-primary">${escapeHTML(p.category_label)}</span></td><td><span class="table-primary">${escapeHTML(p.area)}</span><span class="table-secondary">${escapeHTML(p.city)}</span></td><td><span class="table-primary">${rupee(p.price_per_hour)}/hr</span><span class="table-secondary">${escapeHTML(p.hours_label)}</span></td><td><span class="table-primary">${p.available}/${p.total}</span><span class="table-secondary">${p.lot_count} lots</span></td><td><button class="text-button" data-toggle-place="${p.id}" data-active="${p.is_active}">${p.is_active ? 'Pause bookings' : 'Reopen'}</button></td></tr>`).join('') : `<tr><td colspan="6" class="table-empty">No places match this view.</td></tr>`}</tbody></table>`;
    } else {
      const rows = data.slots.filter(s => match(s.code, s.vehicle_label) && (state.adminStatus === 'all' || (state.adminStatus === 'available' ? s.status === 'available' : state.adminStatus === 'unavailable' ? s.status === 'unavailable' : ['booked','occupied'].includes(s.status))));
      html = `<table class="data-table"><thead><tr><th>Slot</th><th>Lot</th><th>Vehicle type</th><th>Status</th><th>Action</th></tr></thead><tbody>${rows.length ? rows.slice(0, 200).map(s => `<tr><td><span class="table-primary">${s.code}</span></td><td><span class="table-primary">Lot ${s.lot}</span><span class="table-secondary">${escapeHTML(s.lot_name)}</span></td><td><span class="table-primary">${escapeHTML(s.vehicle_label)}</span></td><td><span class="status-badge ${s.status === 'available' ? 'confirmed' : s.status === 'unavailable' ? 'cancelled' : 'completed'}">${escapeHTML(STATUS_LABELS[s.status])}</span></td><td><button class="text-button" data-toggle-slot="${s.id}" data-disable="${s.status !== 'unavailable'}">${s.status === 'unavailable' ? 'Reopen slot' : 'Close slot'}</button></td></tr>`).join('') : `<tr><td colspan="5" class="table-empty">No slots match this view.</td></tr>`}</tbody></table>`;
    }
    $('#admin-table').innerHTML = html;
  }

  function showAddPlace() {
    openModal(`<div class="modal-eyebrow">GROW THE NETWORK</div><h2 id="modal-title">Add a place.</h2><p class="modal-description">New places start with two lots and 16 car slots, ready to take reservations.</p><form id="add-place-form" class="auth-form"><div class="form-field"><label for="place-name">Place name</label><input id="place-name" name="name" placeholder="e.g. Marine Drive Mall" minlength="2" maxlength="120" required autofocus></div><div class="form-row"><div class="form-field"><label for="place-type">Type</label><select id="place-type" name="category">${(state.adminData?.categories || []).map(c => `<option value="${c.value}">${c.singular}</option>`).join('')}</select></div><div class="form-field"><label for="place-area">Area / locality</label><input id="place-area" name="area" placeholder="e.g. Marine Drive" maxlength="80" required></div></div><div class="form-row"><div class="form-field"><label for="place-city">City</label><input id="place-city" name="city" value="Kochi" maxlength="80"></div><div class="form-field"><label for="place-price">Price per hour (₹)</label><input id="place-price" name="price_per_hour" type="number" min="0" max="2000" value="20" required></div></div><div class="form-row"><div class="form-field"><label for="place-open">Opens</label><input id="place-open" name="open_time" type="time" value="09:00" required></div><div class="form-field"><label for="place-close">Closes</label><input id="place-close" name="close_time" type="time" value="22:00" required></div></div><div class="inline-error hidden" id="place-error" role="alert"></div><button class="button button-primary" type="submit">${icon('plus')}Add place to network</button></form>`, true);
  }

  async function addPlace(form) {
    const button = $('button[type="submit"]', form);
    const errorBox = $('#place-error');
    button.disabled = true;
    errorBox.classList.add('hidden');
    try {
      const result = await post('/api/admin/places/', Object.fromEntries(new FormData(form)));
      closeModal();
      state.adminData = null;
      await loadAdmin();
      await loadPlaces();
      toast(`${result.place.name} added. It is taking bookings now.`);
    } catch (error) {
      errorBox.textContent = error.message;
      errorBox.classList.remove('hidden');
    } finally { button.disabled = false; }
  }

  function showAddSlot() {
    const places = state.adminData?.places || [];
    if (!places.length) return toast('Add a place before adding slots.', true);
    openModal(`<div class="modal-eyebrow">LOT DIRECTORY</div><h2 id="modal-title">Add a parking slot.</h2><p class="modal-description">Slot codes use the lot letter first, for example A09.</p><form id="add-slot-form" class="auth-form"><div class="form-field"><label for="slot-place">Place</label><select id="slot-place" name="place_id">${places.map(p => `<option value="${p.id}">${escapeHTML(p.name)} · ${escapeHTML(p.area)}</option>`).join('')}</select></div><div class="form-row"><div class="form-field"><label for="slot-code">Slot number</label><input id="slot-code" name="code" placeholder="A09" pattern="[A-C][0-9]{2,3}" maxlength="4" required autofocus></div><div class="form-field"><label for="slot-vehicle">Vehicle type</label><select id="slot-vehicle" name="vehicle_type">${Object.entries(VEHICLE_LABELS).map(([value, label]) => `<option value="${value}">${label}</option>`).join('')}</select></div></div><p class="field-hint">Lots A, B and C exist at every place. Use the lot letter that matches the slot's location.</p><div class="inline-error hidden" id="slot-error" role="alert"></div><button class="button button-primary" type="submit">${icon('plus')}Add parking slot</button></form>`);
  }

  async function addSlot(form) {
    const button = $('button[type="submit"]', form);
    const errorBox = $('#slot-error');
    button.disabled = true;
    errorBox.classList.add('hidden');
    const values = Object.fromEntries(new FormData(form));
    values.place_id = Number(values.place_id);
    try {
      await post('/api/admin/slots/', values);
      closeModal();
      state.adminData = null;
      await loadAdmin();
      toast('Parking slot added to the lot.');
    } catch (error) {
      errorBox.textContent = error.message;
      errorBox.classList.remove('hidden');
    } finally { button.disabled = false; }
  }

  async function togglePlace(id, active) {
    try {
      await post(`/api/admin/places/${id}/`, {is_active: !active});
      state.adminData = null;
      await loadAdmin();
      await loadPlaces();
      toast(active ? 'Place paused. It no longer accepts new reservations.' : 'Place reopened for bookings.');
    } catch (error) { toast(error.message, true); }
  }

  async function toggleSlot(id, disable) {
    try {
      await post(`/api/admin/slots/${id}/`, {is_disabled: disable});
      state.adminData = null;
      await loadAdmin();
      toast(disable ? 'Slot closed for maintenance.' : 'Slot reopened.');
    } catch (error) { toast(error.message, true); }
  }

  /* ------------------------------------------------------------------ info modals */

  function showGuide() {
    openModal(`<div class="modal-eyebrow">THREE STEPS, ONE SPOT</div><h2 id="modal-title">How Parkwise works.</h2><p class="modal-description">From “where am I going?” to “slot 12 at the mall”.</p><div class="steps-list">${[
      ['search','Search the place','Type a mall, theatre, restaurant, college or hospital — or browse by type near you.'],
      ['car','See real availability','Every place shows how many slots are free for your arrival time and stay length. Open the place to pick a specific slot.'],
      ['check','Book before you drive','Choose your date, arrival time and vehicle, then confirm. Your pass is saved to My bookings.'],
    ].map(([symbol, title, text], index) => `<div class="step-row"><span class="step-number">${index + 1}</span><span class="step-icon">${icon(symbol)}</span><div><strong>${title}</strong><p>${text}</p></div></div>`).join('')}</div><button class="button button-primary modal-full-button" data-action="close-modal">Start searching${icon('arrow')}</button>`, true);
  }

  function showAbout() {
    openModal(`<div class="modal-eyebrow">BCN · PROJECT PHASE 1</div><h2 id="modal-title">One app. Every parking lot.</h2><p class="modal-description">Parkwise is a working prototype of the <strong>Smart Parking Slot Booking System</strong>, reworked from a single-campus app into a place-search booking network.</p><div class="info-section"><h3>What changed in this version</h3><p>The original build only reserved slots at one campus, and the demo had to run on a laptop that every driver reached over the same local Wi-Fi. Now drivers search for a place — a mall, theatre, restaurant, college, hospital, office park or stadium — and book a slot at that venue from any network.</p></div><div class="info-section"><h3>Where the parking data comes from</h3><p>Sample venues and lots around Kochi are seeded into SQLite. Slot counts come from real reservation records in the database, refreshed every 20 seconds. There are no sensors, cameras or automatic number-plate recognition in this prototype.</p></div><div class="info-section"><h3>The people behind the proposal</h3><div class="team-list">${['Aflah','Ajo','Hilda','Shahma','Ameeshah'].map(name => `<span>${name}</span>`).join('')}</div><p style="margin-top:9px">Department of Computer Science &amp; Engineering<br>Bachelor of Technology · Computer Networking project</p></div><div class="info-section"><h3>Simple tools. Practical networking.</h3><div class="info-chips">${['HTML5','CSS3','JavaScript','Python','Django','SQLite','Place search API'].map(label => `<span class="info-chip">${label}</span>`).join('')}</div></div><div class="info-section"><h3>An honest look at the scope</h3><ul><li>Availability is reservation-based. A green slot means no overlapping reservation, not a verified empty space.</li><li>Prices and opening hours are sample settings for each seeded venue, not the venues’ published tariffs.</li><li>No payment gateway is connected — every reservation is free in this prototype.</li><li>SQLite suits a small single-server prototype. A production rollout would need PostgreSQL, HTTPS deployment and a security review.</li></ul></div><button class="button button-primary modal-full-button" data-action="guide">See how booking works${icon('arrow')}</button>`, true);
  }

  function showHelp() {
    openModal(`<div class="modal-eyebrow">A LITTLE HELP GOES A LONG WAY</div><h2 id="modal-title">Good questions.</h2><p class="modal-description">Here’s what to know before you drive.</p>${[
      ['Do I need to be on the venue’s Wi-Fi?','No. That requirement is gone. Parkwise is a normal web app: sign in from mobile data or any network and book at any place in the network.'],
      ['How do I find parking?','Type a place name — “Lulu Mall”, “Cinepolis”, “CUSAT” — or tap a place type to browse malls, theatres, restaurants, colleges, hospitals, offices and stadiums near you.'],
      ['Is the green status detecting an empty slot?','No. Green means there is no overlapping reservation and the slot is not closed by an administrator. This prototype has no physical sensors, so follow signage on arrival.'],
      ['Why does a place show “Full for this time”?','Every slot there already has a reservation overlapping your arrival time and stay length. Change the arrival time, shorten the stay, or pick another place.'],
      ['When can I reserve a slot?','Arrive from today up to 30 days ahead, with a 1, 2, 3, 4 or 8-hour stay. The stay must fit inside that venue’s opening hours — each place has its own.'],
      ['What does it cost?','Each venue has an hourly price shown on its card. The fee is calculated when you book and stored with your reservation. No payment is collected in this prototype.'],
      ['Can I cancel?','Yes, free of charge any time before your arrival time, from My bookings. The slot returns to the pool immediately.'],
      ['Can I use this on my phone?','Yes. The interface is responsive, and the map scrolls horizontally so every lot stays readable on a small screen.'],
      ['Is this a production parking service?','No. It is a Phase 1 educational prototype using sample venue data. Real deployment needs verified venue agreements, payments, and a security review.'],
    ].map(([question, answer], index) => `<details class="faq" ${index === 0 ? 'open' : ''}><summary>${question}</summary><p>${answer}</p></details>`).join('')}<button class="text-button" style="margin-top:23px" data-action="about">Read about the BCN project${icon('up-right')}</button>`, true);
  }

  /* ------------------------------------------------------------------ navigation */

  const PAGES = {
    dashboard: {name:'Find parking', path:'/'},
    bookings: {name:'My bookings', path:'/bookings/'},
    admin: {name:'Admin console', path:'/admin-panel/'},
  };

  function navigate(page, push = true, slug = '') {
    if (!['dashboard', 'bookings', 'admin', 'place'].includes(page)) page = 'dashboard';
    if (page === 'place' && !slug) return navigate('dashboard', push);
    state.page = page;
    if (page === 'place') state.slug = slug;
    closeModal();
    closeSidebar();
    $$('.page').forEach(section => section.classList.toggle('hidden', section.id !== 'page-' + (page === 'place' ? 'place' : page)));
    $$('.nav-item[data-nav]').forEach(link => {
      const nav = link.dataset.nav;
      const active = nav === page || (nav === 'dashboard' && page === 'place');
      link.classList.toggle('active', active);
      if (active) link.setAttribute('aria-current','page'); else link.removeAttribute('aria-current');
    });
    const path = page === 'place' ? `/place/${slug}/` : PAGES[page].path;
    const name = page === 'place' ? (state.place?.name || 'Place') : PAGES[page].name;
    $('#breadcrumb-current').textContent = name;
    document.title = `Parkwise — ${name}`;
    if (push) history.pushState({page, slug}, '', path);
    if (page === 'bookings') { renderBookings(); loadSession().then(renderBookings).catch(() => {}); }
    if (page === 'admin') loadAdmin();
    if (page === 'place') loadPlace(slug);
    window.scrollTo({top:0, behavior:'instant'});
  }

  function closeSidebar() { $('#sidebar').classList.remove('open'); $('#sidebar-scrim').classList.remove('visible'); }

  function syncWindowFromSearch() {
    const date = $('#search-date').value, time = $('#search-time').value;
    if (date) state.window.date = date;
    if (time) state.window.time = time;
    const duration = Number($('#search-duration').value);
    if (duration) state.window.duration = duration;
  }

  function openPlaceFromCard(slug) {
    syncWindowFromSearch();
    state.selectedId = null;
    navigate('place', true, slug);
  }

  /* ----------------------------------------------------------------- event wiring */

  document.addEventListener('click', async event => {
    const target = event.target.closest('button,a,[data-action],[data-place]');
    if (!target || target.disabled) return;
    if (target.dataset.nav) {
      event.preventDefault();
      state.selectedId = null;
      navigate(target.dataset.nav);
      return;
    }
    if (target.dataset.place) { openPlaceFromCard(target.dataset.place); return; }
    if (target.dataset.category !== undefined) { state.category = target.dataset.category; renderCategoryChips(); loadPlaces(); return; }
    if (target.dataset.quick) {
      state.q = target.dataset.quick; state.category = '';
      $('#place-search').value = state.q;
      renderCategoryChips(); loadPlaces(); return;
    }
    if (target.dataset.slot) { selectSlot(Number(target.dataset.slot)); return; }
    if (target.dataset.lot) { state.lot = target.dataset.lot; renderMap(); return; }
    if (target.dataset.bookingFilter) { state.bookingFilter = target.dataset.bookingFilter; renderBookings(); return; }
    if (target.dataset.authTab) { showAuth(target.dataset.authTab, state.authContext); return; }
    if (target.dataset.demo) { await demoSignIn(target.dataset.demo); return; }
    if (target.dataset.pass) { showPass(Number(target.dataset.pass)); return; }
    if (target.dataset.cancel) { confirmCancel(Number(target.dataset.cancel)); return; }
    if (target.dataset.confirmCancel) { await cancelBooking(Number(target.dataset.confirmCancel), target.dataset.adminCancel === 'true', target); return; }
    if (target.dataset.adminTab) { state.adminTab = target.dataset.adminTab; state.adminSearch = ''; state.adminStatus = 'all'; renderAdmin(); return; }
    if (target.dataset.adminBookingCancel) { confirmCancel(Number(target.dataset.adminBookingCancel), true); return; }
    if (target.dataset.togglePlace) { await togglePlace(Number(target.dataset.togglePlace), target.dataset.active === 'true'); return; }
    if (target.dataset.toggleSlot) { await toggleSlot(Number(target.dataset.toggleSlot), target.dataset.disable === 'true'); return; }
    const action = target.dataset.action;
    if (!action) return;
    const actions = {
      'guide':showGuide, 'about':showAbout, 'help':showHelp,
      'profile':showProfile, 'close-modal':closeModal, 'login':() => showAuth(), 'admin-login':() => showAuth('login','admin'),
      'logout':signOut, 'retry-admin':loadAdmin, 'retry-place':() => loadPlace(state.slug),
      'refresh-places':() => loadPlaces(true),
      'clear-search':() => {state.q = ''; $('#place-search').value = ''; $('#clear-search').classList.add('hidden'); loadPlaces();},
      'reset-filters':() => {state.vehicle = 'all'; $('#vehicle-filter').value = 'all'; renderMap();},
      'locate':locateUser,
      'menu':() => {$('#sidebar').classList.toggle('open'); $('#sidebar-scrim').classList.toggle('visible');},
      'toggle-password':() => {const input = $('#auth-password'); const show = input.type === 'password'; input.type = show ? 'text' : 'password'; target.setAttribute('aria-label', show ? 'Hide password' : 'Show password');},
      'reservation':() => {$('.reservation-card').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block:'start'}); $('#booking-date').focus({preventScroll:true});},
      'add-place':showAddPlace, 'add-slot':showAddSlot,
      'export':() => {window.location.href = '/api/admin/export/';},
    };
    actions[action]?.();
  });

  document.addEventListener('keydown', event => {
    if (event.key === 'Enter' && event.target.matches?.('[data-place]')) {
      event.preventDefault();
      openPlaceFromCard(event.target.dataset.place);
    }
  });

  document.addEventListener('submit', event => {
    const form = event.target;
    if (form.id === 'search-form') {
      event.preventDefault();
      syncWindowFromSearch();
      state.q = $('#place-search').value.trim();
      loadPlaces();
      $('#place-search').blur();
    }
    if (form.id === 'booking-form') { event.preventDefault(); submitBooking(); }
    if (form.id === 'auth-form') { event.preventDefault(); submitAuth(form); }
    if (form.id === 'add-place-form') { event.preventDefault(); addPlace(form); }
    if (form.id === 'add-slot-form') { event.preventDefault(); addSlot(form); }
  });

  document.addEventListener('change', event => {
    const target = event.target;
    if (target.id === 'vehicle-filter') { state.vehicle = target.value; renderMap(); return; }
    if (target.id === 'sort-select') { state.sort = target.value; loadPlaces(); return; }
    if (['search-date', 'search-time', 'search-duration'].includes(target.id)) {
      syncWindowFromSearch();
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => { if (state.page === 'place') loadPlace(state.slug); else loadPlaces(); }, 220);
      return;
    }
    if (['booking-date', 'booking-time', 'booking-duration'].includes(target.id)) {
      if (!state.place) return;
      const start = new Date(`${$('#booking-date').value}T${$('#booking-time').value}`);
      const end = new Date(start.getTime() + Number($('#booking-duration').value) * 3600000);
      const closeParts = state.place.close_time.split(':').map(Number);
      const close = new Date(`${$('#booking-date').value}T00:00`);
      close.setHours(closeParts[0], closeParts[1]);
      if (end > close || start.getTime() < Date.now() - 60000) {
        $('#booking-error').textContent = `${state.place.name} is open ${state.place.hours_label}. Choose an arrival time and stay that finish before closing.`;
        $('#booking-error').classList.remove('hidden');
      } else {
        $('#booking-error').classList.add('hidden');
      }
      state.window = {date:$('#booking-date').value, time:$('#booking-time').value, duration:Number($('#booking-duration').value)};
      renderSelection();
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => loadPlace(state.slug, {keepSelection:true, autoFit:false}), 220);
      return;
    }
    if (target.id === 'admin-status') { state.adminStatus = target.value; renderAdminTable(); }
  });

  document.addEventListener('input', event => {
    const target = event.target;
    if (target.id === 'admin-search') { state.adminSearch = target.value; renderAdminTable(); }
    if (target.id === 'vehicle-plate') target.value = target.value.toUpperCase();
    if (target.id === 'place-search') {
      $('#clear-search').classList.toggle('hidden', !target.value);
      state.q = target.value.trim();
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => { if (state.page === 'dashboard') loadPlaces(); }, 260);
    }
  });

  $('#modal-overlay').addEventListener('click', event => { if (event.target === event.currentTarget) closeModal(); });
  $('#sidebar-scrim').addEventListener('click', closeSidebar);
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') { closeModal(); closeSidebar(); }
    if (event.key === 'Tab' && state.modalOpen) {
      const elements = $$('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),summary,[tabindex="0"]', $('#modal')).filter(el => el.getClientRects().length);
      const first = elements[0], last = elements[elements.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === $('#modal'))) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && (document.activeElement === last || document.activeElement === $('#modal'))) { event.preventDefault(); first?.focus(); }
    }
  });

  window.addEventListener('popstate', () => {
    const path = location.pathname;
    const match = path.match(/^\/place\/([^/]+)\/?/);
    if (match) navigate('place', false, decodeURIComponent(match[1]));
    else if (path.startsWith('/bookings')) navigate('bookings', false);
    else if (path.startsWith('/admin-panel')) navigate('admin', false);
    else navigate('dashboard', false);
  });

  document.addEventListener('visibilitychange', () => {
    if (document.hidden || state.modalOpen) return;
    if (state.page === 'dashboard') loadPlaces();
    if (state.page === 'place') loadPlace(state.slug, {keepSelection:true});
  });

  /* -------------------------------------------------------------- optional geolocation */

  function locateUser() {
    if (!navigator.geolocation) return toast('This browser cannot share your location. Showing places around Kochi.', true);
    toast('Looking for places near you…');
    navigator.geolocation.getCurrentPosition(position => {
      state.origin = {lat:position.coords.latitude.toFixed(5), lng:position.coords.longitude.toFixed(5)};
      $('#location-label').textContent = 'Near your location';
      loadPlaces();
      if (state.page === 'place') loadPlace(state.slug);
      toast('Sorted by distance from your location.');
    }, () => toast('Location permission was not granted. Showing places around Kochi.', true), {timeout:8000, maximumAge:600000});
  }

  /* ------------------------------------------------------------------------- init */

  async function init() {
    $$('.page').forEach(section => section.classList.toggle('hidden', section.id !== 'page-' + (state.page === 'place' ? 'place' : state.page)));
    try {
      await loadSession();
    } catch (error) {
      toast(error.message, true);
      applyFallbackWindow();
    }
    if (state.page === 'dashboard' || state.page === 'notfound' || state.page === 'bookings' || state.page === 'admin') {
      if (state.page === 'dashboard') await loadPlaces();
      if (state.page === 'bookings') renderBookings();
      if (state.page === 'admin') await loadAdmin();
    }
    if (state.page === 'place') {
      state.window.date = $('#search-date')?.value || state.window.date;
      await loadPlace(state.slug);
      if (state.page === 'place') { history.replaceState({page:'place', slug:state.slug}, '', `/place/${state.slug}/`); }
    }
    if (new URLSearchParams(location.search).has('signin') && !state.user) showAuth();
    refreshTimer = setInterval(() => {
      if (document.hidden || state.modalOpen || state.bookingBusy) return;
      if (state.page === 'dashboard') loadPlaces();
      if (state.page === 'place') loadPlace(state.slug, {keepSelection:true});
    }, 20000);
    window.addEventListener('beforeunload', () => clearInterval(refreshTimer));
  }

  init();
})();
