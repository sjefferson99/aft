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
- Board import API at /api/boards/import supports three formats: AFT native JSON, Trello JSON, and CSV (detected by file extension).
- AFT JSON imports do not map assignees across instances (cross-instance ID collisions risk). Trello imports use an explicit member_map. CSV imports resolve assignees by username against active+approved users; unresolved usernames are skipped with a warning.
- CSV import supports two target modes: new_board (creates a new board) and existing_board (requires target_board_id and conflict_strategy: duplicate or overwrite). A preview endpoint at POST /api/boards/import/preview shows impact without writing.
- GET /api/boards/import/csv-template returns a downloadable template CSV; no auth required.
- Notifications are user-scoped: each notification has a user_id, and users can only see/modify their own notifications.
- Internal notification creators (backup, scheduler, housekeeping) create notifications for all admins by default.
- POST /api/notifications supports for_all_users flag (admin only) to broadcast notifications to all users.
- Frontend modal changes should reuse existing modal structure/styles and CSS variables for theme support; avoid hardcoded colors and only use danger styling for destructive actions.
- UI/E2E tests for `www/` live in `ui-tests/` (pytest-playwright, no Node toolchain), separate from `server/tests`: run via `cd ui-tests && pytest -v`. Requires the full docker compose stack up at `http://localhost` and, for login-dependent tests, a fresh database (see `ui-tests/docs/UI_TESTING.md`). Use the `logged_in_page` fixture for authenticated tests rather than reimplementing login.

Security workflow
- Run Snyk Code after modifying first-party code in supported languages.
- If issues are introduced, fix and rescan until no new issues are reported for changed paths.

PR review workflow (agent-assisted)
- **MANDATORY size check before `/code-review` or any multi-agent review flow**: run `git diff --stat` first. A single file or under ~300 changed lines gets ONE sequential pass — never parallel multi-agent fanout. This has already been violated once (a ~200-line single-file diff triggered a 7-subagent fanout producing ~30 overlapping findings; the user had to interrupt it as far too much effort for the size of the change). Parallel fanout is reserved for genuinely large/multi-file/high-risk diffs, and even then default to sequential unless the user asks for more.
- Reproduce findings before reporting them: don't just read the diff, actually exercise the changed code (e.g. run the validator against a crafted input) and compare behaviour against the pre-change version to confirm a regression is real, not theoretical.
- Post findings as PR comments (a summary comment plus inline comments anchored to the relevant lines) and stop — wait for explicit go-ahead before committing any fix, even when the fix seems obvious.
- **MANDATORY before every `gh pr comment` / `gh api .../comments` call**: the comment `body`'s FIRST LINE must be `> **⚠️ AI-generated comment, posted on behalf of @<username> — not written by them personally.**`, followed by a blank line, then the content. A trailing "🤖 Generated with Claude Code" footer at the bottom is NOT sufficient — this has already been tried and judged insufficient once (two PR #534 comments posted with only a bottom footer; the account owner had to point out the comments read as if written by them personally). Before sending, re-read the actual `body` string and confirm the disclaimer is literally line 1 — this is a mechanical check to perform every time, not a judgment call to skip when a comment feels short/routine. If a comment was already posted without it, edit it in place immediately (`gh api repos/{owner}/{repo}/issues/comments/{id} -X PATCH --input <jsonfile>` — plain `-f body=@path` silently fails on Windows/Git-Bash and posts the literal string; build the JSON with Python's `json.dump` and pass via `--input`, then verify with a follow-up GET).
- After a fix is approved and applied, re-verify with the same reproduction used to find the bug, then let the human decide about resolving/closing review threads.
- **MANDATORY relevance check before "just to be safe" test re-runs**: after applying a fix, name which files actually changed before running any test suite. A JS-only change does not need a full backend pytest re-run "for extra confidence" — this has already been violated once (an unprompted full backend suite re-run for a frontend-only fix spiralled into two colliding concurrent runs against the same dev DB, producing spurious failures, plus 20+ minutes of silently polling a stalled process before the user had to ask what was happening). Run only the narrowest subset that exercises the changed code path. Never start a second run of the same suite while one is still in flight against the same shared dev DB. If a background process runs past ~1.5x its own typical runtime with no output, check logs for evidence of real progress or surface the delay to the user — don't keep silently rescheduling wakeups.

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
