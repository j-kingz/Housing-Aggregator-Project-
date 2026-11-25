(() => {
  const storageKey = 'housing-accessibility-preferences';
  const scales = ['default', 'large', 'larger'];
  const root = document.documentElement;
  const body = document.body;

  let preferences = { fontScale: 'default', highContrast: false };

  try {
    preferences = {
      ...preferences,
      ...JSON.parse(localStorage.getItem(storageKey) || '{}'),
    };
  } catch (_) {
    // Use default settings if saved data cannot be read.
  }

  function applyPreferences() {
    if (preferences.fontScale === 'default') {
      delete root.dataset.fontScale;
    } else {
      root.dataset.fontScale = preferences.fontScale;
    }

    body.classList.toggle('high-contrast', preferences.highContrast);

    const contrastToggle = document.getElementById('highContrastToggle');
    if (contrastToggle) {
      contrastToggle.checked = preferences.highContrast;
    }
  }

  function savePreferences() {
    try {
      localStorage.setItem(storageKey, JSON.stringify(preferences));
    } catch (_) {
      // The controls still work for the current visit.
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    applyPreferences();

    document.querySelectorAll('[data-font-size]').forEach((button) => {
      button.addEventListener('click', () => {
        const currentIndex = scales.indexOf(preferences.fontScale);

        if (button.dataset.fontSize === 'increase') {
          preferences.fontScale = scales[Math.min(currentIndex + 1, scales.length - 1)];
        } else if (button.dataset.fontSize === 'decrease') {
          preferences.fontScale = scales[Math.max(currentIndex - 1, 0)];
        } else {
          preferences.fontScale = 'default';
        }

        applyPreferences();
        savePreferences();
      });
    });

    document.getElementById('highContrastToggle')?.addEventListener('change', (event) => {
      preferences.highContrast = event.target.checked;
      applyPreferences();
      savePreferences();
    });
  });
})();