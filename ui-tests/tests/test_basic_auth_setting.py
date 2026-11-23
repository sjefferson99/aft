"""UI tests for the HTTP Basic auth setting in Instance Settings (#716)."""
import os
import uuid

import pytest
import requests

UI_BASE_URL = os.getenv("PYTEST_UI_BASE_URL", "http://localhost")

pytestmark = pytest.mark.ui


@pytest.fixture
def branding_user(api_session):
    """An approved user whose only extra permission is branding.edit."""
    suffix = uuid.uuid4().hex[:8]
    user = {
        "email": f"ui-basic-{suffix}@localhost",
        "username": f"ui-basic-{suffix}",
        "password": f"UiBasic-{uuid.uuid4().hex[:12]}-Aa1!",
    }
    response = requests.post(f"{UI_BASE_URL}/api/auth/register", json={
        **user, "display_name": f"UI Basic {suffix}",
    }, timeout=5)
    assert response.status_code == 201, response.text
    body = response.json()
    user_id = body.get("user", {}).get("id") or body.get("data", {}).get("user", {}).get("id")
    approved = api_session.post(f"{UI_BASE_URL}/api/users/{user_id}/approve")
    assert approved.status_code == 200, approved.text

    role = api_session.post(f"{UI_BASE_URL}/api/roles", json={
        "name": f"ui_basic_{suffix}",
        "description": "Created by ui-tests",
        "permissions": ["branding.edit"],
    })
    assert role.status_code in (200, 201), role.text
    assigned = api_session.post(f"{UI_BASE_URL}/api/roles/assign", json={
        "user_id": user_id, "role_id": role.json()["role"]["id"], "board_id": None,
    })
    assert assigned.status_code in (200, 201), assigned.text
    return user


@pytest.fixture
def restore_basic_auth(api_session, ui_base_url):
    yield
    response = api_session.put(f"{ui_base_url}/api/settings/basic-auth", json={"mode": "all"})
    assert response.status_code == 200, response.text


def test_admin_changes_basic_auth_mode(logged_in_page, api_session, ui_base_url, restore_basic_auth):
    page = logged_in_page
    page.goto("/settings.html")

    page.locator("#security-settings-panel").wait_for(state="visible", timeout=8000)
    select = page.locator("#basic-auth-mode")
    page.wait_for_function(
        "() => document.getElementById('basic-auth-mode').value === 'all'", timeout=8000
    )
    assert select.get_attribute("aria-describedby") == "basic-auth-help"

    select.select_option("api_only_users")
    page.locator("#basic-auth-save-btn").click()
    page.locator("#basic-auth-status.success").wait_for(timeout=8000)

    saved = api_session.get(f"{ui_base_url}/api/settings/basic-auth").json()
    assert saved["mode"] == "api_only_users"

    page.reload()
    page.wait_for_function(
        "() => document.getElementById('basic-auth-mode').value === 'api_only_users'", timeout=8000
    )


def test_security_section_hidden_without_system_admin(page, branding_user):
    page.goto("/login.html")
    page.fill("#email", branding_user["email"])
    page.fill("#password", branding_user["password"])
    page.click("#loginButton")
    page.wait_for_url(lambda url: "login.html" not in url, timeout=10000)
    page.goto("/settings.html")

    page.locator("#global-settings-panel").wait_for(state="visible", timeout=8000)
    assert page.locator("#security-settings-panel").is_hidden()
