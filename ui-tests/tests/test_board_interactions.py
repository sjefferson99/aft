"""UI tests for column/card controls on the board.

Board controls are handled by delegated listeners on #board-container rather
than per-element listeners re-attached on every render (issue #525 item 2.1).
Each interaction is exercised after a WebSocket-triggered re-render to check
the handlers survive the board's innerHTML being replaced.
"""
import time
import uuid
import pytest


CHECKLIST_ITEM_COUNT = 8


@pytest.fixture
def board_with_cards(api_session, ui_base_url):
    """Create a board with two columns, a card tall enough to collapse, and a short card."""
    base = ui_base_url
    board_resp = api_session.post(
        f"{base}/api/boards",
        json={"name": f"Interactions Board {uuid.uuid4().hex[:8]}"},
    )
    assert board_resp.status_code == 201
    board = board_resp.json()["board"]

    columns = []
    for name in ("Column A", "Column B"):
        col_resp = api_session.post(f"{base}/api/boards/{board['id']}/columns", json={"name": name})
        assert col_resp.status_code == 201
        columns.append(col_resp.json()["column"])

    long_card_resp = api_session.post(
        f"{base}/api/columns/{columns[0]['id']}/cards",
        json={"title": "Long card"},
    )
    assert long_card_resp.status_code == 201
    long_card = long_card_resp.json()["card"]

    # Enough checklist items to push the card past --card-collapse-height.
    for i in range(CHECKLIST_ITEM_COUNT):
        item_resp = api_session.post(
            f"{base}/api/cards/{long_card['id']}/checklist-items",
            json={"name": f"Item {i}", "checked": False, "order": i},
        )
        assert item_resp.status_code == 201

    short_card_resp = api_session.post(
        f"{base}/api/columns/{columns[0]['id']}/cards", json={"title": "Short card"}
    )
    assert short_card_resp.status_code == 201
    short_card = short_card_resp.json()["card"]

    yield {
        "board": board,
        "col_a": columns[0],
        "col_b": columns[1],
        "long_card": long_card,
        "short_card": short_card,
    }

    api_session.delete(f"{base}/api/boards/{board['id']}")


def _open_board_and_force_rerender(page, api_session, ui_base_url, data):
    """Load the board, then add a card via the API and wait for the WebSocket re-render."""
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"/board.html?id={data['board']['id']}")
    page.locator(f'.card[data-card-id="{data["short_card"]["id"]}"]').wait_for(state="visible", timeout=5000)

    marker = f"Rerender marker {uuid.uuid4().hex[:6]}"
    resp = api_session.post(
        f"{ui_base_url}/api/columns/{data['col_b']['id']}/cards", json={"title": marker}
    )
    assert resp.status_code == 201
    page.locator(".card-title", has_text=marker).wait_for(state="visible", timeout=8000)


@pytest.mark.ui
def test_card_click_opens_edit_modal_after_rerender(logged_in_page, api_session, ui_base_url, board_with_cards):
    page = logged_in_page
    data = board_with_cards
    _open_board_and_force_rerender(page, api_session, ui_base_url, data)

    page.locator(f'.card[data-card-id="{data["short_card"]["id"]}"] .card-title').click()
    page.locator("#edit-card-modal").wait_for(state="visible", timeout=5000)


@pytest.mark.ui
def test_expand_button_toggles_without_opening_card(logged_in_page, api_session, ui_base_url, board_with_cards):
    page = logged_in_page
    data = board_with_cards
    _open_board_and_force_rerender(page, api_session, ui_base_url, data)

    card = page.locator(f'.card[data-card-id="{data["long_card"]["id"]}"]')
    expand_btn = card.locator(".card-expand-btn")
    page.wait_for_function(
        "id => document.querySelector(`.card[data-card-id=\"${id}\"]`)?.classList.contains('collapsed')",
        arg=data["long_card"]["id"],
        timeout=5000,
    )

    expand_btn.click()
    assert "collapsed" not in (card.get_attribute("class") or "")
    assert expand_btn.get_attribute("aria-expanded") == "true"
    assert expand_btn.text_content().strip() == "Show less..."

    expand_btn.click()
    assert "collapsed" in (card.get_attribute("class") or "")
    assert expand_btn.get_attribute("aria-expanded") == "false"
    assert page.locator("#edit-card-modal").count() == 0, "Expand button must not open the card"


@pytest.mark.ui
def test_card_checklist_checkbox_updates_summary(logged_in_page, api_session, ui_base_url, board_with_cards):
    page = logged_in_page
    data = board_with_cards
    _open_board_and_force_rerender(page, api_session, ui_base_url, data)

    card = page.locator(f'.card[data-card-id="{data["long_card"]["id"]}"]')
    card.locator(".card-expand-btn").click()
    card.locator(".card-checklist-checkbox").first.click()

    summary = card.locator(".card-checklist-summary")
    page.wait_for_function(
        f"el => el.textContent.trim().startsWith('1/{CHECKLIST_ITEM_COUNT} ')",
        arg=summary.element_handle(),
        timeout=5000,
    )
    assert "checked" in (card.locator(".card-checklist-name").first.get_attribute("class") or "")
    assert page.locator("#edit-card-modal").count() == 0, "Checkbox must not open the card"

    items = api_session.get(f"{ui_base_url}/api/cards/{data['long_card']['id']}").json()["card"]["checklist_items"]
    assert sum(1 for item in items if item["checked"]) == 1


@pytest.mark.ui
def test_column_menu_toggles_and_rename_opens_modal(logged_in_page, api_session, ui_base_url, board_with_cards):
    page = logged_in_page
    data = board_with_cards
    _open_board_and_force_rerender(page, api_session, ui_base_url, data)

    col_a_id = data["col_a"]["id"]
    col_b_id = data["col_b"]["id"]
    dropdown_a = page.locator(f'.column-menu-dropdown[data-column-id="{col_a_id}"]')
    dropdown_b = page.locator(f'.column-menu-dropdown[data-column-id="{col_b_id}"]')

    page.locator(f'.column-menu-btn[data-column-id="{col_a_id}"]').click()
    dropdown_a.wait_for(state="visible", timeout=5000)

    # Opening another column's menu closes the first.
    page.locator(f'.column-menu-btn[data-column-id="{col_b_id}"]').click()
    dropdown_b.wait_for(state="visible", timeout=5000)
    dropdown_a.wait_for(state="hidden", timeout=5000)

    # Clicking the same button again closes it.
    page.locator(f'.column-menu-btn[data-column-id="{col_b_id}"]').click()
    dropdown_b.wait_for(state="hidden", timeout=5000)

    page.locator(f'.column-menu-btn[data-column-id="{col_a_id}"]').click()
    dropdown_a.wait_for(state="visible", timeout=5000)
    dropdown_a.locator(".column-menu-rename-btn").dispatch_event("click")

    page.locator("#edit-column-modal").wait_for(state="visible", timeout=5000)
    dropdown_a.wait_for(state="hidden", timeout=5000)


@pytest.mark.ui
def test_add_card_buttons_open_modal(logged_in_page, api_session, ui_base_url, board_with_cards):
    page = logged_in_page
    data = board_with_cards
    _open_board_and_force_rerender(page, api_session, ui_base_url, data)

    col_b_id = data["col_b"]["id"]
    page.locator(f'.add-card-btn[data-column-id="{col_b_id}"]').click()
    modal = page.locator("#add-card-modal")
    modal.wait_for(state="visible", timeout=5000)


@pytest.mark.ui
def test_delete_card_button_deletes_card(logged_in_page, api_session, ui_base_url, board_with_cards):
    page = logged_in_page
    data = board_with_cards
    _open_board_and_force_rerender(page, api_session, ui_base_url, data)

    card = page.locator(f'.card[data-card-id="{data["short_card"]["id"]}"]')
    card.hover()
    card.locator(".card-delete-btn").click()
    page.locator("#appModalConfirmBtn").click()

    card.wait_for(state="detached", timeout=8000)
    assert page.locator("#edit-card-modal").count() == 0, "Delete button must not open the card"


@pytest.mark.ui
def test_drag_card_to_other_column(logged_in_page, api_session, ui_base_url, board_with_cards):
    page = logged_in_page
    data = board_with_cards
    _open_board_and_force_rerender(page, api_session, ui_base_url, data)

    card_id = data["short_card"]["id"]
    col_b_id = data["col_b"]["id"]
    page.locator(f'.card[data-card-id="{card_id}"] .card-title').drag_to(
        page.locator(f'.add-card-btn[data-column-id="{col_b_id}"]')
    )

    page.locator(
        f'.column-cards[data-column-id="{col_b_id}"] .card[data-card-id="{card_id}"]'
    ).wait_for(state="attached", timeout=8000)

    # The DOM moves before the PATCH lands; poll the API rather than assume a fixed delay.
    deadline = time.monotonic() + 8
    column_id = None
    while time.monotonic() < deadline:
        column_id = api_session.get(f"{ui_base_url}/api/cards/{card_id}").json()["card"]["column_id"]
        if column_id == col_b_id:
            break
        page.wait_for_timeout(200)
    assert column_id == col_b_id
