// Minimal PWA service worker - v1 install-criteria only.
// Deliberately does NOT cache anything yet: no precaching, no runtime
// caching, no offline fallback. A registered fetch handler is required for
// Chrome/Android to consider the app installable, so this is a pure
// pass-through. Real caching strategy is a separate, later phase - see
// docs/FEATURE_pwa_support.md.

self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (event) => {
  event.respondWith(fetch(event.request));
});
