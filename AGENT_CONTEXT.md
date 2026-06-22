# Agent Context (Portable)

Purpose
- Keep high-signal repo facts that should be available to any Copilot agent on any machine.
- Prefer stable conventions and known pitfalls over temporary task chatter.

How to use
- Read this file at the start of security or testing work.
- Update only when behaviour or workflow changes.
- Keep entries short and factual.

Critical workflow reminders
- **ALWAYS review CONTRIBUTING.md before implementing changes**:  
  - Check coding standards for formatting and naming conventions  
  - Ensure API tests follow API-only patterns (no direct DB access)  
  - Review security guidelines (input validation, length limits, no error leaking)  
  - Update README/docs if behaviour changed  
  - Create or update tests for all API changes  
  - Run pytest to verify all tests pass

Current high-value context
- Notification rendering in www/js/notifications.js uses DOM node construction for list rendering to reduce DOM-XSS risk from template-string HTML assembly.
- Notification action URLs are validated server-side by validate_safe_url in server/app.py and include protocol restrictions plus unsafe-character checks.
- Focused notification URL security tests live in server/tests/test_api_notifications.py.
- Integration pytest calls in server/tests hit the running Docker stack.
- For local development/testing, ALWAYS use compose.yml and ALWAYS include --build so code changes are reflected:
  - Start/rebuild: docker compose up -d --build
  - Stop: docker compose down
  - Reset DB data dir: docker compose down; remove ./data contents; docker compose up -d --build
- Use compose.example.yml as the GHCR deployment template.
- Board import API at /api/boards/import enforces JSON size caps, strict format/schema validation, and relationship integrity checks before writes.
- Imported card assignees are intentionally not mapped by user id across instances; imported cards are created by the importing user and left unassigned.
- Notifications are user-scoped: each notification has a user_id, and users can only see/modify their own notifications.
- Internal notification creators (backup, scheduler, housekeeping) create notifications for all admins by default.
- POST /api/notifications supports for_all_users flag (admin only) to broadcast notifications to all users.
- Frontend modal changes should reuse existing modal structure/styles and CSS variables for theme support; avoid hardcoded colors and only use danger styling for destructive actions.
- UI/E2E tests for `www/` live in `ui-tests/` (pytest-playwright, no Node toolchain), separate from `server/tests`: run via `cd ui-tests && pytest -v`. Requires the full docker compose stack up at `http://localhost` and, for login-dependent tests, a fresh database (see `ui-tests/docs/UI_TESTING.md`). Use the `logged_in_page` fixture for authenticated tests rather than reimplementing login.

Security workflow
- Run Snyk Code after modifying first-party code in supported languages.
- If issues are introduced, fix and rescan until no new issues are reported for changed paths.

Useful commands
- Rebuild dev stack: docker compose down; docker compose up -d --build
- Quick dev command reference:
  - Start/rebuild dev stack: docker compose up -d --build
  - Stop dev stack: docker compose down
  - Restart a clean DB: docker compose down; remove ./data contents; docker compose up -d --build
  - Show service status: docker compose ps
  - Follow logs: docker compose logs -f server nginx db redis
  - Rebuild a single service: docker compose up -d --build server
  - Run backend tests: cd server && ..\\.venv\\Scripts\\python.exe -m pytest -v
  - Run UI/E2E tests: cd ui-tests && pytest -v (one-time setup: pip install -r requirements-dev.txt && playwright install chromium)
- Focused notification tests:
  - from server/: ..\\.venv\\Scripts\\python.exe -m pytest tests/test_api_notifications.py -k "attribute_breakout or relative_url or https_url or javascript_protocol" -q
- Focused Snyk scan:
  - path: c:\\git\\aft\\www\\js\\notifications.js

What does not belong here
- Secrets, credentials, tokens, or environment-specific private data.
- One-off debugging notes that will be stale next week.
