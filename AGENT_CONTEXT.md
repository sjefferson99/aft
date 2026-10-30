# Agent Context

Shared guidance for any AI coding agent working in this repo (Claude, Copilot,
etc.). Tool-specific entry points such as CLAUDE.md point here. Keep entries
short, factual and durable. Update this file when behaviour or workflow
changes, not for one-off task notes.

## Sub-agents

Never use sub-agents, for any task, including code review, research or searching. Do all the work yourself in the main session.

## Before making changes

Read CONTRIBUTING.md before implementing anything. It covers:
- Coding standards: formatting and naming.
- API test conventions: tests go through the API only, with no direct DB access.
- Security expectations: validate input, enforce length limits, and never leak internal error details to clients.

Also:
- Add or update tests for every API change.
- Update README/docs when user-visible behaviour changes.

## Environment

- There are three development machines: St Austell (primary, Windows), a MacBook (often used) and Wychwood (occasionally used, Windows). Each has its own `.venv`, `.env` and dev database, so after pulling dependency or config changes, check they are up to date on the machine you're on.
- Commands below use Windows paths. The repo venv is `.venv`, so use `.venv\Scripts\python.exe` (or `../.venv/Scripts/python.exe` from Git Bash). On the MacBook use `.venv/bin/python`.
- To test passkeys locally, set `WEBAUTHN_RP_ID=localhost` and `WEBAUTHN_ORIGINS=http://localhost,https://localhost` in `.env`. Browsers exempt localhost, so no certificate or domain is needed. Without them the passkey tests skip.
- Use `compose.yml` for local development and testing, and always pass `--build` so code changes reach the containers. `compose.example.yml` is the GHCR deployment template; don't use it locally.
- `compose.yml` bind-mounts `./www` into nginx, so frontend edits are live without a rebuild. To reproduce a frontend bug, undo the fix first: a rebuild doesn't bring back the old code.
- `./data` is the MySQL data directory, mounted into the `db` container and gitignored. Clearing it resets the database.

## Common commands

| Task | Command |
|---|---|
| Start / rebuild stack | `docker compose up -d --build` |
| Stop stack | `docker compose down` |
| Reset to a clean DB | `docker compose down`, confirm it stopped, delete `./data` contents, then `docker compose up -d --build` |
| Rebuild one service | `docker compose up -d --build server` |
| Service status | `docker compose ps` |
| Follow logs | `docker compose logs -f server nginx db redis` |
| Backend tests | from `server/`: `..\.venv\Scripts\python.exe -m pytest -q` |
| Backend tests, skipping slow ones | from `server/`: `..\.venv\Scripts\python.exe -m pytest -q -m "not slow"` |
| UI/E2E tests | from `ui-tests/`: `..\.venv\Scripts\python.exe -m pytest -q` |
| UI test one-time setup | `pip install -r ui-tests/requirements-dev.txt` then `playwright install chromium` |

Only delete `./data` after `docker compose down` has succeeded. Removing files under a running MySQL instance corrupts the database.

## Testing

- `server/tests` are integration tests. They hit the running Docker stack, so the stack must be up and rebuilt with current code. The full suite takes about 20 minutes (~900 tests).
- Tests marked `slow` (`@pytest.mark.slow`) wait on real scheduler cycles. They are currently the backup-notification tests in `test_backup_notifications.py`.
- The default backend run is `-m "not slow"`. Only run the full backend suite, slow tests included, after changes to backups, notifications or the schedulers, before a release, or when the user asks. Say in the PR when the slow tests were skipped.
- `ui-tests/` holds Playwright tests for `www/` (pytest-playwright, no Node toolchain). They need the stack at `http://localhost`. Login-dependent tests need a fresh database; see `ui-tests/docs/UI_TESTING.md`. Use the `logged_in_page` fixture for authenticated tests rather than reimplementing login.
- Both suites share one dev database. Never run two suites, or two runs of the same suite, at the same time: they interfere with each other and produce spurious failures.
- Match test scope to what changed. A frontend-only (JS/CSS/HTML) change doesn't need a backend pytest run. Run the narrowest subset that exercises the changed code. When backend code or dependencies change, or before merging, run the whole backend suite with `-m "not slow"` (see above) and the UI suite.
- Many unexpected failures come from a dirty database. Before you debug a failure, reset to a clean DB and re-run.
- Long runs should go in the background. If a run goes well past its usual duration with no new output, check the container logs. If it has stalled, tell the user rather than waiting silently.

## Security

- Run a Snyk Code scan on new or modified first-party code. If it reports issues in the changed code, fix them and rescan until it reports none.

## Feature notes

Non-obvious behaviour that is easy to break:

- **Notifications**
  - Notifications are user-scoped. Each has a `user_id`, and users can only see or modify their own.
  - Internal creators (backup, scheduler, housekeeping) notify all admins by default.
  - `POST /api/notifications` accepts `for_all_users` (admin only) to broadcast to every user.
  - `www/js/notifications.js` renders lists by building DOM nodes rather than template-string HTML, to avoid DOM-XSS. Keep it that way.
  - Action URLs are validated server-side by `validate_safe_url` in `server/app.py` (protocol allow-list plus unsafe-character checks). Focused tests are in `server/tests/test_api_notifications.py`.
- **Board import** (`POST /api/boards/import`)
  - Accepts three formats, detected by file extension: AFT native JSON, Trello JSON and CSV.
  - AFT JSON does not map assignees, because user IDs collide across instances.
  - Trello imports use an explicit `member_map`.
  - CSV resolves assignees by username against active, approved users. Unresolved usernames are skipped with a warning.
  - CSV has two target modes. `new_board` creates a new board. `existing_board` requires `target_board_id` and a `conflict_strategy` of `duplicate` or `overwrite`.
  - `POST /api/boards/import/preview` shows the impact without writing anything.
  - `GET /api/boards/import/csv-template` returns a template CSV and needs no auth.
- **MySQL memory tuning**: the `db` service's `command:` list sets MySQL options from `MYSQL_*` env vars with small-install defaults (see README "Database memory tuning"). Keep `compose.yml`, `compose.example.yml`, `.env.example` and the README table in sync when adding or changing one. `max_connections` must stay above 15 × gunicorn workers (SQLAlchemy pool 5 + overflow 10) plus backup/restore headroom.
- **Gunicorn workers/threads**: `server/gunicorn.conf.py` reads `GUNICORN_WORKERS` (default 1) and `GUNICORN_THREADS` (default 32), validated in `server/gunicorn_settings.py` (unit tests in `server/tests/test_gunicorn_settings.py`). Every open Socket.IO WebSocket holds a gthread thread for its lifetime, so a low thread count starves the whole app: 1 × 8 hung with 7 open tabs. Don't lower the default thread count without re-measuring. Keep the multi-worker safety mechanisms (Redis Socket.IO queue, scheduler locks) intact.
- **Passkeys (WebAuthn)**
  - Off unless `WEBAUTHN_RP_ID` is set. `server/webauthn_settings.py` validates the settings at startup (unit tests in `server/tests/test_webauthn_settings.py`). Routes are in `server/passkey_routes.py`.
  - Passkeys are an alternative sign-in alongside the password, not a second factor. Accounts always keep a password.
  - Challenges are stored in Redis, keyed by the challenge itself (read back from `clientDataJSON` on verify). They are single use (GETDEL) and bound to the browser session by a `webauthn_binding` id. Keying by challenge lets several ceremonies run at once in one session (two tabs, or autofill plus the sign-in button). Don't move them into the Flask session: with cookie sessions an old cookie could replay a challenge.
  - Binary WebAuthn values are stored as base64url text in `ascii_bin` columns, so backups stay plain text and lookups stay case-sensitive.
  - A passkey sign-in stores `passkey_id` in the session. `_resolve_session_user` ends that session when the passkey is removed.
  - API tests use the software authenticator in `server/tests/soft_authenticator.py`. They need `WEBAUTHN_RP_ID=localhost` and `WEBAUTHN_ORIGINS=http://localhost,https://localhost` in `.env`, or they skip. UI tests (`ui-tests/tests/test_passkeys.py`) use Chromium's virtual authenticator and need the same settings.
  - Frontend: `www/js/passkeys.js` does the base64url conversion around `navigator.credentials`. The login page starts one autofill (conditional) request on load and never restarts it after it rejects: some browsers reject at once when there is nothing to offer, which caused a request loop. Only the button flow restarts it.
- **Sign-in rate limits** (`server/auth_rate_limit.py`)
  - Any new code that calls `verify_password` must check `password_block_seconds` first and call `record_password_failure` on a wrong password, so every password check shares one per-account budget. Blocked attempts must not verify the password.
  - Use `get_client_ip()` for the client's address. `request.remote_addr` is always nginx, so limits keyed on it are shared by every client. `get_client_ip()` reads `X-Forwarded-For` from the right using `TRUSTED_PROXY_HOPS`, so clients can't spoof it.
  - `compose.yml` raises the per-IP limits because both test suites share one IP. They are covered by unit tests in `server/tests/test_auth_rate_limit.py`. Per-account limits stay at their defaults, so tests that expect failed logins should use their own account. Ten failures in 15 minutes on `test-admin` would block the suite.
- **Agile archive**: agile cards have both Done and Archive. The done filter applies to the task and done views only. The Archived View lists done and not-done cards together, so requests from it must not narrow by `done`.
- **401 responses on logged-in pages**: the global fetch wrapper in `www/js/utils.js` treats any 401 as signed out and redirects to the login page. Endpoints called from logged-in pages must return 400, not 401, for "wrong password"-type errors where the session is still valid.
- **Frontend asset versions**: nginx serves CSS and JS with a 1-hour browser cache. When you change a file that its HTML page loads with a `?v=` value (such as `board.js` and `board.css` in `www/board.html`), bump that value, in the form `YYYYMMDDa`, or browsers can run new JS against old CSS.
- **Mobile board height**: at 900px and below, `updateMobileBoardViewportMetrics()` in `www/js/board.js` sets the board height from the measured viewport, because an installed PWA can report a `100dvh` taller than the visible area. It re-measures on viewport changes and through a `ResizeObserver` on `document.body`, because the header loads after the board can render. UI tests that intercept requests need `context.route`, since the service worker makes them.
- **Frontend modals**: reuse the existing modal structure and styles, and use the CSS variables so themes work. Don't hardcode colours. Use danger styling only for destructive actions.

## PR review workflow

- **Review sequentially.** Check `git diff --stat` first, then review the diff yourself in one pass. Never fan out to sub-agents (see Sub-agents above).
- **Reproduce before reporting.** Run the changed code against a crafted input and compare it with the pre-change behaviour. Report a regression only after you have confirmed it is real.
- **Report, then wait.** Post findings as PR comments: one summary comment, plus inline comments on the relevant lines. Then stop. Don't commit fixes until the user approves them, even obvious ones.
- **Label AI-written comments.** Comments are posted from the user's GitHub account, so readers will assume the user wrote them unless told otherwise. Every comment body must start with this exact line, followed by a blank line:

  `> **⚠️ AI-generated comment, posted on behalf of @<username> — not written by them personally.**`

  A footer at the bottom is not enough, because readers see the top first. Check the final body string before each post. If a comment went out without the line, edit it immediately. Write the JSON with Python's `json.dump` and send it with `gh api repos/{owner}/{repo}/issues/comments/{id} -X PATCH --input <file>`, then confirm with a GET. On Windows/Git Bash, `-f body=@path` posts the literal path string instead of the file contents.
- **After an approved fix**, re-run the reproduction that found the bug to confirm the fix. Leave resolving or closing review threads to the user.
- **After merging**, delete the merged branch locally and on the remote. Before deleting, check `git branch --merged origin/main` lists it. Never delete an unmerged branch without asking.

## PR labels and release notes

- When opening a PR, label it as described in CONTRIBUTING.md "Labels and Release Notes". If admins must check or act on anything when upgrading, add `upgrade-note` and a "Release notes" section to the PR description. Use `breaking-change` the same way for incompatible API changes. Label Snyk PRs `security`.
- To draft release notes, generate the grouped list without creating a release:
  `gh api repos/sjefferson99/aft/releases/generate-notes -f tag_name=<new tag> -f previous_tag_name=<last tag> -q .body`
  Then rewrite each line in plain language, in the style of earlier releases. Expand `breaking-change` and `upgrade-note` entries from the "Release notes" section of each PR. A PR that is both a feature and an upgrade risk is grouped only under Upgrade notes, so also mention it in the feature section where relevant. Before drafting, check that every merged PR since the last tag has a category label:
  `gh pr list --state merged --search "merged:><last release date>" --json number,title,labels`

## Dependabot PR processing

1. List open PRs: `gh pr list --author app/dependabot`.
2. Create a local branch from `origin/main` and merge each dependabot branch into it.
   - Dependabot pins in `server/requirements.txt` sit on adjacent lines, so expect content conflicts.
   - Resolve each conflict by keeping every bumped version.
3. Install into the venv: `.venv\Scripts\python.exe -m pip install -r server/requirements.txt -r server/requirements-dev.txt -r ui-tests/requirements-dev.txt`.
4. Reset to a clean DB and rebuild (see the commands table), then wait for `http://localhost` to return 200.
5. Run the UI tests first, because they need the fresh DB. Then run the backend tests, one after the other.
6. If a suite fails, it's usually a dirty DB rather than the dependency. Reset the DB and re-run before investigating.
7. If everything passes, merge with `gh pr merge <n> --merge`.
   - After the first merge, the remaining PRs will conflict on the same file.
   - For each remaining PR: check out its branch, merge `origin/main`, take `server/requirements.txt` from your tested branch and push.
   - Confirm that `git diff` against the tested branch is empty, then merge.
8. Check that `origin/main` matches the tested tree, then delete the local branches.
