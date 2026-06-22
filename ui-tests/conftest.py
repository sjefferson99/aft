"""Pytest configuration and fixtures for Playwright UI/E2E tests."""
import os
import time

import pytest
import requests

# UI under test is the nginx-fronted stack, same target as server/tests'
# API_BASE_URL. Override with PYTEST_UI_BASE_URL for local debugging.
UI_BASE_URL = os.getenv("PYTEST_UI_BASE_URL", "http://localhost")
READY_ENDPOINT = "/api/auth/setup/status"
WAIT_TIMEOUT_SECONDS = float(os.getenv("PYTEST_UI_WAIT_TIMEOUT_SECONDS", "8"))
WAIT_INTERVAL_SECONDS = 0.5

TEST_ADMIN_EMAIL = "test-admin@localhost"
TEST_ADMIN_USERNAME = "test-admin"
TEST_ADMIN_PASSWORD = "TestAdmin123!"


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
