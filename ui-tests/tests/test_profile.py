"""UI tests for the Profile page."""
import pytest
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
