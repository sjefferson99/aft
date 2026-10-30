"""UI smoke tests for the login flow."""
import uuid

import pytest


@pytest.mark.ui
def test_login_with_valid_credentials_loads_boards_page(logged_in_page):
    """A successful login lands on the boards page, not back on login.html."""
    page = logged_in_page

    assert "login.html" not in page.url

    boards_container = page.locator("#boards-container")
    boards_container.wait_for(state="visible", timeout=5000)
    assert boards_container.is_visible()


@pytest.mark.ui
def test_login_with_invalid_credentials_shows_error(page):
    """An incorrect password keeps the user on login.html with an error shown."""
    page.goto("/login.html")
    page.fill("#email", "test-admin@localhost")
    page.fill("#password", "WrongPassword123!")
    page.click("#loginButton")

    error_message = page.locator("#errorMessage")
    error_message.wait_for(state="visible", timeout=5000)

    assert "login.html" in page.url
    assert error_message.inner_text().strip() != ""


@pytest.mark.ui
def test_login_rate_limit_shows_message(page):
    """After too many failures the login page says to try again later."""
    email = f"nobody-{uuid.uuid4().hex}@localhost"

    page.goto("/login.html")
    for _ in range(10):
        response = page.request.post(
            "/api/auth/login", data={"email": email, "password": "WrongPassword123!"}
        )
        assert response.status == 401

    page.fill("#email", email)
    page.fill("#password", "WrongPassword123!")
    page.click("#loginButton")

    error_message = page.locator("#errorMessage")
    error_message.wait_for(state="visible", timeout=5000)

    assert "login.html" in page.url
    assert "Too many attempts" in error_message.inner_text()
