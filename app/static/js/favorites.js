/* The heart button: save or un-save a home without leaving the page. */
(function () {
  'use strict';
  document.addEventListener('click', async function (event) {
    const button = event.target.closest('.heart-btn');
    if (!button) return;
    event.preventDefault();
    event.stopPropagation();

    // not signed in: go and sign in first
    if (!document.body.dataset.signedIn) {
      window.location.href = '/login';
      return;
    }
    const meta = document.querySelector('meta[name="csrf-token"]');
    try {
      const response = await fetch('/favorites/' + button.dataset.listing + '/toggle', {
        method: 'POST',
        headers: {'Accept': 'application/json', 'X-CSRFToken': meta ? meta.content : ''},
      });
      const data = await response.json();
      document.querySelectorAll('.heart-btn[data-listing="' + button.dataset.listing + '"]').forEach(function (b) {
        b.classList.toggle('saved', data.saved);
        b.setAttribute('aria-pressed', data.saved ? 'true' : 'false');
        b.querySelector('i').className = data.saved ? 'bi bi-heart-fill' : 'bi bi-heart';
        b.title = data.saved ? 'Remove from saved homes' : 'Save this home';
      });
      const badge = document.getElementById('favoriteCount');
      if (badge) { badge.textContent = data.count; badge.hidden = data.count === 0; }
    } catch (e) { /* leave the heart as it was */ }
  });
})();
