# Agent Context

Shared guidance for any AI coding agent working in this repo (Claude, Copilot,
etc.). Tool-specific entry points such as CLAUDE.md point here. Keep entries
short, factual and durable. Update this file when behaviour or workflow
changes, not for one-off task notes.

## Before making changes

Read CONTRIBUTING.md before implementing anything. It covers:
- Coding standards: formatting and naming.
- API test conventions: tests go through the API only, with no direct DB access.
- Security expectations: validate input, enforce length limits, and never leak internal error details to clients.

Also:
- Add or update tests for every API change.
- Update README/docs when user-visible behaviour changes.

## Environment

- The development machine runs Windows. Commands below use Windows paths. The repo venv is `.venv`, so use `.venv\Scripts\python.exe` (or `../.venv/Scripts/python.exe` from Git Bash).
- Use `compose.yml` for local development and testing, and always pass `--build` so code changes reach the containers. `compose.example.yml` is the GHCR deployment template; don't use it locally.
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
| UI/E2E tests | from `ui-tests/`: `..\.venv\Scripts\python.exe -m pytest -q` |
| UI test one-time setup | `pip install -r ui-tests/requirements-dev.txt` then `playwright install chromium` |

Only delete `./data` after `docker compose down` has succeeded. Removing files under a running MySQL instance corrupts the database.

## Testing

- `server/tests` are integration tests. They hit the running Docker stack, so the stack must be up and rebuilt with current code. The full suite takes about 20 minutes (~900 tests).
- `ui-tests/` holds Playwright tests for `www/` (pytest-playwright, no Node toolchain). They need the stack at `http://localhost`. Login-dependent tests need a fresh database; see `ui-tests/docs/UI_TESTING.md`. Use the `logged_in_page` fixture for authenticated tests rather than reimplementing login.
- Both suites share one dev database. Never run two suites, or two runs of the same suite, at the same time: they interfere with each other and produce spurious failures.
- Match test scope to what changed. A frontend-only (JS/CSS/HTML) change doesn't need a backend pytest run. Run the narrowest subset that exercises the changed code. Run full suites when backend code or dependencies change, or before merging.
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
- **Frontend modals**: reuse the existing modal structure and styles, and use the CSS variables so themes work. Don't hardcode colours. Use danger styling only for destructive actions.

## PR review workflow

- **Size the review to the diff.** Check `git diff --stat` first. For a single file or fewer than ~300 changed lines, do one sequential review pass with no parallel sub-agents. Multi-agent fan-out on a small diff produces many overlapping, low-value findings. Use fan-out only for large, multi-file or high-risk changes, and even then only when the user asks for it.
- **Reproduce before reporting.** Run the changed code against a crafted input and compare it with the pre-change behaviour. Report a regression only after you have confirmed it is real.
- **Report, then wait.** Post findings as PR comments: one summary comment, plus inline comments on the relevant lines. Then stop. Don't commit fixes until the user approves them, even obvious ones.
- **Label AI-written comments.** Comments are posted from the user's GitHub account, so readers will assume the user wrote them unless told otherwise. Every comment body must start with this exact line, followed by a blank line:

  `> **⚠️ AI-generated comment, posted on behalf of @<username> — not written by them personally.**`

  A footer at the bottom is not enough, because readers see the top first. Check the final body string before each post. If a comment went out without the line, edit it immediately. Write the JSON with Python's `json.dump` and send it with `gh api repos/{owner}/{repo}/issues/comments/{id} -X PATCH --input <file>`, then confirm with a GET. On Windows/Git Bash, `-f body=@path` posts the literal path string instead of the file contents.
- **After an approved fix**, re-run the reproduction that found the bug to confirm the fix. Leave resolving or closing review threads to the user.

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
