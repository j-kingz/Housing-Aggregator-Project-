/*
 * Type-ahead for location boxes, so nobody has to type a place perfectly.
 *
 * Put data-suggest="area" (neighbourhoods only) or data-suggest="place"
 * (neighbourhoods + buildings) on a text input.
 *
 *   data-require-match   the text must end up as a real suggestion. A near miss
 *                        ("westlnds") is corrected to the closest place; text
 *                        nothing resembles is cleared.
 *   data-google          also show Google Maps place suggestions (needs the key)
 *   data-lat / data-lng  selectors of hidden inputs to fill with the GPS point
 *   data-area-id         selector of a hidden input to fill with the area id
 *   data-county-field    selector of a hidden input to fill with the county of the
 *                        picked place. On that input, data-display points at a
 *                        read-only box that shows it, and data-counties lists the
 *                        county names used to read the county from an address.
 *   data-county-from     selector of a text box whose picked county limits these suggestions
 */
(function () {
  'use strict';

  const ICONS = {county: 'bi-map', area: 'bi-geo-alt', building: 'bi-building', place: 'bi-pin-map', google: 'bi-pin-map'};
  const GROUPS = {county: 'Counties', area: 'Neighbourhoods', building: 'Buildings', place: 'Places in Kenya', google: 'Places in Kenya'};

  function debounce(fn, ms) {
    let t;
    return function () {
      const args = arguments;
      clearTimeout(t);
      t = setTimeout(() => fn.apply(null, args), ms);
    };
  }

  function googleReady() {
    return window.HA_GOOGLE_READY === true && window.google && google.maps && google.maps.importLibrary;
  }

  class Typeahead {
    constructor(input) {
      this.input = input;
      this.kind = input.dataset.suggest || 'place';
      this.require = input.hasAttribute('data-require-match');
      this.useGoogle = input.hasAttribute('data-google');
      this.latField = input.dataset.lat ? document.querySelector(input.dataset.lat) : null;
      this.lngField = input.dataset.lng ? document.querySelector(input.dataset.lng) : null;
      this.idField = input.dataset.areaId ? document.querySelector(input.dataset.areaId) : null;
      this.countyField = input.dataset.countyField ? document.querySelector(input.dataset.countyField) : null;
      this.countyFrom = input.dataset.countyFrom ? document.querySelector(input.dataset.countyFrom) : null;
      // data-county-any: fill the county for every kind of place (buildings, map
      // places), not only for counties and neighbourhoods
      this.countyAny = input.hasAttribute('data-county-any');
      this.items = [];
      this.active = -1;
      this.chosen = input.value.trim() !== '';   // a value that came from the server is already valid
      this.pending = null;
      this.token = 0;

      const host = input.closest('.input-group') || input.parentElement;
      host.classList.add('position-relative');
      this.menu = document.createElement('div');
      this.menu.className = 'ta-menu list-group shadow-sm';
      this.menu.hidden = true;
      host.appendChild(this.menu);

      this.hint = document.createElement('div');
      this.hint.className = 'form-text ta-hint';
      this.hint.hidden = true;
      (host.nextElementSibling && host.nextElementSibling.classList.contains('form-text')
        ? host.nextElementSibling : host).insertAdjacentElement('afterend', this.hint);

      input.setAttribute('autocomplete', 'off');
      input.setAttribute('role', 'combobox');
      input.setAttribute('aria-autocomplete', 'list');

      input.addEventListener('input', () => this.onType());
      input.addEventListener('focus', () => this.onType());
      input.addEventListener('keydown', e => this.onKey(e));
      input.addEventListener('blur', () => setTimeout(() => this.settle(), 160));
      this.menu.addEventListener('mousedown', e => {
        const row = e.target.closest('[data-index]');
        if (row) { e.preventDefault(); this.pick(this.items[Number(row.dataset.index)]); }
      });

      const form = input.form;
      if (form && !form.dataset.taBound) {
        form.dataset.taBound = '1';
        form.addEventListener('submit', e => {
          const waiting = form.__taWaiting || [];
          if (waiting.some(t => t.needsSettling())) {
            e.preventDefault();
            Promise.all(waiting.map(t => t.settle())).then(() => form.submit());
          }
        });
      }
      if (form) { (form.__taWaiting = form.__taWaiting || []).push(this); }

      this.onType = debounce(this.onType.bind(this), 160);
    }

    needsSettling() {
      return this.require && this.input.value.trim() !== '' && !this.chosen;
    }

    setPoint(lat, lng, areaId) {
      if (this.latField) this.latField.value = lat != null ? lat : '';
      if (this.lngField) this.lngField.value = lng != null ? lng : '';
      if (this.idField) this.idField.value = areaId != null ? areaId : '';
      this.input.dispatchEvent(new CustomEvent('ta-point', {bubbles: true, detail: {lat, lng, areaId}}));
    }

    /* Fill the county field (and the box that shows it); '' clears both. */
    setCounty(name) {
      if (!this.countyField) return;
      this.countyField.value = name || '';
      const display = this.countyField.dataset.display
        ? document.querySelector(this.countyField.dataset.display) : null;
      if (display) display.value = name ? `${name} County` : '';
    }

    countyNames() {
      const field = this.countyField;
      if (!field) return [];
      if (field.options) return Array.from(field.options).map(o => o.value).filter(Boolean);
      try { return JSON.parse(field.dataset.counties || '[]'); } catch (e) { return []; }
    }

    /* The county named in an address: "Westlands, Nairobi, Kenya" -> Nairobi. */
    selectCountyFromText(text) {
      if (!this.countyField || !text) return;
      const key = s => ` ${String(s).toLowerCase().replace(/[-,]/g, ' ').replace(/\s+/g, ' ').trim()} `;
      const haystack = key(text);
      // whole words only. Addresses run from the street to the county, so the
      // county named furthest right wins ("Kiambu Rd, Nairobi" is in Nairobi);
      // on a tie the longer name wins.
      let found = '', at = -1;
      this.countyNames().forEach(name => {
        const i = haystack.lastIndexOf(key(name));
        if (i > at || (i === at && i >= 0 && name.length > found.length)) { found = name; at = i; }
      });
      this.setCounty(found);
    }

    showHint(text) {
      this.hint.textContent = text || '';
      this.hint.hidden = !text;
    }

    async fetchLocal(q) {
      try {
        let url = `/api/suggest?kind=${encodeURIComponent(this.kind)}&q=${encodeURIComponent(q)}`;
        const county = this.countyFrom && this.countyFrom.dataset.county;
        if (county) url += `&county=${encodeURIComponent(county)}`;
        if (this.useGoogle && googleReady()) url += '&ext=0';
        const r = await fetch(url, {headers: {'Accept': 'application/json'}});
        const d = await r.json();
        return d.items || [];
      } catch (e) { return []; }
    }

    async fetchGoogle(q) {
      if (!this.useGoogle || !googleReady() || q.length < 3) return [];
      try {
        const lib = await google.maps.importLibrary('places');
        this.session = this.session || new lib.AutocompleteSessionToken();
        const res = await lib.AutocompleteSuggestion.fetchAutocompleteSuggestions({
          input: q, sessionToken: this.session, includedRegionCodes: ['ke'],
        });
        return (res.suggestions || []).slice(0, 5).map(s => ({
          label: s.placePrediction.mainText ? s.placePrediction.mainText.toString() : s.placePrediction.text.toString(),
          detail: s.placePrediction.secondaryText ? s.placePrediction.secondaryText.toString() : 'Google Maps',
          type: 'google',
          prediction: s.placePrediction,
        }));
      } catch (e) { return []; }
    }

    async onType() {
      const q = this.input.value.trim();
      this.chosen = false;
      if (this.kind === 'place') this.setPoint(null, null, null);
      this.input.dataset.county = '';
      this.setCounty('');                        // new text: the county is not known yet
      const mine = ++this.token;
      const [local, google] = await Promise.all([this.fetchLocal(q), this.fetchGoogle(q)]);
      if (mine !== this.token) return;           // a newer keystroke is already being handled
      this.items = local.concat(google);
      this.active = -1;
      this.render();
      if (q === '') this.showHint('');
    }

    render() {
      const q = this.input.value.trim();
      if (!this.items.length) {
        this.menu.innerHTML = q
          ? '<div class="list-group-item small text-muted">No place like that yet. Check the spelling.</div>'
          : '';
        this.menu.hidden = !q;
        return;
      }
      let lastGroup = '';
      let html = '';
      this.items.forEach((it, i) => {
        const group = GROUPS[it.type] || '';
        if (group && group !== lastGroup) {
          html += `<div class="ta-group">${group}</div>`;
          lastGroup = group;
        }
        html += `
        <button type="button" class="list-group-item list-group-item-action ta-item ${i === this.active ? 'active' : ''}" data-index="${i}">
          <i class="bi ${ICONS[it.type] || ICONS.area} me-2"></i>
          <span class="fw-medium">${this.escape(it.label)}</span>
          <span class="small ta-detail">${this.escape(it.detail || '')}</span>
        </button>`;
      });
      if (this.items.some(it => it.type === 'place')) {
        html += '<div class="ta-credit">Places from OpenStreetMap contributors</div>';
      }
      this.menu.innerHTML = html;
      this.menu.hidden = false;
    }

    escape(s) {
      return String(s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
    }

    onKey(e) {
      if (this.menu.hidden && e.key !== 'ArrowDown') return;
      if (e.key === 'ArrowDown') { e.preventDefault(); this.active = Math.min(this.active + 1, this.items.length - 1); this.render(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); this.active = Math.max(this.active - 1, 0); this.render(); }
      else if (e.key === 'Enter' && this.active >= 0) { e.preventDefault(); this.pick(this.items[this.active]); }
      else if (e.key === 'Escape') { this.menu.hidden = true; }
    }

    async pick(item) {
      if (!item) return;
      this.menu.hidden = true;
      this.input.value = item.type === 'county' ? item.label : (item.value || item.label);
      this.chosen = true;
      this.showHint('');
      if (item.prediction) {                       // a Google place: ask for its GPS point
        try {
          const place = item.prediction.toPlace();
          await place.fetchFields({fields: ['location', 'displayName', 'formattedAddress']});
          this.input.value = place.displayName || item.label;
          if (place.location) this.setPoint(place.location.lat(), place.location.lng(), null);
          if (this.countyAny) this.selectCountyFromText(place.formattedAddress || item.label);
          this.session = null;
          this.input.dispatchEvent(new CustomEvent('ta-place', {bubbles: true, detail: {
            name: place.displayName, address: place.formattedAddress,
            lat: place.location && place.location.lat(), lng: place.location && place.location.lng()}}));
        } catch (e) { /* the text is still usable */ }
      } else if (item.type === 'county') {
        // a whole county: search by county, not by a circle around its town
        this.input.dataset.county = item.county;
        this.setCounty(item.county);
        this.setPoint(null, null, null);
        this.input.dispatchEvent(new CustomEvent('ta-place', {bubbles: true, detail: item}));
      } else {
        // neighbourhoods, buildings and map places carry their county when it is known
        if (item.county && (this.countyAny || item.type === 'area')) this.setCounty(item.county);
        else if (this.countyAny) this.selectCountyFromText(`${item.label}, ${item.detail || ''}`);
        this.setPoint(item.lat, item.lng, item.area_id);
        this.input.dispatchEvent(new CustomEvent('ta-place', {bubbles: true, detail: item}));
      }
    }

    /* Decide what to do with text that was typed but never picked. */
    async settle() {
      this.menu.hidden = true;
      const text = this.input.value.trim();
      if (!text || this.chosen) return;
      const items = (await this.fetchLocal(text)).filter(i => i.type !== 'google');
      const exact = items.find(i => i.label.toLowerCase() === text.toLowerCase());
      if (exact) { await this.pick(exact); return; }
      if (this.require) {
        if (items.length) {
          await this.pick(items[0]);
          this.showHint(`"${text}" was not a known place. Using "${items[0].label}" instead.`);
        } else {
          this.input.value = '';
          this.setPoint(null, null, null);
          this.showHint(`We don't know "${text}". Start typing and pick a place from the list.`);
        }
      } else if (!items.length) {
        this.showHint('No exact match. We will search for this text.');
      }
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('input[data-suggest]').forEach(el => new Typeahead(el));
  });
})();
