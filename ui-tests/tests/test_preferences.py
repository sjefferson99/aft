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


def create_role_user(api_session, regular_user, permissions):
    created = api_session.post(f"{UI_BASE_URL}/api/roles", json={
        "name": f"ui_instance_{uuid.uuid4().hex[:8]}",
        "description": "Created by ui-tests",
        "permissions": permissions,
    })
    assert created.status_code in (200, 201), created.text
    assigned = api_session.post(f"{UI_BASE_URL}/api/roles/assign", json={
        "user_id": regular_user["id"], "role_id": created.json()["role"]["id"], "board_id": None,
    })
    assert assigned.status_code in (200, 201), assigned.text
    return regular_user


def test_admin_pages_open_as_tabs(logged_in_page):
    page = logged_in_page
    page.goto("/settings.html")

    assert page.locator("h1.page-title").inner_text() == "Instance Settings"
    tabs = page.locator(".settings-tab")
    page.locator("#settings-tab-instance[aria-selected='true']").wait_for(timeout=8000)
    assert tabs.all_inner_texts() == [
        "Instance Settings", "User Management", "Role Management", "Backup & Restore", "Theme Builder",
    ]
    assert page.locator("#settings-dropdown-menu a[href$='.html']").count() == 0
    assert page.locator("#mobile-board-actions a[href$='.html']").count() == 0

    page.locator("#settings-tab-users").click()
    assert page.url.endswith("/settings.html#users")
    assert page.locator("#global-settings-panel").is_hidden()

    frame = page.frame_locator('iframe[src="/user-management.html?embedded=1"]')
    frame.locator(".active-user-card").first.wait_for(timeout=10000)
    assert frame.locator(".header").is_hidden()
    assert frame.locator(".page-title").is_hidden()


def test_tabs_keep_work_when_changing_tab(logged_in_page):
    page = logged_in_page
    page.goto("/settings.html#users")
    frame = page.frame_locator('iframe[src="/user-management.html?embedded=1"]')
    frame.locator("#user-search").fill("kept search")

    page.locator("#settings-tab-instance").click()
    page.locator("#global-settings-panel").wait_for(state="visible", timeout=5000)
    page.locator("#settings-tab-users").click()

    assert frame.locator("#user-search").input_value() == "kept search"
    assert page.locator("iframe.settings-tab-frame").count() == 1


def test_tabs_work_from_the_keyboard(logged_in_page):
    page = logged_in_page
    page.goto("/settings.html")
    instance = page.locator("#settings-tab-instance")
    page.locator("#settings-tab-instance[aria-selected='true']").wait_for(timeout=8000)

    instance.focus()
    page.keyboard.press("ArrowRight")
    assert page.locator("#settings-tab-users").get_attribute("aria-selected") == "true"
    page.keyboard.press("ArrowLeft")
    assert instance.get_attribute("aria-selected") == "true"


def test_user_with_one_admin_permission_keeps_their_route(browser, api_session, regular_user):
    """user.manage alone must still reach User Management, without the branding panel."""
    create_role_user(api_session, regular_user, ["user.manage"])

    context = browser.new_context(base_url=UI_BASE_URL)
    try:
        page = context.new_page()
        login(page, regular_user)
        page.goto("/settings.html")
        page.locator("#settings-tab-users[aria-selected='true']").wait_for(timeout=8000)

        assert "settings.html" in page.url
        assert page.locator("#global-settings-panel").is_hidden()
        assert page.locator("#settings-tab-instance").is_hidden()
        assert page.locator("#settings-tab-backup").is_hidden()
        assert page.locator("#settings-tab-roles").is_hidden()

        page.locator(".user-dropdown .icon-link").click()
        assert page.locator('.user-dropdown-item[href="/settings.html"]').is_visible()
    finally:
        context.close()


def test_regular_user_has_no_instance_settings_link(page, regular_user):
    login(page, regular_user)
    page.goto("/profile.html")
    page.wait_for_load_state("networkidle")
    page.locator(".user-dropdown .icon-link").click()

    page.locator('.user-dropdown-item[href="/profile.html"]').wait_for(state="visible", timeout=5000)
    assert page.locator('.user-dropdown-item[href="/settings.html"]').is_hidden()


def test_board_menu_only_appears_on_boards(logged_in_page, board):
    page = logged_in_page
    page.goto("/profile.html")
    page.wait_for_load_state("networkidle")
    assert page.locator(".settings-dropdown").is_hidden()

    page.goto(f"/board.html?id={board['id']}")
    page.locator(".settings-dropdown .icon-link").wait_for(state="visible", timeout=8000)
    assert page.locator(".settings-dropdown .icon-link").get_attribute("title") == "Board menu"


def test_changing_the_link_changes_the_tab(logged_in_page):
    page = logged_in_page
    page.goto("/settings.html#users")
    page.locator("#settings-tab-users[aria-selected='true']").wait_for(timeout=8000)

    page.evaluate("window.location.hash = '#roles'")

    page.locator("#settings-tab-roles[aria-selected='true']").wait_for(timeout=5000)
