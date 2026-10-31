"""UI tests for preferences on the profile page and the instance settings page (#621)."""
import os
import uuid

import pytest
import requests

UI_BASE_URL = os.getenv("PYTEST_UI_BASE_URL", "http://localhost")

pytestmark = pytest.mark.ui


@pytest.fixture
def regular_user(api_session):
    """An approved user with the default roles, so without branding.edit."""
    suffix = uuid.uuid4().hex[:8]
    user = {
        "email": f"ui-prefs-{suffix}@localhost",
        "username": f"ui-prefs-{suffix}",
        "password": f"UiPrefs-{uuid.uuid4().hex[:12]}-Aa1!",
    }
    response = requests.post(f"{UI_BASE_URL}/api/auth/register", json={
        **user, "display_name": f"UI Prefs {suffix}",
    }, timeout=5)
    assert response.status_code == 201, response.text
    body = response.json()
    user["id"] = body.get("user", {}).get("id") or body.get("data", {}).get("user", {}).get("id")
    approved = api_session.post(f"{UI_BASE_URL}/api/users/{user['id']}/approve")
    assert approved.status_code == 200, approved.text
    return user


def login(page, user):
    page.goto("/login.html")
    page.fill("#email", user["email"])
    page.fill("#password", user["password"])
    page.click("#loginButton")
    page.wait_for_url(lambda url: "login.html" not in url, timeout=10000)


def test_profile_page_holds_preferences(logged_in_page):
    page = logged_in_page
    page.goto("/profile.html#preferences")

    assert page.locator(".profile-nav a").all_inner_texts() == ["Account", "Security", "Preferences"]
    page.locator("#theme-select option").first.wait_for(state="attached", timeout=8000)
    page.locator("#working-style option").first.wait_for(state="attached", timeout=8000)
    for selector in ("#default-board", "#timezone-select", "#touchscreen-mode"):
        assert page.locator(selector).count() == 1
    page.wait_for_function(
        "() => document.getElementById('preferences').getBoundingClientRect().top < window.innerHeight",
        timeout=8000,
    )


def test_preference_saves_from_the_profile_page(logged_in_page, api_session, ui_base_url):
    original = api_session.get(f"{ui_base_url}/api/settings/working-style").json()["value"]
    changed = "agile" if original == "kanban" else "kanban"

    page = logged_in_page
    page.goto("/profile.html")
    page.wait_for_load_state("networkidle")  # Preferences binds its listeners after loading
    try:
        page.select_option("#working-style", changed)
        page.locator("#settings-status", has_text="Saved").wait_for(state="visible", timeout=5000)
        assert api_session.get(f"{ui_base_url}/api/settings/working-style").json()["value"] == changed
    finally:
        api_session.put(f"{ui_base_url}/api/settings/working-style", json={"value": original})


def test_user_without_instance_access_goes_to_their_preferences(page, regular_user):
    login(page, regular_user)
    page.goto("/settings.html")

    page.wait_for_url("**/profile.html#preferences", timeout=8000)
    page.locator("#working-style").wait_for(state="visible", timeout=5000)


def test_settings_page_only_has_instance_settings(logged_in_page):
    page = logged_in_page
    page.goto("/settings.html")

    page.locator("#global-settings-panel").wait_for(state="visible", timeout=8000)
    page.locator("#instance-default-theme option").first.wait_for(state="attached", timeout=8000)
    assert page.locator("#default-board").count() == 0
    assert page.locator("#theme-select").count() == 0
    assert "profile.html" not in page.url
    assert page.locator('.settings-page-note a[href="/profile.html#preferences"]').is_visible()


def test_desktop_user_menu_links_to_profile(logged_in_page):
    page = logged_in_page
    page.goto("/settings.html")
    page.locator(".user-dropdown .icon-link").click()

    page.locator('.user-dropdown-item[href="/profile.html"]').click()
    page.wait_for_url("**/profile.html", timeout=8000)
