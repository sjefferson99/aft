# UI/E2E Testing Guide (Playwright)

## Overview

This suite drives a real browser against the running AFT stack to test the
frontend (`www/`) end-to-end, the same way a user would: through nginx at
`http://localhost`, not by importing frontend JS directly.

It is built on [pytest-playwright](https://playwright.dev/python/docs/test-runners),
so it's a normal `pytest` suite - no Node.js/npm toolchain required.

It is deliberately kept separate from `server/tests` (run from `ui-tests/`,
not picked up by the root `pytest -v`) because it needs browser binaries and
is slower than the API integration suite.

## Test Organisation

```
ui-tests/
├── conftest.py              # Fixtures: base_url, ensure_test_admin, logged_in_page
├── pytest.ini               # Suite-scoped pytest config (testpaths=tests)
├── requirements-dev.txt     # pytest, pytest-playwright, playwright, requests
├── docs/
│   └── UI_TESTING.md        # This file
└── tests/
    ├── __init__.py
    └── test_login.py        # Example: login flow smoke tests
```

## Prerequisites

1. **Python 3.11+** installed on your machine.
2. **Docker containers running** for the full stack (UI tests need nginx +
   server + db, not just the API):
   ```bash
   docker compose up -d --build
   ```
   The app must be reachable at `http://localhost`.

## Setup

```bash
cd ui-tests
python -m venv venv
source venv/bin/activate   # Windows: .\venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
playwright install chromium
```

`playwright install chromium` is a one-time (per machine) download of the
browser binary - it is not a pip package and won't appear in `pip list`.

## Authentication for Tests

Like `server/tests`, this suite uses a canonical test-admin account:

- Email: `test-admin@localhost`
- Username: `test-admin`
- Password: `TestAdmin123!`

The session-scoped `ensure_test_admin` fixture in `conftest.py` creates this
user automatically **on a fresh database** (no existing users) via the setup
API. It does **not** attempt password recovery if a different admin already
exists - if login-dependent tests fail with an authentication error, reset
to a fresh database:

```bash
docker compose down
rm -rf data   # Windows PowerShell: Remove-Item -Recurse -Force data
docker compose up -d --build
```

Tests that need an authenticated session should use the `logged_in_page`
fixture rather than re-implementing the login flow.

## Running Tests

```bash
cd ui-tests
source venv/bin/activate

# Run all UI tests
pytest -v

# Run headed (watch the browser) - useful while writing/debugging a test
pytest -v --headed

# Run a specific file or test
pytest tests/test_login.py -v
pytest tests/test_login.py::test_login_with_valid_credentials_loads_boards_page -v

# Slow down actions to see what's happening
pytest -v --headed --slowmo 500
```

## Writing New Tests

```python
import pytest


@pytest.mark.ui
def test_my_feature(logged_in_page):
    """Test description."""
    page = logged_in_page
    page.goto("/board.html?id=1")

    page.click("#some-button")

    assert page.locator("#some-result").is_visible()
```

Guidelines:

- Prefer stable selectors that already exist for accessibility (`id`,
  `role`, `aria-label`) over brittle CSS class chains - this also doubles as
  a lightweight accessibility check (see
  [Accessibility Requirements](../../CONTRIBUTING.md#accessibility-requirements)).
- Use `page.goto("/relative.html")` - the `base_url` fixture in
  `conftest.py` already points at the running stack.
- Don't reach into the database or filesystem to set up state; drive the UI
  (or call the API with `requests`, like `server/tests` does) the same way a
  real client would.
- Clean up any data you create through the UI/API, mirroring the cleanup
  pattern used in `server/tests`.

## Troubleshooting

### `Executable doesn't exist` / browser launch errors

Run `playwright install chromium` again - the browser binary is per-machine,
not tracked by pip.

### Connection refused / timeouts waiting for the stack

```bash
curl http://localhost/api/health
docker compose ps
docker compose logs -f nginx server
```

### Login-dependent tests fail with an auth error

The test-admin user either doesn't exist with the expected password, or a
different admin already exists. Reset to a fresh database (see
[Authentication for Tests](#authentication-for-tests) above).
