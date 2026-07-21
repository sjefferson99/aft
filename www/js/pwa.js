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
