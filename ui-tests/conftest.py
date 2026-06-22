"""Pytest configuration and fixtures for Playwright UI/E2E tests."""
import os
import time
import uuid
from urllib.parse import urlparse

import pytest
import requests

# UI under test is the nginx-fronted stack, same target as server/tests'
# API_BASE_URL. Override with PYTEST_UI_BASE_URL for local debugging.
UI_BASE_URL = os.getenv("PYTEST_UI_BASE_URL", "http://localhost")
UI_HOST = urlparse(UI_BASE_URL).hostname or "localhost"
READY_ENDPOINT = "/api/auth/setup/status"
WAIT_TIMEOUT_SECONDS = float(os.getenv("PYTEST_UI_WAIT_TIMEOUT_SECONDS", "8"))
WAIT_INTERVAL_SECONDS = 0.5

TEST_ADMIN_EMAIL = "test-admin@localhost"
TEST_ADMIN_USERNAME = "test-admin"
TEST_ADMIN_PASSWORD = "TestAdmin123!"


def _mirror_secure_session_cookies_for_http(session):
    """Mirror Secure-flagged cookies as non-secure so `requests` will still
    send them over http://localhost.

    When SESSION_COOKIE_SECURE=true on the server, the login response sets
    the auth cookie with Secure, which `requests` then withholds on plain
    HTTP requests. Same quirk, same fix as server/tests/conftest.py.
    """
    if not UI_BASE_URL.startswith("http://"):
        return

    for cookie in [c for c in session.cookies if c.secure]:
        cookie_path = cookie.path or "/"
        session.cookies.set(cookie.name, cookie.value, path=cookie_path, secure=False)
        session.cookies.set(cookie.name, cookie.value, domain=UI_HOST, path=cookie_path, secure=False)


@pytest.fixture(scope="session")
def base_url():
    """Point pytest-playwright's base_url at the running stack.

    Lets tests use page.goto("/login.html") instead of hardcoding hosts.
    """
    return UI_BASE_URL


@pytest.fixture(scope="session", autouse=True)
def ensure_test_admin():
    """Wait for the stack to be reachable and make sure the canonical
    test-admin user exists, mirroring server/tests/conftest.py.

    Only handles the fresh-database case (no users yet). If an admin
    already exists with different credentials, start from a fresh
    database first - see ui-tests/docs/UI_TESTING.md.
    """
    deadline = time.time() + WAIT_TIMEOUT_SECONDS
    last_error = None

    while time.time() < deadline:
        try:
            response = requests.get(f"{UI_BASE_URL}{READY_ENDPOINT}", timeout=2)
            if response.status_code < 500:
                break
            last_error = f"unexpected status {response.status_code}"
        except requests.exceptions.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(WAIT_INTERVAL_SECONDS)
    else:
        raise Exception(
            "UI under test is not reachable for Playwright tests. "
            f"Tried {UI_BASE_URL}{READY_ENDPOINT} for {WAIT_TIMEOUT_SECONDS:.1f}s; "
            f"last error: {last_error}. Start the stack first "
            "(docker compose up -d --build) or increase PYTEST_UI_WAIT_TIMEOUT_SECONDS."
        )

    setup_status = requests.get(f"{UI_BASE_URL}{READY_ENDPOINT}", timeout=2).json()
    if not setup_status.get("setup_complete", False):
        requests.post(
            f"{UI_BASE_URL}/api/auth/setup/admin",
            json={
                "email": TEST_ADMIN_EMAIL,
                "username": TEST_ADMIN_USERNAME,
                "password": TEST_ADMIN_PASSWORD,
                "display_name": "Test Admin",
            },
            timeout=5,
        )


@pytest.fixture
def logged_in_page(page):
    """A Playwright page already authenticated as the test-admin user."""
    page.goto("/login.html")
    page.fill("#email", TEST_ADMIN_EMAIL)
    page.fill("#password", TEST_ADMIN_PASSWORD)
    page.click("#loginButton")
    page.wait_for_url(lambda url: "login.html" not in url, timeout=10000)
    return page


@pytest.fixture
def ui_base_url():
    """Expose the stack URL to tests that need to call the API directly."""
    return UI_BASE_URL


@pytest.fixture
def api_session(ensure_test_admin):
    """A requests.Session authenticated as test-admin, separate from the
    browser's own cookies. Used to set up/tear down data quickly (e.g. a
    board to open) without making every test depend on the UI flow for it.
    """
    session = requests.Session()
    response = session.post(
        f"{UI_BASE_URL}/api/auth/login",
        json={"email": TEST_ADMIN_EMAIL, "password": TEST_ADMIN_PASSWORD},
        timeout=5,
    )
    assert response.status_code == 200, (
        f"API login as test-admin failed: {response.status_code} {response.text}"
    )
    _mirror_secure_session_cookies_for_http(session)
    return session


@pytest.fixture
def board(api_session):
    """Create a board via the API and yield it; delete it afterwards.

    For tests whose focus is something *inside* a board (columns, cards),
    not board creation itself - mirrors server/tests' sample_board fixture.
    """
    response = api_session.post(
        f"{UI_BASE_URL}/api/boards",
        json={"name": f"UI Test Board {uuid.uuid4().hex[:8]}", "description": "Created by ui-tests"},
    )
    assert response.status_code == 201, f"Failed to create board: {response.status_code} {response.text}"
    board_data = response.json()["board"]

    yield board_data

    # 404/403 are fine here - some tests legitimately delete the board
    # themselves (e.g. via the UI) before this teardown runs; require_board_access
    # returns 403 rather than 404 for a missing board to avoid revealing which
    # board IDs exist. Anything else means the board was left behind.
    cleanup_response = api_session.delete(f"{UI_BASE_URL}/api/boards/{board_data['id']}")
    assert cleanup_response.status_code in (200, 403, 404), (
        f"Failed to clean up board {board_data['id']}: "
        f"{cleanup_response.status_code} {cleanup_response.text}"
    )


@pytest.fixture
def column(api_session, board):
    """Create a column on `board` via the API and yield it; delete it afterwards."""
    response = api_session.post(
        f"{UI_BASE_URL}/api/boards/{board['id']}/columns",
        json={"name": "To Do"},
    )
    assert response.status_code == 201, f"Failed to create column: {response.status_code} {response.text}"
    column_data = response.json()["column"]

    yield column_data

    cleanup_response = api_session.delete(f"{UI_BASE_URL}/api/columns/{column_data['id']}")
    assert cleanup_response.status_code in (200, 403, 404), (
        f"Failed to clean up column {column_data['id']}: "
        f"{cleanup_response.status_code} {cleanup_response.text}"
    )
