"""UI tests for the Profile page."""
import re
import uuid

import pytest
import requests
from playwright.sync_api import expect


@pytest.mark.ui
def test_change_password_with_wrong_current_password_shows_error(logged_in_page):
    """A wrong current password shows the error and leaves the user on the page (#591)."""
    page = logged_in_page
    page.goto("/profile.html")
    page.wait_for_load_state("networkidle")

    navigations = []
    page.on("framenavigated", lambda frame: navigations.append(frame.url))

    page.fill("#current-password", "WrongPassword123!")
    page.fill("#new-password", "NewPassword456!")
    page.fill("#confirm-password", "NewPassword456!")

    with page.expect_response("**/api/auth/change-password") as response_info:
        page.click("#change-password-btn")
    assert response_info.value.status == 400

    expect(page.locator("#password-status")).to_have_text("Current password is incorrect")
    assert "profile.html" in page.url
    assert navigations == []
    # The form isn't cleared, so the user can correct the current password.
    expect(page.locator("#new-password")).to_have_value("NewPassword456!")


@pytest.mark.ui
def test_saving_a_taken_username_shows_the_server_error(logged_in_page, ui_base_url):
    """A rejected profile save shows the server's message, not the generic one (#594)."""
    taken_username = f"ui-profile-{uuid.uuid4().hex[:8]}"
    response = requests.post(f"{ui_base_url}/api/auth/register", json={
        "email": f"{taken_username}@localhost",
        "username": taken_username,
        "password": f"UiProfile-{uuid.uuid4().hex[:12]}-Aa1!",
        "display_name": "UI Profile",
    }, timeout=5)
    assert response.status_code == 201, response.text

    page = logged_in_page
    page.goto("/profile.html")
    page.wait_for_load_state("networkidle")

    # test-admin's @localhost address fails the form's own check, so use one that reaches the server.
    page.fill("#email", "test-admin@example.com")
    page.fill("#username", taken_username)
    page.click("#save-profile-btn")

    expect(page.locator("#profile-status")).to_have_text("Username already taken")


@pytest.mark.ui
def test_rejected_profile_colour_shows_the_server_error(logged_in_page):
    """A rejected colour shows the server's message, not the generic one (#594)."""
    page = logged_in_page
    page.goto("/profile.html")
    page.wait_for_load_state("networkidle")

    # The swatches only offer valid colours, so make one invalid to get a real rejection.
    swatch = page.locator(".colour-swatch").first
    swatch.evaluate("element => { element.dataset.colour = 'not-a-colour'; }")
    swatch.click()

    expect(page.locator("#colour-status")).to_contain_text("must be a valid RGB hex string")


@pytest.mark.ui
def test_form_text_and_inputs_use_theme_colours(logged_in_page):
    """Help text and inputs follow the theme, so they stay readable on dark themes (#611)."""
    page = logged_in_page
    page.goto("/profile.html")
    page.wait_for_load_state("networkidle")

    page.evaluate("""() => {
      document.documentElement.style.setProperty('--text-color', 'rgb(1, 2, 3)');
      document.documentElement.style.setProperty('--card-bg-color', 'rgb(4, 5, 6)');
    }""")

    expect(page.locator(".field-help").first).to_have_css("color", "rgb(1, 2, 3)")
    display_name = page.locator("#display-name")
    expect(display_name).to_have_css("color", "rgb(1, 2, 3)")
    expect(display_name).to_have_css("background-color", "rgb(4, 5, 6)")


@pytest.mark.ui
def test_profile_stylesheet_only_uses_defined_theme_variables(logged_in_page):
    """A variable with no fallback must be defined, or the colour silently falls back (#611)."""
    page = logged_in_page
    page.goto("/profile.html")
    page.wait_for_load_state("networkidle")

    stylesheet = page.request.get("/css/profile.css").text()
    variables = set(re.findall(r"var\((--[\w-]+)\)", stylesheet))
    assert variables

    undefined = page.evaluate("""variables => {
      const styles = getComputedStyle(document.documentElement);
      return variables.filter(name => !styles.getPropertyValue(name).trim());
    }""", sorted(variables))
    assert undefined == []
