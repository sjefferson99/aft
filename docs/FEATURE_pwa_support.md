# AFT as an installable PWA

## Context

AFT's frontend (`www/`) is a plain HTML/CSS/JS app with no build step, served by nginx, which also reverse-proxies `/api` and `/socket.io` to the Flask backend on the same origin. Auth is a server-side session cookie, extended via a "Remember me" checkbox at login.

Goal for **v1**: get AFT installable as a basic app (home screen icon, standalone window, no browser chrome) on iOS and Android, with minimal new development, and **without paying for an Apple Developer account**. This replaces the earlier Capacitor PoC (`176-enable-capacitor-support-for-mobile-app-like-experience` branch, see [FEATURE_mobile_app_capacitor.md](FEATURE_mobile_app_capacitor.md) for the superseded plan) — real iOS distribution with Capacitor needs a $99/yr Apple Developer account; a PWA needs no app-store account on either platform to install to a home screen.

**v1 is intentionally thin**: manifest + minimal service worker (just enough to satisfy install criteria) + the remember-me fix below. Biometric unlock, real offline caching, and push notifications were features planned for Capacitor's "Phase 2" — they're carried forward as **Phase 2 here too**, not dropped, and are described at the end of this doc so they're not lost, but are explicitly out of scope for this pass.

Because a PWA is served from the AFT instance's own domain rather than wrapped in a separate native shell, this work lives almost entirely in the existing `www/` tree, not a sibling project — no "which server" URL picker screen is needed the way Capacitor's remote-URL mode required one.

## Prerequisites

- No new local tooling — no Node/npm build step is introduced; a manifest and a service worker are both plain static files nginx already knows how to serve.
- The AFT deployment must be served over **valid HTTPS**. Service worker registration and PWA install criteria refuse to activate on plain HTTP, with the sole exception of `localhost` for local dev.
- Square source icons at 192×192 and 512×512 (plus a maskable variant for Android) — derived from the existing `www/images/AFT_logo_fullsize.png`.

## Project layout

Everything is additive inside the existing static tree:

```
www/
  manifest.webmanifest      # new — app metadata, icons, display mode
  sw.js                      # new — minimal service worker (install-criteria only, no real caching yet)
  icons/                     # new — generated PWA icon sizes (incl. maskable)
```

`www/index.html`, `board.html`, etc. each gain a `<link rel="manifest">` tag and a small inline/deferred `navigator.serviceWorker.register('/sw.js')` call — no bundler needed since these are plain `<script>` tags already.

## Web app manifest

`www/manifest.webmanifest`, linked from every top-level HTML page:

- `name` / `short_name`: "AFT Tasks" / "AFT".
- `start_url`: `/`.
- `display`: `standalone` (falls back to `minimal-ui`/browser automatically if unsupported).
- `theme_color` / `background_color`: pulled from AFT's existing CSS theme variables so OS chrome (status bar, splash background) matches in-app branding.
- `icons`: 192×192 and 512×512 `any`, plus a 512×512 `maskable` variant (extra padding so Android's adaptive-icon mask doesn't clip the logo) — generated once from `www/images/AFT_logo_fullsize.png`.
- `id`: an explicit stable app id (e.g. `/`) so re-installs/updates are recognized as the same app.

**Multi-tenant note carried over from the Capacitor doc:** AFT is self-hosted at many different domains — each deployment's install is inherently scoped to its own origin, which the browser already handles natively for PWAs (no shared "the AFT app" listing to manage, unlike an App Store entry).

## Minimal service worker (install criteria only)

`www/sw.js` — deliberately does the least amount of work needed to make Chrome/Android and iOS treat AFT as installable. Real caching strategy is Phase 2 (see below):

- `install` event: no precaching in v1 — just `self.skipWaiting()`.
- `activate` event: `self.clients.claim()`.
- `fetch` event: present (a registered fetch handler is part of Chrome's install criteria) but a pure pass-through (`event.respondWith(fetch(event.request))`) — no caching behavior yet, so there is zero risk of serving stale API/auth responses in v1.

This satisfies installability on Chrome/Android without taking on any of the cache-invalidation, offline-fallback, or stale-data complexity that comes with a real caching strategy — that work is scoped into Phase 2 below rather than rushed here.

## Install affordance

- Chrome/Edge/Android fire `beforeinstallprompt` — no custom UI is strictly required for v1 (the browser's own install icon in the address bar / menu is enough to ship), but a small "Install app" button on `www/settings.html` is a cheap discoverability win: capture the event, stash it, trigger `.prompt()` on click.
- iOS Safari fires no `beforeinstallprompt` — install is manual only ("Share" → "Add to Home Screen"). A short static instructional note in the same settings section covers this (no functional code needed, just copy).
- `window.matchMedia('(display-mode: standalone)').matches` (or iOS's `navigator.standalone`) detects the running-as-installed-app state, for hiding the "Install app" affordance once already installed and for the remember-me default below.

## Remember-me fix + auto-check in installed app

Investigation turned up an existing bug, unrelated to PWA work but worth fixing alongside it since the installed app is exactly where it matters most:

- `server/auth.py:49` (`SESSION_LIFETIME_HOURS = 24 * 7`) is the value actually wired to `app.py`'s `PERMANENT_SESSION_LIFETIME` — the real cookie lifetime is **7 days**.
- `server/auth.py:50` (`REMEMBER_ME_LIFETIME_DAYS = 30`) is unused dead config, and `www/login.html:33` advertises **"Remember me for 30 days"** against it — a stale label, not a stale cookie. Users are told 30 days but get 7.
- **Fix**: update `login.html`'s label to say "7 days" (matching the actual enforced lifetime), and remove the unused `REMEMBER_ME_LIFETIME_DAYS` constant in `auth.py` so there's only one source of truth for the value. No change to actual session behavior — this aligns the copy to the code that already governs it.
- **Auto-check in installed app**: default the "Remember me" checkbox to checked when `window.matchMedia('(display-mode: standalone)').matches` (or `navigator.standalone` on iOS) is true, in `www/js/login.js` — same reasoning as the Capacitor doc's equivalent change (an installed app implies a personal device where staying logged in for the session's full lifetime is the expected behavior), just gated on PWA standalone-mode detection instead of `window.Capacitor?.isNativePlatform()`. Still overridable — this only sets the initial checkbox state.

## Native polish

- `theme_color` in the manifest plus a `<meta name="theme-color">` tag (kept in sync) handles status-bar/title-bar tinting — declarative, no plugin.
- Splash screen on Android is auto-generated by Chrome from the manifest's `background_color` + icon — no separate splash asset pipeline.
- iOS Safari still wants the older `apple-touch-icon` link tag and `apple-mobile-web-app-*` meta tags for a fully native-feeling launch.

## Build & run loop

- No build/sync step — edit `manifest.webmanifest` / `sw.js` / JS directly, reload. This is the biggest simplification versus Capacitor's `npx cap sync` + platform-IDE loop, and it's why v1 can stay this thin.
- Local HTTPS for testing service worker registration: `localhost` is exempted from the HTTPS requirement, via the existing `docker compose up -d --build` dev loop.
- Installing for test: desktop Chrome/Edge address-bar install icon; Android Chrome menu → "Install app"; iOS Safari Share sheet → "Add to Home Screen".

## Verification

1. Visit a deployment over HTTPS in Chrome/Android — confirm the install affordance appears (browser's own UI and/or AFT's custom button) and installing produces a standalone-window/home-screen app with no browser chrome, no Apple account or app-store step involved.
2. Visit the same deployment in iOS Safari — confirm the custom "Add to Home Screen" instructions appear and manually installing produces a correctly-icon'd, correctly-themed home screen app.
3. Confirm the login page now says "Remember me for 7 days" and that ticking it produces a session cookie that actually lasts 7 days (already true today — this step just confirms the label now matches).
4. Launch the installed app fresh (not previously logged in) — confirm "Remember me" is pre-checked automatically, and can still be unchecked manually.
5. Force-quit and relaunch the installed app after logging in with Remember me checked — confirm it opens directly to a logged-in board.
6. Drag-and-drop a card between columns on a touch device inside the installed app — `www/js/board.js` already has touch handlers, so this should work unchanged; confirm on-device specifically in standalone mode, not just the browser tab, since standalone occasionally surfaces viewport/safe-area differences the browser tab doesn't.
7. Confirm existing non-PWA browser usage is completely unaffected — someone who never installs the app should see zero behavior change.

## Phase 2 (not in this pass — carried forward from Capacitor's deferred scope)

These were the Capacitor plan's "v2"/deferred items. PWA can support all of them better than Capacitor could (no plugin needed for any), but each is a real scope increase over the install-only v1 above, so they stay out of this doc's implementation until explicitly picked up:

- **Real offline caching**: a proper service-worker caching strategy (stale-while-revalidate for static assets, network-first-with-cache-fallback for `/api` GETs, network-only for mutations/`/socket.io`/auth) plus an `offline.html` fallback page. v1's service worker deliberately does none of this yet.
- **Biometric unlock**: WebAuthn platform authenticator (Face ID / Touch ID / Android fingerprint / Windows Hello) as a local re-auth gate on top of the existing session cookie. Needs new `server/` endpoints to store and verify WebAuthn credentials — a new server-side trust boundary, meaning it needs its own review pass rather than folding into general PWA setup.
- **Push notifications**: Web Push would need a service-worker push handler, new server-side subscription storage, and a VAPID key pair — a standalone feature in its own right, not incidental PWA setup. AFT's realtime layer today is Socket.IO over a live connection, which only works while the app is open.
