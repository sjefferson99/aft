"""UI tests for personal API tokens (#714)."""
import os
import uuid

import pytest
import requests
from playwright.sync_api import expect

UI_BASE_URL = os.getenv("PYTEST_UI_BASE_URL", "http://localhost")
TEST_ADMIN_PASSWORD = "TestAdmin123!"

pytestmark = pytest.mark.ui


def _me_status(token):
    return requests.get(
        f"{UI_BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=5
    ).status_code


def _create_in_dialog(page, name, read_only=False, password=None):
    dialog = page.locator(".api-token-dialog")
    expect(dialog).to_be_visible()
    expect(dialog.get_by_label("Name")).to_be_focused()
    dialog.get_by_label("Name").fill(name)
    if read_only:
        dialog.get_by_label("Access").select_option("read")
    dialog.get_by_label("Expires").select_option("30")
    if password is not None:
        dialog.get_by_label("Current Password").fill(password)
    dialog.get_by_role("button", name="Create token").click()

    shown = page.get_by_role("dialog", name="API token created")
    expect(shown).to_be_visible()
    token = shown.get_by_label("API token").input_value()
    assert token.startswith("aft_")
    shown.get_by_role("button", name="Done").click()
    expect(page.locator(".api-token-dialog")).to_have_count(0)
    return token


def test_create_use_and_revoke_own_token(logged_in_page, api_session):
    name = f"UI token {uuid.uuid4().hex[:8]}"
    page = logged_in_page
    page.goto("/profile.html")
    page.wait_for_load_state("networkidle")

    token = None
    try:
        page.click("#create-api-token-btn")
        token = _create_in_dialog(page, name, read_only=True, password=TEST_ADMIN_PASSWORD)
        expect(page.locator("#create-api-token-btn")).to_be_focused()
        assert _me_status(token) == 200

        item = page.locator(".api-token-item", has_text=name)
        expect(item).to_be_visible()
        expect(item.locator(".api-token-badge")).to_have_text("Read only")
        expect(item.locator(".api-token-prefix")).to_have_text(f"{token[:12]}…")
        # The token itself is never listed.
        assert token not in page.content()

        item.get_by_role("button", name=f"Revoke API token {name}").click()
        page.locator("#appModalConfirmBtn").click()
        expect(item).to_have_count(0)
        assert _me_status(token) == 401
    finally:
        # Revoke anything left behind if the test failed part way.
        tokens = api_session.get(f"{UI_BASE_URL}/api/auth/tokens").json().get("tokens", [])
        for leftover in tokens:
            if leftover["name"] == name:
                api_session.delete(f"{UI_BASE_URL}/api/auth/tokens/{leftover['id']}")


def test_create_dialog_needs_a_name(logged_in_page):
    page = logged_in_page
    page.goto("/profile.html")
    page.wait_for_load_state("networkidle")
    page.click("#create-api-token-btn")
    dialog = page.locator(".api-token-dialog")
    dialog.get_by_role("button", name="Create token").click()
    expect(dialog.locator(".api-token-error")).to_have_text("Enter a name.")
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    expect(page.locator("#create-api-token-btn")).to_be_focused()


def test_admin_creates_and_revokes_tokens_for_api_only_account(logged_in_page, api_session):
    suffix = uuid.uuid4().hex[:8]
    response = requests.post(f"{UI_BASE_URL}/api/auth/register", json={
        "email": f"ui-token-{suffix}@localhost",
        "username": f"ui-token-{suffix}",
        "password": f"UiToken-{uuid.uuid4().hex[:12]}-Aa1!",
        "display_name": f"UI Token {suffix}",
    }, timeout=5)
    assert response.status_code == 201, response.text
    body = response.json()
    user_id = body.get("user", {}).get("id") or body.get("data", {}).get("user", {}).get("id")
    assert api_session.post(f"{UI_BASE_URL}/api/users/{user_id}/approve").status_code == 200

    page = logged_in_page
    page.goto("/user-management.html")
    row = page.locator(f'.active-user-card[data-user-id="{user_id}"]')
    row.wait_for(timeout=10000)
    # Only API-only accounts get the button: other people make their own tokens.
    expect(row.locator('[data-action="create-api-token"]')).to_have_count(0)

    response = api_session.put(f"{UI_BASE_URL}/api/users/{user_id}/api-only", json={"api_only": True})
    assert response.status_code == 200, response.text
    page.reload()
    row = page.locator(f'.active-user-card[data-user-id="{user_id}"]')
    row.wait_for(timeout=10000)

    row.locator('[data-action="create-api-token"]').click()
    token = _create_in_dialog(page, "aft-mcp")
    assert _me_status(token) == 200

    row = page.locator(f'.active-user-card[data-user-id="{user_id}"]')
    expect(row.locator(".user-meta", has_text="API tokens: 1")).to_be_visible()

    # Two more tokens, so one can be revoked on its own and the rest together.
    others = {}
    for name in ("backup-script", "dashboard"):
        response = api_session.post(
            f"{UI_BASE_URL}/api/users/{user_id}/tokens", json={"name": name, "read_only": True}
        )
        assert response.status_code == 201, response.text
        others[name] = response.json()["token"]
    page.reload()
    row = page.locator(f'.active-user-card[data-user-id="{user_id}"]')
    row.wait_for(timeout=10000)
    expect(row.locator(".user-meta", has_text="API tokens: 3")).to_be_visible()

    row.locator('[data-action="manage-api-tokens"]').click()
    dialog = page.get_by_role("dialog", name="API tokens for UI Token")
    expect(dialog).to_be_visible()
    items = dialog.locator(".api-token-manage-item")
    expect(items).to_have_count(3)
    expect(dialog.locator(".api-token-manage-item", has_text="dashboard").locator(".api-token-manage-badge")).to_have_text("Read only")
    # The token values are never shown, only their first characters.
    assert token not in dialog.inner_text()

    # Revoke takes a second click on the same button.
    revoke = dialog.get_by_role("button", name="Revoke API token backup-script")
    revoke.click()
    confirm = dialog.get_by_role("button", name="Confirm revoking API token backup-script")
    expect(confirm).to_be_visible()
    assert _me_status(others["backup-script"]) == 200
    confirm.click()
    expect(items).to_have_count(2)
    expect(dialog.locator(".api-token-status")).to_have_text('Revoked "backup-script"')
    assert _me_status(others["backup-script"]) == 401
    assert _me_status(others["dashboard"]) == 200
    assert _me_status(token) == 200

    dialog.get_by_role("button", name="Revoke all").click()
    dialog.get_by_role("button", name="Confirm revoking all API tokens").click()
    expect(dialog.locator(".api-token-manage-empty")).to_be_visible()
    assert _me_status(others["dashboard"]) == 401
    assert _me_status(token) == 401

    dialog.get_by_role("button", name="Close").click()
    expect(page.locator(".api-token-dialog")).to_have_count(0)
    row = page.locator(f'.active-user-card[data-user-id="{user_id}"]')
    expect(row.locator('[data-action="manage-api-tokens"]')).to_have_count(0)
    # The row is rebuilt, and focus lands on its remaining token button.
    expect(row.locator('[data-action="create-api-token"]')).to_be_focused()
