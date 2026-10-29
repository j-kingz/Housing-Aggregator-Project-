/*
 * Maps and the GPS picker.
 *
 * Uses Google Maps when a key is configured and it loads, otherwise
 * OpenStreetMap through Leaflet, so a map is always shown.
 *
 *   <div class="ha-map" data-points='[{"lat":-1.28,"lng":36.82,"label":"Flat","url":"/listings/1"}]'
 *        data-target='{"lat":-1.29,"lng":36.8,"label":"Work"}'></div>
 *
 * A picker map (data-pick-lat / data-pick-lng = ids of the inputs) lets the
 * person click the map or drag the pin to set an exact GPS point.
 */
(function () {
  'use strict';

  const KENYA_CENTER = {lat: -1.2921, lng: 36.8219};
  const LEAFLET_JS = 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js';
  const LEAFLET_CSS = 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css';

  function engine() {
    return new Promise(resolve => {
      if (!document.body.dataset.googleKey) return resolve('leaflet');
      if (window.HA_GOOGLE_READY) return resolve('google');
      if (window.HA_GOOGLE_FAILED) return resolve('leaflet');
      document.addEventListener('ha-google-ready', () => resolve('google'), {once: true});
      document.addEventListener('ha-google-failed', () => resolve('leaflet'), {once: true});
      setTimeout(() => resolve(window.HA_GOOGLE_READY ? 'google' : 'leaflet'), 7000);
    });
  }

  let leafletPromise;
  function loadLeaflet() {
    if (window.L) return Promise.resolve();
    if (!leafletPromise) {
      leafletPromise = new Promise((resolve, reject) => {
        const css = document.createElement('link');
        css.rel = 'stylesheet'; css.href = LEAFLET_CSS;
        document.head.appendChild(css);
        const js = document.createElement('script');
        js.src = LEAFLET_JS; js.onload = resolve; js.onerror = reject;
        document.head.appendChild(js);
      });
    }
    return leafletPromise;
  }

  // straight-line distance in km, for the labels and dashed lines
  function km(a, b) {
    const R = 6371.0088, rad = x => x * Math.PI / 180;
    const dLat = rad(b.lat - a.lat), dLng = rad(b.lng - a.lng);
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLng / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(h));
  }
  function withDistance(p, target) {
    if (!target) return p.label;
    return p.label + ' - ' + km(p, target).toFixed(1) + ' km from ' + target.label;
  }

  function parse(el, name) {
    try { return JSON.parse(el.dataset[name] || 'null'); } catch (e) { return null; }
  }

  function setInputs(el, lat, lng) {
    const la = document.querySelector(el.dataset.pickLat);
    const ln = document.querySelector(el.dataset.pickLng);
    if (la) la.value = Number(lat).toFixed(6);
    if (ln) ln.value = Number(lng).toFixed(6);
    if (la) la.dispatchEvent(new Event('change', {bubbles: true}));
  }

  async function drawGoogle(el, points, target, picking) {
    const lib = await google.maps.importLibrary('maps');
    const all = points.concat(target ? [target] : []);
    const map = new lib.Map(el, {
      center: all.length ? {lat: all[0].lat, lng: all[0].lng} : KENYA_CENTER,
      zoom: all.length === 1 ? 16 : 12, mapTypeControl: false, streetViewControl: false,
    });
    const bounds = new google.maps.LatLngBounds();
    const info = new google.maps.InfoWindow();
    const markers = [];

    function add(p, isTarget) {
      const marker = new google.maps.Marker({
        map, position: {lat: p.lat, lng: p.lng}, title: p.label,
        draggable: !!picking && !isTarget,
        icon: isTarget ? {path: google.maps.SymbolPath.CIRCLE, scale: 9, fillColor: '#f59e0b', fillOpacity: 1, strokeColor: '#b45309', strokeWeight: 2} : undefined,
      });
      if (p.label && !picking) {
        marker.addListener('click', () => {
          const div = document.createElement('div');
          const strong = document.createElement('strong'); strong.textContent = withDistance(p, isTarget ? null : target); div.appendChild(strong);
          if (p.url) { div.appendChild(document.createElement('br')); const a = document.createElement('a'); a.href = p.url; a.textContent = 'Open'; div.appendChild(a); }
          info.setContent(div); info.open(map, marker);
        });
      }
      bounds.extend(marker.getPosition());
      markers.push(marker);
      return marker;
    }
    points.forEach(p => add(p, false));
    if (target) add(target, true);
    if (all.length > 1) map.fitBounds(bounds, 40);

    if (target && !picking) {
      points.slice(0, 40).forEach(p => {
        new google.maps.Polyline({
          map, path: [{lat: p.lat, lng: p.lng}, {lat: target.lat, lng: target.lng}],
          strokeColor: '#f59e0b', strokeOpacity: 0, strokeWeight: 2,
          icons: [{icon: {path: 'M 0,-1 0,1', strokeOpacity: 0.9, scale: 3}, offset: '0', repeat: '14px'}],
        });
      });
      if (points.length === 1) {
        new google.maps.Marker({
          map, clickable: false,
          position: {lat: (points[0].lat + target.lat) / 2, lng: (points[0].lng + target.lng) / 2},
          icon: {path: google.maps.SymbolPath.CIRCLE, scale: 0},
          label: {text: km(points[0], target).toFixed(1) + ' km', color: '#92400e', fontWeight: '700', fontSize: '13px'},
        });
      }
    }

    if (picking) {
      let pin = markers[0];
      const place = (lat, lng) => {
        if (!pin) pin = add({lat, lng, label: 'Unit location'}, false);
        pin.setPosition({lat, lng}); setInputs(el, lat, lng);
      };
      map.addListener('click', e => { place(e.latLng.lat(), e.latLng.lng()); });
      if (pin) pin.addListener('dragend', e => setInputs(el, e.latLng.lat(), e.latLng.lng()));
      el.__moveTo = (lat, lng) => { place(lat, lng); map.setCenter({lat, lng}); map.setZoom(17); if (pin && !pin.__bound) { pin.__bound = true; pin.addListener('dragend', e => setInputs(el, e.latLng.lat(), e.latLng.lng())); } };
    }
  }

  async function drawLeaflet(el, points, target, picking) {
    await loadLeaflet();
    const all = points.concat(target ? [target] : []);
    const start = all.length ? [all[0].lat, all[0].lng] : [KENYA_CENTER.lat, KENYA_CENTER.lng];
    const map = L.map(el).setView(start, all.length === 1 ? 16 : 12);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19, attribution: '&copy; OpenStreetMap contributors',
    }).addTo(map);

    const layers = [];
    function add(p, isTarget) {
      const m = L.circleMarker([p.lat, p.lng], {
        radius: isTarget ? 10 : 8, color: isTarget ? '#b45309' : '#0f766e',
        fillColor: isTarget ? '#f59e0b' : '#14b8a6', fillOpacity: 0.85, weight: 2,
      }).addTo(map);
      if (p.label && !picking) {
        const div = document.createElement('div');
        const strong = document.createElement('strong'); strong.textContent = withDistance(p, isTarget ? null : target); div.appendChild(strong);
        if (p.url) { div.appendChild(document.createElement('br')); const a = document.createElement('a'); a.href = p.url; a.textContent = 'Open'; div.appendChild(a); }
        m.bindPopup(div);
      }
      layers.push(m);
      return m;
    }
    points.forEach(p => add(p, false));
    if (target) add(target, true);
    if (all.length > 1) map.fitBounds(all.map(p => [p.lat, p.lng]), {padding: [30, 30]});

    // dashed lines to the workplace, with the distance written on the line
    if (target && !picking) {
      points.slice(0, 40).forEach(p => {
        const line = L.polyline([[p.lat, p.lng], [target.lat, target.lng]],
                                {color: '#f59e0b', weight: 2, dashArray: '6 6'}).addTo(map);
        line.bindTooltip(km(p, target).toFixed(1) + ' km', {permanent: points.length === 1, className: 'km-label'});
      });
    }

    if (picking) {
      let pin = layers[0] || null;
      const place = (lat, lng) => {
        if (pin) pin.setLatLng([lat, lng]); else pin = add({lat, lng, label: 'Unit location'}, false);
        setInputs(el, lat, lng);
      };
      map.on('click', e => place(e.latlng.lat, e.latlng.lng));
      el.__moveTo = (lat, lng) => { place(lat, lng); map.setView([lat, lng], 17); };
    }
    setTimeout(() => map.invalidateSize(), 200);
  }

  async function init(el) {
    const picking = !!el.dataset.pickLat;
    let points = parse(el, 'points') || [];
    const target = parse(el, 'target');
    if (picking) {
      const la = parseFloat(document.querySelector(el.dataset.pickLat).value);
      const ln = parseFloat(document.querySelector(el.dataset.pickLng).value);
      if (!isNaN(la) && !isNaN(ln)) points = [{lat: la, lng: ln, label: 'Unit location'}];
    }
    const which = await engine();
    try {
      if (which === 'google') await drawGoogle(el, points, target, picking);
      else await drawLeaflet(el, points, target, picking);
    } catch (e) {
      el.innerHTML = '<div class="p-3 text-muted small">The map could not be loaded.</div>';
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.ha-map').forEach(init);

    // "Use my current location" buttons fill the GPS fields from the device
    document.querySelectorAll('[data-use-location]').forEach(btn => {
      btn.addEventListener('click', () => {
        const status = document.querySelector(btn.dataset.useLocation);
        if (!navigator.geolocation) { if (status) status.textContent = 'This browser cannot share its location.'; return; }
        if (status) status.textContent = 'Finding your position...';
        navigator.geolocation.getCurrentPosition(pos => {
          const {latitude, longitude, accuracy} = pos.coords;
          const map = document.querySelector('.ha-map[data-pick-lat]');
          if (map && map.__moveTo) map.__moveTo(latitude, longitude);
          else if (map) setInputs(map, latitude, longitude);
          if (status) status.textContent = `Position set (accurate to about ${Math.round(accuracy)} m). Stand inside the building for the best result.`;
        }, err => {
          if (status) status.textContent = 'Could not get your position: ' + err.message;
        }, {enableHighAccuracy: true, timeout: 15000});
      });
    });

    // a place picked in a search box moves the picker map
    document.addEventListener('ta-place', e => {
      const d = e.detail || {};
      const map = document.querySelector('.ha-map[data-pick-lat]');
      if (map && map.__moveTo && d.lat != null && d.lng != null) map.__moveTo(d.lat, d.lng);
      else if (map && d.lat != null) setInputs(map, d.lat, d.lng);
    });
  });
})();
