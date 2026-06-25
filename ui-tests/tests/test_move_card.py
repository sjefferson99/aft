"""UI tests for the move card and move all cards functionality."""
import uuid
import pytest


@pytest.fixture
def board_with_two_columns(api_session, ui_base_url):
    """Create a board with two columns and one card in the first column."""
    base = ui_base_url
    board_resp = api_session.post(
        f"{base}/api/boards",
        json={"name": f"Move Test Board {uuid.uuid4().hex[:8]}"},
    )
    assert board_resp.status_code == 201
    board = board_resp.json()["board"]

    col_a_resp = api_session.post(
        f"{base}/api/boards/{board['id']}/columns", json={"name": "Column A"}
    )
    assert col_a_resp.status_code == 201
    col_a = col_a_resp.json()["column"]

    col_b_resp = api_session.post(
        f"{base}/api/boards/{board['id']}/columns", json={"name": "Column B"}
    )
    assert col_b_resp.status_code == 201
    col_b = col_b_resp.json()["column"]

    card_resp = api_session.post(
        f"{base}/api/columns/{col_a['id']}/cards", json={"title": "Card to Move"}
    )
    assert card_resp.status_code == 201
    card = card_resp.json()["card"]

    yield {"board": board, "col_a": col_a, "col_b": col_b, "card": card}

    api_session.delete(f"{base}/api/boards/{board['id']}")


def _open_move_card_modal_via_edit_modal(page, card_id):
    """On desktop, open the move card modal via the edit card modal's Move button."""
    page.locator(f'.card[data-card-id="{card_id}"]').click()
    edit_modal = page.locator("#edit-card-modal")
    edit_modal.wait_for(state="visible", timeout=5000)
    edit_modal.locator("#move-card-detail-btn").click()


@pytest.mark.ui
def test_move_card_button_not_on_card_on_desktop(logged_in_page, board_with_two_columns):
    """The card-level move button must be hidden on desktop (viewport > 900 px)."""
    page = logged_in_page
    data = board_with_two_columns
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"/board.html?id={data['board']['id']}")

    card_id = data["card"]["id"]
    move_btn = page.locator(f'.card[data-card-id="{card_id}"] .card-move-btn')
    move_btn.wait_for(state="attached", timeout=5000)
    assert not move_btn.is_visible(), "card-move-btn should be hidden on desktop"


@pytest.mark.ui
def test_move_button_in_edit_modal_on_desktop(logged_in_page, board_with_two_columns):
    """The Move button must be present in the edit card modal on desktop."""
    page = logged_in_page
    data = board_with_two_columns
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"/board.html?id={data['board']['id']}")

    card_id = data["card"]["id"]
    page.locator(f'.card[data-card-id="{card_id}"]').click()
    edit_modal = page.locator("#edit-card-modal")
    edit_modal.wait_for(state="visible", timeout=5000)

    move_btn = edit_modal.locator("#move-card-detail-btn")
    assert move_btn.is_visible(), "Move button should be visible in edit card modal on desktop"
    assert move_btn.text_content().strip() == "Move", "Move button label should be 'Move'"


@pytest.mark.ui
def test_move_card_button_visible_on_mobile(logged_in_page, board_with_two_columns):
    """The move-card button must be visible on the card itself on mobile (viewport <= 900 px)."""
    page = logged_in_page
    data = board_with_two_columns
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"/board.html?id={data['board']['id']}")

    card_id = data["card"]["id"]
    move_btn = page.locator(f'.card[data-card-id="{card_id}"] .card-move-btn')
    move_btn.wait_for(state="visible", timeout=5000)
    assert move_btn.is_visible(), "card-move-btn should be visible on mobile"


@pytest.mark.ui
def test_move_card_modal_shows_board_picker(logged_in_page, board_with_two_columns):
    """Clicking Move in the edit modal opens a move modal that contains a board selector."""
    page = logged_in_page
    data = board_with_two_columns
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"/board.html?id={data['board']['id']}")

    _open_move_card_modal_via_edit_modal(page, data["card"]["id"])

    modal = page.locator("#move-card-modal")
    modal.wait_for(state="visible", timeout=5000)

    board_select = modal.locator("#move-card-target-board")
    assert board_select.is_visible(), "Board picker should be visible in move card modal"

    column_select = modal.locator("#move-card-target-column")
    assert column_select.is_visible(), "Column picker should be visible in move card modal"


@pytest.mark.ui
def test_move_card_modal_has_correct_aria_attributes(logged_in_page, board_with_two_columns):
    """Move card modal must carry the required accessibility attributes."""
    page = logged_in_page
    data = board_with_two_columns
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"/board.html?id={data['board']['id']}")

    _open_move_card_modal_via_edit_modal(page, data["card"]["id"])

    modal = page.locator("#move-card-modal")
    modal.wait_for(state="visible", timeout=5000)

    assert modal.get_attribute("role") == "dialog"
    assert modal.get_attribute("aria-modal") == "true"
    assert modal.get_attribute("aria-labelledby") == "move-card-modal-title"
    assert modal.get_attribute("aria-describedby") == "move-card-modal-desc"


@pytest.mark.ui
def test_move_card_modal_defaults_to_current_board(logged_in_page, board_with_two_columns):
    """The board picker defaults to the board the card currently lives on."""
    page = logged_in_page
    data = board_with_two_columns
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"/board.html?id={data['board']['id']}")

    _open_move_card_modal_via_edit_modal(page, data["card"]["id"])

    modal = page.locator("#move-card-modal")
    modal.wait_for(state="visible", timeout=5000)

    selected_board_id = modal.locator("#move-card-target-board").input_value()
    assert selected_board_id == str(data["board"]["id"]), (
        f"Board picker should default to current board {data['board']['id']}, "
        f"got {selected_board_id}"
    )


@pytest.mark.ui
def test_move_card_same_board_via_modal(logged_in_page, board_with_two_columns):
    """Completing the move card modal moves the card to the selected column."""
    page = logged_in_page
    data = board_with_two_columns
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"/board.html?id={data['board']['id']}")

    card_id = data["card"]["id"]
    col_b_id = data["col_b"]["id"]

    _open_move_card_modal_via_edit_modal(page, card_id)

    modal = page.locator("#move-card-modal")
    modal.wait_for(state="visible", timeout=5000)

    # Board is already on current board; select Column B
    modal.locator("#move-card-target-column").select_option(str(col_b_id))
    modal.locator("#move-card-position").select_option("bottom")
    modal.locator("button[type='submit']").click()

    # Modal should close and card should appear in Column B
    modal.wait_for(state="detached", timeout=8000)
    card_in_col_b = page.locator(
        f'.column-cards[data-column-id="{col_b_id}"] .card[data-card-id="{card_id}"]'
    )
    card_in_col_b.wait_for(state="visible", timeout=8000)


@pytest.mark.ui
def test_move_all_cards_modal_shows_board_picker(logged_in_page, board_with_two_columns):
    """The move-all-cards modal opened from the column menu contains a board picker."""
    page = logged_in_page
    data = board_with_two_columns
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"/board.html?id={data['board']['id']}")

    col_a_id = data["col_a"]["id"]

    # Open the column context menu; dispatch_event fires the handler immediately
    # without Playwright's post-visible stability wait, avoiding a race where the
    # board re-renders (clearing the .show class) before the click completes.
    move_all_btn = page.locator(f'.column-move-all-cards-btn[data-column-id="{col_a_id}"]')
    page.locator(f'.column-menu-btn[data-column-id="{col_a_id}"]').click()
    move_all_btn.wait_for(state="visible", timeout=5000)
    move_all_btn.dispatch_event("click")

    modal = page.locator("#move-all-cards-modal")
    modal.wait_for(state="visible", timeout=5000)

    assert modal.locator("#move-all-target-board").is_visible(), (
        "Board picker should be present in move-all-cards modal"
    )
    assert modal.locator("#target-column-select").is_visible(), (
        "Column picker should be present in move-all-cards modal"
    )


@pytest.mark.ui
def test_move_all_cards_modal_has_correct_aria_attributes(logged_in_page, board_with_two_columns):
    """Move all cards modal must carry the required accessibility attributes."""
    page = logged_in_page
    data = board_with_two_columns
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"/board.html?id={data['board']['id']}")

    col_a_id = data["col_a"]["id"]
    move_all_btn = page.locator(f'.column-move-all-cards-btn[data-column-id="{col_a_id}"]')
    page.locator(f'.column-menu-btn[data-column-id="{col_a_id}"]').click()
    move_all_btn.wait_for(state="visible", timeout=5000)
    move_all_btn.dispatch_event("click")

    modal = page.locator("#move-all-cards-modal")
    modal.wait_for(state="visible", timeout=5000)

    assert modal.get_attribute("role") == "dialog"
    assert modal.get_attribute("aria-modal") == "true"
    assert modal.get_attribute("aria-labelledby") == "move-all-cards-modal-title"
    assert modal.get_attribute("aria-describedby") == "move-all-cards-modal-desc"
