"""UI tests for sharing a board from the board menu (#285)."""
import uuid

import pytest
import requests
from playwright.sync_api import expect

pytestmark = pytest.mark.ui

SHARE_ITEM = "#share-board-menu-item"
MODAL = "#board-share-modal"


@pytest.fixture
def other_user(api_session, ui_base_url):
    """An approved user to share with."""
    suffix = uuid.uuid4().hex[:8]
    display_name = f"Share Target {suffix}"
    response = requests.post(f"{ui_base_url}/api/auth/register", json={
        "email": f"ui-share-{suffix}@localhost",
        "username": f"ui-share-{suffix}",
        "password": f"UiShare-{uuid.uuid4().hex[:12]}-Aa1!",
        "display_name": display_name,
    }, timeout=5)
    assert response.status_code == 201, response.text
    body = response.json()
    user_id = body.get("user", {}).get("id") or body.get("data", {}).get("user", {}).get("id")
    approve = api_session.post(f"{ui_base_url}/api/users/{user_id}/approve")
    assert approve.status_code == 200, approve.text
    return {"id": user_id, "display_name": display_name}


def open_share_dialog(page, board):
    page.goto(f"/board.html?id={board['id']}")
    page.wait_for_function(
        f"() => document.querySelector('{SHARE_ITEM}')?.style.display === ''", timeout=8000
    )
    page.locator(".settings-dropdown .icon-link").click()
    page.locator(SHARE_ITEM).click()
    expect(page.locator(MODAL)).to_be_visible()


def members(api_session, ui_base_url, board):
    response = api_session.get(f"{ui_base_url}/api/boards/{board['id']}/members")
    assert response.status_code == 200, response.text
    return [(m["user"]["id"], m["access"]) for m in response.json()["members"]]


def test_owner_shares_changes_and_removes_access(
    logged_in_page, api_session, board, ui_base_url, other_user
):
    page = logged_in_page
    open_share_dialog(page, board)

    modal = page.locator(MODAL)
    expect(page.locator("#board-share-modal-title")).to_have_text("Share Board")
    expect(modal.locator(".board-share-list .board-share-empty")).to_have_text("Not shared with anyone yet.")

    modal.get_by_role("group", name="Access for new people").get_by_role("button", name="Editor").click()
    page.fill("#board-share-search", other_user["display_name"])
    results = modal.locator(".board-share-result")
    expect(results).to_have_count(1)
    results.first.click()

    row = modal.locator(f'.board-share-member[data-user-id="{other_user["id"]}"]')
    expect(row).to_be_visible()
    expect(row.locator('button[aria-pressed="true"]')).to_have_text("Editor")
    assert members(api_session, ui_base_url, board) == [(other_user["id"], "editor")]
    # Someone who already has access isn't offered again.
    expect(results).to_have_count(0)

    row.get_by_role("button", name="Viewer").click()
    expect(row.locator('button[aria-pressed="true"]')).to_have_text("Viewer")
    assert members(api_session, ui_base_url, board) == [(other_user["id"], "viewer")]

    row.get_by_role("button", name=f"Stop sharing with {other_user['display_name']}").click()
    expect(page.locator("#appModal")).to_be_visible()
    page.locator("#appModalConfirmBtn").click()
    expect(modal.locator(".board-share-list .board-share-empty")).to_be_visible()
    assert members(api_session, ui_base_url, board) == []

    page.locator("#board-share-done-btn").click()
    expect(page.locator(MODAL)).to_have_count(0)


def test_people_without_share_rights_see_a_read_only_list(logged_in_page, board, other_user):
    page = logged_in_page
    read_only = {
        "success": True,
        "board_id": board["id"],
        "owner": {"id": 999999, "display_name": "Board Owner", "username": "board-owner"},
        "members": [{
            "user": {"id": other_user["id"], "display_name": other_user["display_name"], "username": "x"},
            "access": "editor",
            "roles": ["board_editor"],
        }],
        "can_share": False,
    }
    page.context.route(
        f"**/api/boards/{board['id']}/members*",
        lambda route: route.fulfill(status=200, json=read_only)
        if route.request.method == "GET" else route.fallback(),
    )
    open_share_dialog(page, board)

    expect(page.locator(SHARE_ITEM)).to_have_text("Board Members")
    expect(page.locator("#board-share-modal-title")).to_have_text("Board Members")
    expect(page.locator(".board-share-owner")).to_have_text("Owner: Board Owner (@board-owner)")
    row = page.locator(f'.board-share-member[data-user-id="{other_user["id"]}"]')
    expect(row.locator(".board-share-access-label")).to_have_text("Editor")
    expect(row.locator(".board-share-remove")).to_have_count(0)
    expect(page.locator("#board-share-search")).to_have_count(0)


def test_reassign_offers_to_keep_the_previous_owner(logged_in_page, board, other_user):
    page = logged_in_page
    page.goto(f"/board.html?id={board['id']}")
    page.wait_for_function(
        "() => document.querySelector('#reassign-board-menu-item')?.style.display === ''", timeout=8000
    )
    page.locator(".settings-dropdown .icon-link").click()
    page.locator("#reassign-board-menu-item").click()

    keep = page.locator("#board-owner-keep-previous")
    expect(keep).to_be_hidden()
    page.select_option("#board-owner-select", str(other_user["id"]))
    expect(keep).to_be_visible()
    expect(keep).to_be_checked()


def test_picking_a_person_before_access_prompts_for_a_choice(
    logged_in_page, api_session, board, ui_base_url, other_user
):
    page = logged_in_page
    open_share_dialog(page, board)
    modal = page.locator(MODAL)
    toggle = modal.get_by_role("group", name="Access for new people")
    expect(toggle.locator('button[aria-pressed="true"]')).to_have_count(0)

    page.fill("#board-share-search", other_user["display_name"])
    modal.locator(".board-share-result").first.click()

    hint = page.locator("#board-share-access-hint")
    expect(hint).to_be_visible()
    expect(hint).to_have_text("Choose Viewer or Editor first")
    assert members(api_session, ui_base_url, board) == []

    toggle.get_by_role("button", name="Viewer").click()
    expect(hint).to_be_hidden()
    modal.locator(".board-share-result").first.click()
    row = modal.locator(f'.board-share-member[data-user-id="{other_user["id"]}"]')
    expect(row.locator('button[aria-pressed="true"]')).to_have_text("Viewer")
    assert members(api_session, ui_base_url, board) == [(other_user["id"], "viewer")]


def test_owner_deletes_board_from_board_menu(logged_in_page, api_session, ui_base_url):
    response = api_session.post(
        f"{ui_base_url}/api/boards",
        json={"name": f"UI Delete Board {uuid.uuid4().hex[:8]}", "description": "Deleted by ui-tests"},
    )
    assert response.status_code == 201, response.text
    board = response.json()["board"]

    page = logged_in_page
    page.goto(f"/board.html?id={board['id']}")
    page.wait_for_function(
        "() => document.querySelector('#delete-board-menu-item')?.style.display === ''", timeout=8000
    )
    page.locator(".settings-dropdown .icon-link").click()
    page.locator("#delete-board-menu-item").click()

    expect(page.locator("#appModal")).to_be_visible()
    expect(page.locator("#appModalTitle")).to_have_text("Delete Board")
    page.locator("#appModalConfirmBtn").click()
    page.wait_for_url("**/index.html", timeout=8000)

    boards = api_session.get(f"{ui_base_url}/api/boards").json()["boards"]
    assert board["id"] not in [b["id"] for b in boards]


def test_delete_board_hidden_without_permission(logged_in_page, board):
    page = logged_in_page
    page.context.route(
        f"**/api/boards/{board['id']}/owner*",
        lambda route: route.fulfill(status=200, json={
            "success": True,
            "board": {"id": board["id"], "owner_id": 999999},
            "current_owner": {"id": 999999, "display_name": "Board Owner", "username": "board-owner"},
            "can_reassign": False,
            "can_delete": False,
            "available_users": [],
        }) if route.request.method == "GET" else route.fallback(),
    )
    page.goto(f"/board.html?id={board['id']}")
    page.wait_for_function(
        "() => document.querySelector('#share-board-menu-item')?.style.display === ''", timeout=8000
    )
    expect(page.locator("#delete-board-menu-item")).to_be_hidden()
    expect(page.locator("#mobile-delete-board-menu-item")).to_be_hidden()
