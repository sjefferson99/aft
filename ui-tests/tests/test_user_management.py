"""UI tests for the combined Users panel on User Management (#632, #622)."""
import os
import uuid

import pytest
import requests

UI_BASE_URL = os.getenv("PYTEST_UI_BASE_URL", "http://localhost")

pytestmark = pytest.mark.ui


def create_user(api_session, approve=True):
    suffix = uuid.uuid4().hex[:8]
    user = {
        "email": f"ui-users-{suffix}@localhost",
        "username": f"ui-users-{suffix}",
        "password": f"UiUsers-{uuid.uuid4().hex[:12]}-Aa1!",
    }
    response = requests.post(f"{UI_BASE_URL}/api/auth/register", json={
        **user, "display_name": f"UI Users {suffix}",
    }, timeout=5)
    assert response.status_code == 201, response.text
    body = response.json()
    user["id"] = body.get("user", {}).get("id") or body.get("data", {}).get("user", {}).get("id")
    if approve:
        approved = api_session.post(f"{UI_BASE_URL}/api/users/{user['id']}/approve")
        assert approved.status_code == 200, approved.text
    return user


def role_id(api_session, name):
    roles = api_session.get(f"{UI_BASE_URL}/api/roles").json()["roles"]
    return next(role["id"] for role in roles if role["name"] == name)


def assign_role(api_session, user, role, board_id=None):
    response = api_session.post(f"{UI_BASE_URL}/api/roles/assign", json={
        "user_id": user["id"], "role_id": role, "board_id": board_id,
    })
    assert response.status_code in (200, 201), response.text


def user_row(page, user):
    row = page.locator(f'.active-user-card[data-user-id="{user["id"]}"]')
    row.wait_for(timeout=10000)
    return row


def login_status(user, password):
    return requests.post(f"{UI_BASE_URL}/api/auth/login", json={
        "email": user["email"], "password": password,
    }, timeout=5).status_code


@pytest.fixture
def managed_user(api_session):
    return create_user(api_session)


def test_one_panel_holds_users_and_roles(logged_in_page, api_session, managed_user, board):
    """A row shows account actions and global and board roles, with no second list."""
    assign_role(api_session, managed_user, role_id(api_session, "board_editor"), board["id"])

    page = logged_in_page
    page.goto("/user-management.html")
    row = user_row(page, managed_user)

    assert row.locator('[data-action="deactivate"]').count() == 1
    chip = row.locator(".user-role-chip", has_text=board["name"])
    chip.wait_for(timeout=5000)
    assert "board_editor" in chip.inner_text()
    assert page.locator("#role-users-list").count() == 0
    assert page.locator("#role-user-search").count() == 0
    assert page.locator('#active-users-section .filter-bar #add-user-btn').is_visible()


def add_board_role_from_the_row(page, row, board):
    row.locator('[data-action="add-role"]').click()
    page.locator("#add-role-modal").wait_for(state="visible", timeout=5000)
    page.select_option("#role-select", label="board_viewer")
    page.select_option("#board-select", label=board["name"])
    page.click("#add-role-ok-btn")


def test_add_and_remove_role_from_the_row(logged_in_page, managed_user, board):
    page = logged_in_page
    page.goto("/user-management.html")
    add_board_role_from_the_row(page, user_row(page, managed_user), board)

    chip = user_row(page, managed_user).locator(".user-role-chip", has_text=board["name"])
    chip.wait_for(timeout=10000)
    assert "board_viewer" in chip.inner_text()

    chip.locator(".user-role-chip-remove").click()
    page.locator("#confirm-modal").wait_for(state="visible", timeout=5000)
    page.click("#confirm-ok-btn")

    page.locator(
        f'.active-user-card[data-user-id="{managed_user["id"]}"] .user-role-chip',
        has_text=board["name"],
    ).wait_for(state="detached", timeout=10000)


def test_search_stays_applied_after_a_role_change(logged_in_page, managed_user, board):
    """Reloading the list after a change keeps the search that is in the box."""
    page = logged_in_page
    page.goto("/user-management.html")
    row = user_row(page, managed_user)

    page.fill("#user-search", managed_user["username"])
    page.wait_for_function("document.querySelectorAll('.active-user-card').length === 1")

    add_board_role_from_the_row(page, row, board)

    user_row(page, managed_user).locator(
        ".user-role-chip", has_text=board["name"]
    ).wait_for(timeout=10000)
    assert page.locator(".active-user-card").count() == 1


def test_own_row_cannot_change_roles(logged_in_page):
    page = logged_in_page
    page.goto("/user-management.html")
    page.fill("#user-search", "test-admin@localhost")
    row = page.locator(".active-user-card", has_text="test-admin@localhost")
    row.wait_for(timeout=10000)

    assert "Cannot modify own roles" in row.inner_text()
    assert "You" in row.locator(".user-name").inner_text()
    assert row.locator('[data-action="add-role"]').count() == 0
    assert row.locator(".user-role-chip-remove").count() == 0
    assert row.locator('[data-action="reset-password"]').count() == 0
    assert row.locator('[data-action="deactivate"]').is_disabled()


def test_deactivated_user_keeps_read_only_roles(logged_in_page, api_session, managed_user):
    """Inactive users aren't offered for role changes, but stay in the list."""
    deactivated = api_session.post(f"{UI_BASE_URL}/api/users/{managed_user['id']}/deactivate")
    assert deactivated.status_code == 200, deactivated.text

    page = logged_in_page
    page.goto("/user-management.html")
    page.locator(".active-user-card").first.wait_for(timeout=10000)
    assert page.locator(f'.active-user-card[data-user-id="{managed_user["id"]}"]').count() == 0

    page.locator(".toggle-label").click()
    row = user_row(page, managed_user)
    assert row.locator(".role-badge", has_text="theme_user").count() == 1
    assert row.locator(".user-role-chip").count() == 0
    assert row.locator('[data-action="add-role"]').count() == 0
    assert row.locator('[data-action="activate"]').count() == 1


def test_board_name_with_quotes_is_not_rendered_as_html(logged_in_page, api_session, managed_user):
    name = f'"><img src=x onerror=window.__xss=1> {uuid.uuid4().hex[:6]}'
    created = api_session.post(f"{UI_BASE_URL}/api/boards", json={"name": name})
    assert created.status_code == 201, created.text
    board_id = created.json()["board"]["id"]
    try:
        assign_role(api_session, managed_user, role_id(api_session, "board_editor"), board_id)

        page = logged_in_page
        page.goto("/user-management.html")
        chip = user_row(page, managed_user).locator(".user-role-chip", has_text="board_editor")
        chip.wait_for(timeout=5000)

        assert name in chip.get_attribute("title")
        assert chip.locator("img").count() == 0
        assert page.evaluate("window.__xss") is None
    finally:
        api_session.delete(f"{UI_BASE_URL}/api/boards/{board_id}")


def test_admin_can_reset_password_from_the_user_list(logged_in_page, managed_user):
    new_password = f"UiReset-{uuid.uuid4().hex[:12]}-Aa1!"

    page = logged_in_page
    page.goto("/user-management.html")
    user_row(page, managed_user).locator('[data-action="reset-password"]').click()

    page.locator("#reset-password-modal").wait_for(state="visible", timeout=5000)
    page.fill("#reset-password-new", new_password)
    page.fill("#reset-password-confirm", new_password)
    page.click("#reset-password-ok-btn")
    page.locator("#reset-password-modal").wait_for(state="hidden", timeout=5000)

    assert login_status(managed_user, new_password) == 200
    assert login_status(managed_user, managed_user["password"]) != 200


def test_role_only_user_gets_role_editing_without_account_actions(
    browser, api_session, managed_user
):
    """A user.role holder without user.manage can edit roles but not accounts."""
    suffix = uuid.uuid4().hex[:8]
    created = api_session.post(f"{UI_BASE_URL}/api/roles", json={
        "name": f"ui_role_editor_{suffix}",
        "description": "Created by ui-tests",
        "permissions": ["user.role"],
    })
    assert created.status_code in (200, 201), created.text
    custom_role = created.json()["role"]["id"]
    role_editor = create_user(api_session)
    assign_role(api_session, role_editor, custom_role)

    context = browser.new_context(base_url=UI_BASE_URL)
    try:
        page = context.new_page()
        page.goto("/login.html")
        page.fill("#email", role_editor["email"])
        page.fill("#password", role_editor["password"])
        page.click("#loginButton")
        page.wait_for_url(lambda url: "login.html" not in url, timeout=10000)

        page.goto("/user-management.html")
        page.fill("#user-search", managed_user["username"])
        row = user_row(page, managed_user)
        row.locator('[data-action="add-role"]').wait_for(timeout=5000)

        assert page.locator(".user-actions").count() == 0
        assert not page.locator("#add-user-btn").is_visible()
        assert not page.locator("#show-active-only").locator("..").is_visible()
        assert not page.locator("#pending-users-section").is_visible()
    finally:
        context.close()


def test_user_list_is_paged(logged_in_page, api_session, board):
    """10 rows by default, with 20, 50 and All, and role changes keep your place."""
    users = [create_user(api_session) for _ in range(12)]
    total = sum(
        1 for user in api_session.get(f"{UI_BASE_URL}/api/users?status=approved").json()["users"]
        if user["is_active"]
    )

    page = logged_in_page
    page.goto("/user-management.html")
    rows = page.locator(".active-user-card")
    rows.first.wait_for(timeout=10000)
    status = page.locator("#users-page-status")

    assert rows.count() == 10
    assert status.inner_text() == f"1\u201310 of {total}"
    assert page.locator("#users-prev-btn").is_disabled()
    assert [o.get_attribute("value") for o in page.locator("#users-page-size option").all()] == [
        "10", "20", "50", "all",
    ]

    page.click("#users-next-btn")
    page.wait_for_function("document.querySelector('#users-page-status').textContent.startsWith('11')")
    assert page.locator("#users-prev-btn").is_enabled()

    second_page_user = {"id": rows.first.get_attribute("data-user-id")}
    add_board_role_from_the_row(page, user_row(page, second_page_user), board)
    user_row(page, second_page_user).locator(
        ".user-role-chip", has_text=board["name"]
    ).wait_for(timeout=10000)
    assert status.inner_text().startswith("11")

    page.select_option("#users-page-size", "all")
    page.wait_for_function(f"document.querySelectorAll('.active-user-card').length === {total}")
    assert status.inner_text() == f"1\u2013{total} of {total}"
    assert page.locator("#users-next-btn").is_disabled()

    page.select_option("#users-page-size", "10")
    page.click("#users-next-btn")
    page.wait_for_function("document.querySelector('#users-page-status').textContent.startsWith('11')")
    page.fill("#user-search", users[0]["username"])
    page.wait_for_function("document.querySelectorAll('.active-user-card').length === 1")
    assert not page.locator("#users-pagination").is_visible()
