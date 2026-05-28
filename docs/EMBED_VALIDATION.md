# Public Board Embed Validation

Use this checklist after changing embed-related settings.

## Prerequisites

- Public board exists and is set to Public in AFT.
- `.env` has the origins you want to allow in `EMBED_ALLOWED_ORIGINS`.
- Stack is restarted so nginx regenerates runtime header config:

```powershell
docker compose up -d --build nginx
```

## Quick Automated Check (PowerShell)

Run the helper script:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check-embed-policy.ps1 -BaseUrl https://localhost -ExpectedAllowedOrigins https://partner-a.example
```

What it checks:

- `/public-board.html` includes CSP with `frame-ancestors`.
- `/public-board.html` omits `X-Frame-Options`.
- expected allowlisted origins appear in the `frame-ancestors` directive.
- `/board.html` still has `X-Frame-Options: SAMEORIGIN`.

## Manual Browser Validation

1. Allowed host test:
- Open an allowed partner page that contains the generated iframe snippet.
- Confirm board renders and card details open.

2. Blocked host test:
- Open the same iframe snippet from a non-allowlisted host origin.
- Confirm browser blocks frame render (console should report frame policy violation).

3. Direct-link test:
- Open AFT public URL directly (`/public-board.html?slug=...`).
- Confirm board still works outside iframe.

4. Private page protection test:
- Attempt to frame `/board.html` from external site.
- Confirm frame is blocked due to SAMEORIGIN protection.

## Common Failure Patterns

- "Refused to frame": origin missing from `EMBED_ALLOWED_ORIGINS` or nginx not restarted.
- Wrong host mismatch: http vs https, hostname vs subdomain, or missing port.
- Parent page adds strict iframe sandbox flags that block required behavior.

## Related Config

- `EMBED_ALLOWED_ORIGINS` controls iframe embedding allowlist.
- `CORS_ALLOWED_ORIGINS` controls parent-site direct API/WebSocket access.
