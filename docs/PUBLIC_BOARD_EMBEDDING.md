# Public Board Embedding Plan

This document captures the initial implementation plan for safely embedding AFT public boards on external websites.

## Goals

- Allow embedding of AFT public boards in `iframe` elements on trusted partner sites.
- Keep default clickjacking protections for all non-public pages.
- Add a UI action to generate and copy ready-to-use embed HTML.
- Keep cross-origin API access locked down unless explicitly allowed.

## Current State (as implemented today)

- Public board URL format already exists:
  - `/public-board.html?slug=<slug>`
- Public board data is served by read-only public API endpoints.
- Public route hardening already exists (throttling and no-cache/noindex behavior).
- Nginx currently blocks framing globally with:
  - `X-Frame-Options: SAMEORIGIN`
- CORS is controlled by `CORS_ALLOWED_ORIGINS` in `.env` for HTTP/HTTPS/WebSocket cross-origin requests.

## Important Security Model

There are two different controls:

1. Frame policy (clickjacking protection)
- Controls who can embed AFT pages in an `iframe`.
- This is set via response headers (`Content-Security-Policy: frame-ancestors ...` and legacy `X-Frame-Options`).

2. CORS policy
- Controls which external web origins can call AFT APIs via browser JavaScript.
- This is independent from whether an `iframe` can display AFT pages.

## Required Changes

### 1) Add an embed allowlist env variable

Add to `.env.example`:

- `EMBED_ALLOWED_ORIGINS=`

Example:

- `EMBED_ALLOWED_ORIGINS=https://partner-a.example,https://portal.partner-b.example`

Rules:

- Exact origins only (scheme + host [+ port]).
- No wildcard `*` in production.
- Keep list as small as possible.

### 2) Make nginx read env and generate runtime config

Current `server/nginx.conf` is static. To support origin allowlists from `.env`:

- Convert nginx config to a template (`server/nginx.conf.template`) with placeholders.
- Update `server/entrypoint.sh` to run env substitution before starting nginx.
- Keep safe defaults if env var is empty (do not allow external framing).

### 3) Allow framing only for public board page

For `public-board.html` responses:

- Use CSP `frame-ancestors` with allowlisted origins.
- Keep strict anti-framing behavior on all authenticated/internal pages.

Notes:

- Prefer CSP `frame-ancestors` as the modern control.
- Keep `X-Frame-Options` as a legacy fallback where practical, but do not rely on it for per-origin allowlists.

### 4) Keep CORS separate and minimal

- Continue using `CORS_ALLOWED_ORIGINS` for API/WebSocket browser access.
- Do not broaden CORS unless parent sites must call APIs directly.

### 5) Add "Copy Embed Code" UI action

Add a board-settings action (desktop + mobile) next to existing public-link actions:

- Show only when board is public and has a slug.
- Generate an `iframe` snippet targeting the board public URL.
- Copy snippet to clipboard and show toast.
- Include a hint if embedding fails: update `EMBED_ALLOWED_ORIGINS` and redeploy nginx.

Suggested snippet:

```html
<iframe
  src="https://your-aft-domain/public-board.html?slug=your-slug"
  title="AFT Public Board"
  width="100%"
  height="900"
  style="border:0;"
  loading="lazy"
  referrerpolicy="strict-origin-when-cross-origin">
</iframe>
```

Host page notes:

- If host adds strict iframe `sandbox`, it may break board functionality unless the required permissions are present.
- Start without sandbox restrictions unless a partner has strict policy requirements, then test explicitly.

## CORS Clarification (FAQ)

Question:

- If CORS is not configured for a partner site, will users inside the embedded public board fail when opening cards?

Answer:

- In the normal iframe model, opening cards inside the embedded board still works.
- Reason: the AFT page inside the iframe calls AFT APIs from the same origin as itself.
- CORS is mainly relevant when JavaScript running on the parent site (outside the iframe) tries to call AFT APIs directly.
- In that parent-site-direct-call scenario, missing origin in `CORS_ALLOWED_ORIGINS` will cause browser CORS failures.

## Rollout Checklist

1. Add and document `EMBED_ALLOWED_ORIGINS` in `.env.example` and README.
2. Add nginx template + entrypoint substitution for runtime env-driven frame policy.
3. Apply route-specific frame policy for public board page only.
4. Add "Copy Embed Code" action in header settings (desktop + mobile).
5. Add copy-to-clipboard embed HTML generation and user toast messages.
6. Validate manually on:
   - allowed origin host page (works)
   - disallowed origin host page (blocked)
   - direct public URL navigation (still works)
   - authenticated/private pages in iframe (still blocked)

## Operational Notes

- Rotating a public link should invalidate old embed URLs immediately.
- Public board URL should be treated as a bearer link.
- Keep throttling and no-store/noindex headers in place for public endpoints.

## Future Enhancements (optional)

- Add `postMessage` support for dynamic iframe height and host/iframe communication.
- Add per-board allowed embed origins if finer-grained policy is needed.
- Add analytics/audit events for embed-code generation and public-link use.
