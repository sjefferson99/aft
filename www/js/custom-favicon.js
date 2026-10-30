// Applies the instance's custom logo as the favicon on pages that don't load
// header.js (login, setup, register, logout). Any failure leaves the default
// favicon from the HTML in place.
(function applyCustomFavicon() {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 5000);

  fetch('/api/branding/logo', { signal: controller.signal, cache: 'no-store' })
    .then((response) => (response.ok ? response.json() : null))
    .then((data) => {
      const filename = typeof data?.filename === 'string' ? data.filename.trim() : '';
      if (!filename) {
        return;
      }

      const faviconPath = `/images/backgrounds/logos/${encodeURIComponent(filename)}`;
      document.querySelectorAll('link[rel="icon"]').forEach((faviconLink) => {
        faviconLink.href = faviconPath;
        faviconLink.removeAttribute('type');
      });
    })
    .catch((error) => {
      if (error.name !== 'AbortError') {
        console.warn('Failed to load custom favicon:', error);
      }
    })
    .finally(() => clearTimeout(timeoutId));
})();
