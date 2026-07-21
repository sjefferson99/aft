// Registers the PWA service worker. Safe no-op in browsers without
// serviceWorker support (e.g. older Safari) and in plain HTTP dev contexts
// where registration will simply fail silently.
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch((error) => {
      console.debug('Service worker registration failed:', error.message);
    });
  });
}

// iOS reads the home-screen label from apple-mobile-web-app-title at
// "Add to Home Screen" time, not from manifest.webmanifest's name/short_name
// (iOS ignores those). Without this, a configured custom app name would
// apply on Android/desktop but silently keep showing the generic "AFT"
// label on iOS installs - defeating the point of naming an instance to
// distinguish it from other installs on the same device.
(function syncAppleTouchIconTitle() {
  fetch('/api/branding/app-name', { cache: 'no-store' })
    .then((response) => (response.ok ? response.json() : null))
    .then((data) => {
      if (!data || !data.name) {
        return;
      }
      const meta = document.querySelector('meta[name="apple-mobile-web-app-title"]');
      if (meta) {
        meta.setAttribute('content', data.name);
      }
    })
    .catch(() => {
      // Static "AFT" fallback in the HTML stands.
    });
})();
