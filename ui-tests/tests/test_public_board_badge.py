"""UI tests for the compact public board badge and the Copy Public Link menu item."""
import uuid
import pytest


@pytest.fixture
def public_board(api_session, ui_base_url):
    board_resp = api_session.post(
        f"{ui_base_url}/api/boards", json={"name": f"Public Badge {uuid.uuid4().hex[:8]}"}
    )
    assert board_resp.status_code == 201
    board_id = board_resp.json()["board"]["id"]
    public_resp = api_session.patch(f"{ui_base_url}/api/boards/{board_id}", json={"is_public": True})
    assert public_resp.status_code == 200
    yield public_resp.json()["board"]
    api_session.delete(f"{ui_base_url}/api/boards/{board_id}")


def _open_board(page, board_id):
    page.goto(f"/board.html?id={board_id}")
    page.wait_for_function("() => window.boardManager?.hasLoadedBoardData && window.header", timeout=8000)


def _copied_text(page):
    return page.evaluate("() => navigator.clipboard.readText()")


@pytest.mark.ui
def test_badge_is_compact_and_copies_link(logged_in_page, public_board, ui_base_url):
    page = logged_in_page
    page.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=ui_base_url)
    _open_board(page, public_board["id"])

    badge = page.locator("#public-board-badge-btn")
    badge.wait_for(state="visible", timeout=8000)
    assert badge.inner_text() == "P"
    box = badge.bounding_box()
    assert box["width"] <= 24 and box["height"] <= 24

    badge.click()
    assert _copied_text(page).endswith(f"/public-board.html?slug={public_board['public_slug']}")


@pytest.mark.ui
def test_settings_menu_copies_public_link(logged_in_page, public_board, ui_base_url):
    page = logged_in_page
    page.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=ui_base_url)
    _open_board(page, public_board["id"])

    page.wait_for_function(
        "() => document.getElementById('copy-public-link-menu-item')?.style.display !== 'none'",
        timeout=8000,
    )
    page.evaluate("() => document.getElementById('copy-public-link-menu-item').click()")
    page.wait_for_function("() => document.querySelector('.header-inline-toast')", timeout=8000)
    assert _copied_text(page).endswith(f"/public-board.html?slug={public_board['public_slug']}")


@pytest.mark.ui
def test_mobile_badge_is_compact(logged_in_page, public_board):
    page = logged_in_page
    page.set_viewport_size({"width": 390, "height": 800})
    _open_board(page, public_board["id"])

    badge = page.locator("#public-board-badge-mobile-btn")
    badge.wait_for(state="visible", timeout=8000)
    assert badge.inner_text() == "P"
    assert badge.bounding_box()["width"] <= 24


@pytest.mark.ui
def test_private_board_has_no_badge_or_copy_item(logged_in_page, api_session, public_board, ui_base_url):
    page = logged_in_page
    resp = api_session.patch(f"{ui_base_url}/api/boards/{public_board['id']}", json={"is_public": False})
    assert resp.status_code == 200
    _open_board(page, public_board["id"])

    assert not page.locator("#public-board-badge-btn").is_visible()
    assert page.locator("#copy-public-link-menu-item").evaluate("el => el.style.display") == "none"
