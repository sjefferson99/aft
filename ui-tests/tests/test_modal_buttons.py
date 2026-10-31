"""UI tests for the compact modal buttons."""
import pytest


@pytest.fixture
def card(api_session, ui_base_url, column):
    response = api_session.post(
        f"{ui_base_url}/api/columns/{column['id']}/cards", json={"title": "Modal button card"}
    )
    assert response.status_code == 201, response.text
    return response.json()["card"]


def _open_edit_modal(page, board_id, card_id, width, height=800):
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"/board.html?id={board_id}")
    page.locator(f'.card[data-card-id="{card_id}"]').click()
    page.locator("#edit-card-modal #edit-card-title").wait_for(state="visible", timeout=8000)


@pytest.mark.ui
def test_edit_card_buttons_leave_room_on_mobile(logged_in_page, column, card):
    """On a phone the actions take two rows at most, as icons with accessible names."""
    page = logged_in_page
    _open_edit_modal(page, column["board_id"], card["id"], 375, 667)

    actions = page.locator("#edit-card-modal .modal-header-actions")
    assert actions.bounding_box()["height"] <= 80

    move_btn = page.locator("#move-card-detail-btn")
    assert move_btn.get_attribute("aria-label") == "Move"
    assert not move_btn.locator(".btn-label").is_visible()
    assert move_btn.locator(".btn-icon").is_visible()

    assert page.locator("#cancel-edit-card-btn").inner_text() == "Cancel"
    modal = page.locator("#edit-card-modal .modal-content")
    assert modal.evaluate("el => el.scrollWidth <= el.clientWidth")


@pytest.mark.ui
def test_edit_card_buttons_show_labels_on_desktop(logged_in_page, column, card):
    page = logged_in_page
    _open_edit_modal(page, column["board_id"], card["id"], 1280)

    assert page.locator("#move-card-detail-btn .btn-label").is_visible()
    assert page.locator("#move-card-detail-btn").bounding_box()["height"] <= 36


@pytest.mark.ui
def test_add_card_buttons_stay_in_one_row_on_mobile(logged_in_page, column):
    page = logged_in_page
    page.set_viewport_size({"width": 375, "height": 667})
    page.goto(f"/board.html?id={column['board_id']}")
    # The add card modal stays shut until the header has confirmed the database.
    page.wait_for_function(
        "() => window.boardManager?.hasLoadedBoardData && window.header?.dbConnected", timeout=8000
    )
    page.evaluate("id => window.boardManager.openAddCardModal(id)", column["id"])

    cancel = page.locator("#cancel-card-btn").bounding_box()
    create = page.locator("#add-card-modal .modal-actions .btn-primary").bounding_box()
    assert cancel["y"] == create["y"]
