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
    """Load the board, then rename a column via the API and wait for the WebSocket re-render.

    Card events are patched in place (issue #525 item 2.3c); a column rename
    still reloads and re-renders the whole board.
    """
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"/board.html?id={data['board']['id']}")
    page.locator(f'.card[data-card-id="{data["short_card"]["id"]}"]').wait_for(state="visible", timeout=5000)

    marker = f"Rerender marker {uuid.uuid4().hex[:6]}"
    resp = api_session.patch(
        f"{ui_base_url}/api/columns/{data['col_b']['id']}", json={"name": marker}
    )
    assert resp.status_code == 200
    page.locator(".column-header h4", has_text=marker).wait_for(state="visible", timeout=8000)


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


# --- Incremental card patching (issue #525 item 2.3c) ---
#
# Card events from other clients are patched into the board in place instead
# of reloading it. The test's own browser receives the API changes made here
# as a second client. A spy on boardManager.loadBoard/renderBoard checks that
# no full reload happened.

# Longer than the 150 ms reload debounce, so a fallback reload has started.
RELOAD_SETTLE_MS = 600


def _open_board_for_patching(page, board_id, query=""):
    """Load the board, wait until its socket has joined the board room, and spy on reloads."""
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"/board.html?id={board_id}{query}")
    # The assignee-filter visibility watcher re-renders once during start-up.
    page.wait_for_function(
        "() => window.boardManager?.hasLoadedBoardData"
        " && !window.boardManager.currentLoadController"
        " && !window.boardManager.assigneeFilterVisibilityWatcherId"
        " && window.boardManager.wsManager?.socket?.connected",
        timeout=8000,
    )
    # Re-joining is idempotent; waiting for room_joined guarantees the next
    # broadcast reaches this page.
    page.evaluate(
        """() => new Promise((resolve) => {
            const bm = window.boardManager;
            bm.wsManager.socket.once('room_joined', resolve);
            bm.wsManager.socket.emit('join_board', { board_id: bm.boardId });
        })"""
    )
    page.evaluate(
        """() => {
            const bm = window.boardManager;
            window.__aftLoadBoardCalls = 0;
            window.__aftRenderBoardCalls = 0;
            const loadBoard = bm.loadBoard.bind(bm);
            const renderBoard = bm.renderBoard.bind(bm);
            bm.loadBoard = (...args) => { window.__aftLoadBoardCalls += 1; return loadBoard(...args); };
            bm.renderBoard = (...args) => { window.__aftRenderBoardCalls += 1; return renderBoard(...args); };
        }"""
    )


def _reload_calls(page):
    page.wait_for_timeout(RELOAD_SETTLE_MS)
    return page.evaluate("() => [window.__aftLoadBoardCalls, window.__aftRenderBoardCalls]")


def _assert_no_reload(page):
    assert _reload_calls(page) == [0, 0], "Card event should be patched in, not trigger a full reload"


def _assert_board_matches_api(page, api_session, ui_base_url, board_id, shown=lambda card: True, count=None):
    """Each column's card nodes, data-order values and count match a fresh board fetch."""
    resp = api_session.get(f"{ui_base_url}/api/boards/{board_id}/cards?archived=false")
    assert resp.status_code == 200
    for column in resp.json()["board"]["columns"]:
        expected = [(card["id"], str(card["order"])) for card in column["cards"] if shown(card)]
        actual = page.evaluate(
            """(columnId) => Array.from(
                document.querySelectorAll(`.column-cards[data-column-id="${columnId}"] .card[data-card-id]`),
                (el) => [Number(el.dataset.cardId), el.dataset.order]
            )""",
            column["id"],
        )
        assert [tuple(pair) for pair in actual] == expected, f"column {column['id']} cards/order"
        expected_count = count(column) if count else str(len(expected))
        count_text = page.locator(f'.column[data-column-id="{column["id"]}"] .card-count').text_content()
        assert count_text == f"({expected_count})", f"column {column['id']} count"


def _card(page, card_id):
    return page.locator(f'.card[data-card-id="{card_id}"]')


@pytest.mark.ui
def test_created_card_is_patched_in_order(logged_in_page, api_session, ui_base_url, board_with_cards):
    page = logged_in_page
    data = board_with_cards
    _open_board_for_patching(page, data["board"]["id"])

    resp = api_session.post(
        f"{ui_base_url}/api/columns/{data['col_a']['id']}/cards", json={"title": "Patched top card", "order": 0}
    )
    assert resp.status_code == 201
    card_id = resp.json()["card"]["id"]
    _card(page, card_id).wait_for(state="visible", timeout=8000)

    first_id = page.evaluate(
        "(columnId) => Number(document.querySelector(`.column-cards[data-column-id=\"${columnId}\"] .card`).dataset.cardId)",
        data["col_a"]["id"],
    )
    assert first_id == card_id
    _assert_no_reload(page)
    _assert_board_matches_api(page, api_session, ui_base_url, data["board"]["id"])


@pytest.mark.ui
def test_edited_card_is_patched(logged_in_page, api_session, ui_base_url, board_with_cards):
    page = logged_in_page
    data = board_with_cards
    _open_board_for_patching(page, data["board"]["id"])

    card_id = data["short_card"]["id"]
    resp = api_session.patch(f"{ui_base_url}/api/cards/{card_id}", json={"title": "Renamed short card"})
    assert resp.status_code == 200
    _card(page, card_id).locator(".card-title", has_text="Renamed short card").wait_for(timeout=8000)

    _assert_no_reload(page)
    _assert_board_matches_api(page, api_session, ui_base_url, data["board"]["id"])


@pytest.mark.ui
def test_moved_card_is_patched(logged_in_page, api_session, ui_base_url, board_with_cards):
    page = logged_in_page
    data = board_with_cards
    _open_board_for_patching(page, data["board"]["id"])

    card_id = data["short_card"]["id"]
    col_b_id = data["col_b"]["id"]
    resp = api_session.patch(f"{ui_base_url}/api/cards/{card_id}", json={"column_id": col_b_id, "order": 0})
    assert resp.status_code == 200
    page.locator(f'.column-cards[data-column-id="{col_b_id}"] .card[data-card-id="{card_id}"]').wait_for(
        timeout=8000
    )

    _assert_no_reload(page)
    _assert_board_matches_api(page, api_session, ui_base_url, data["board"]["id"])


@pytest.mark.ui
def test_deleted_card_is_patched(logged_in_page, api_session, ui_base_url, board_with_cards):
    page = logged_in_page
    data = board_with_cards
    _open_board_for_patching(page, data["board"]["id"])

    card_id = data["short_card"]["id"]
    assert api_session.delete(f"{ui_base_url}/api/cards/{card_id}").status_code == 200
    _card(page, card_id).wait_for(state="detached", timeout=8000)

    _assert_no_reload(page)
    _assert_board_matches_api(page, api_session, ui_base_url, data["board"]["id"])


@pytest.mark.ui
def test_archived_and_unarchived_card_are_patched(logged_in_page, api_session, ui_base_url, board_with_cards):
    page = logged_in_page
    data = board_with_cards
    _open_board_for_patching(page, data["board"]["id"])

    card_id = data["short_card"]["id"]
    assert api_session.patch(f"{ui_base_url}/api/cards/{card_id}/archive").status_code == 200
    _card(page, card_id).wait_for(state="detached", timeout=8000)
    _assert_no_reload(page)
    _assert_board_matches_api(page, api_session, ui_base_url, data["board"]["id"])

    assert api_session.patch(f"{ui_base_url}/api/cards/{card_id}/unarchive").status_code == 200
    _card(page, card_id).wait_for(state="visible", timeout=8000)
    _assert_no_reload(page)
    _assert_board_matches_api(page, api_session, ui_base_url, data["board"]["id"])


@pytest.mark.ui
def test_agile_done_toggle_is_patched(logged_in_page, api_session, ui_base_url, board_with_cards):
    """Other clients see done toggles; before 2.3c nothing listened for card_done_status_changed."""
    page = logged_in_page
    data = board_with_cards
    board_id = data["board"]["id"]
    resp = api_session.put(f"{ui_base_url}/api/boards/{board_id}/settings/working-style", json={"value": "agile"})
    assert resp.status_code == 200
    _open_board_for_patching(page, board_id)

    def agile_count(column):
        return f"{sum(1 for card in column['cards'] if card['done'])}/{len(column['cards'])}"

    card_id = data["short_card"]["id"]
    assert api_session.patch(f"{ui_base_url}/api/cards/{card_id}/done", json={"done": True}).status_code == 200
    _card(page, card_id).wait_for(state="detached", timeout=8000)
    _assert_no_reload(page)
    _assert_board_matches_api(
        page, api_session, ui_base_url, board_id, shown=lambda card: not card["done"], count=agile_count
    )

    assert api_session.patch(f"{ui_base_url}/api/cards/{card_id}/done", json={"done": False}).status_code == 200
    _card(page, card_id).wait_for(state="visible", timeout=8000)
    _assert_no_reload(page)
    _assert_board_matches_api(
        page, api_session, ui_base_url, board_id, shown=lambda card: not card["done"], count=agile_count
    )


@pytest.mark.ui
def test_patched_cards_keep_collapse_state(logged_in_page, api_session, ui_base_url, board_with_cards):
    page = logged_in_page
    data = board_with_cards
    _open_board_for_patching(page, data["board"]["id"])

    # A user-expanded card stays expanded when another client edits it.
    long_id = data["long_card"]["id"]
    page.wait_for_function(
        "id => document.querySelector(`.card[data-card-id=\"${id}\"]`)?.classList.contains('collapsed')",
        arg=long_id,
        timeout=5000,
    )
    _card(page, long_id).locator(".card-expand-btn").click()
    resp = api_session.patch(f"{ui_base_url}/api/cards/{long_id}", json={"title": "Edited long card"})
    assert resp.status_code == 200
    _card(page, long_id).locator(".card-title", has_text="Edited long card").wait_for(timeout=8000)
    page.wait_for_function(
        "id => document.querySelector(`.card[data-card-id=\"${id}\"]`)?.classList.contains('has-overflow')",
        arg=long_id,
        timeout=5000,
    )
    long_card = _card(page, long_id)
    assert "collapsed" not in (long_card.get_attribute("class") or "")
    assert long_card.locator(".card-expand-btn").get_attribute("aria-expanded") == "true"

    _assert_no_reload(page)

    # A card that grows past the collapse height as checklist items are added
    # becomes collapsed.
    resp = api_session.post(f"{ui_base_url}/api/columns/{data['col_b']['id']}/cards", json={"title": "Tall card"})
    assert resp.status_code == 201
    new_id = resp.json()["card"]["id"]
    for i in range(CHECKLIST_ITEM_COUNT):
        item_resp = api_session.post(
            f"{ui_base_url}/api/cards/{new_id}/checklist-items",
            json={"name": f"Item {i}", "checked": False, "order": i},
        )
        assert item_resp.status_code == 201
    page.wait_for_function(
        "id => document.querySelector(`.card[data-card-id=\"${id}\"]`)?.classList.contains('collapsed')",
        arg=new_id,
        timeout=8000,
    )
    _assert_no_reload(page)


@pytest.mark.ui
def test_checklist_events_are_patched(logged_in_page, api_session, ui_base_url, board_with_cards):
    page = logged_in_page
    data = board_with_cards
    _open_board_for_patching(page, data["board"]["id"])

    card_id = data["short_card"]["id"]
    summary = _card(page, card_id).locator(".card-checklist-summary")

    resp = api_session.post(
        f"{ui_base_url}/api/cards/{card_id}/checklist-items", json={"name": "Patched item", "checked": False}
    )
    assert resp.status_code == 201
    item_id = resp.json()["checklist_item"]["id"]
    summary.filter(has_text="0/1 (0%)").wait_for(timeout=8000)
    _assert_no_reload(page)

    resp = api_session.patch(f"{ui_base_url}/api/checklist-items/{item_id}", json={"checked": True})
    assert resp.status_code == 200
    summary.filter(has_text="1/1 (100%)").wait_for(timeout=8000)
    assert _card(page, card_id).locator(".card-checklist-checkbox").is_checked()
    _assert_no_reload(page)

    assert api_session.delete(f"{ui_base_url}/api/checklist-items/{item_id}").status_code == 200
    _card(page, card_id).locator(".card-checklist").wait_for(state="detached", timeout=8000)
    _assert_no_reload(page)
    _assert_board_matches_api(page, api_session, ui_base_url, data["board"]["id"])


@pytest.mark.ui
def test_card_inserted_above_keeps_column_scroll_position(logged_in_page, api_session, ui_base_url, board_with_cards):
    page = logged_in_page
    data = board_with_cards
    col_b_id = data["col_b"]["id"]
    for i in range(30):
        resp = api_session.post(f"{ui_base_url}/api/columns/{col_b_id}/cards", json={"title": f"Filler {i}"})
        assert resp.status_code == 201
    _open_board_for_patching(page, data["board"]["id"])

    column = page.locator(f'.column-cards[data-column-id="{col_b_id}"]')
    assert column.evaluate("el => { el.scrollTop = el.scrollHeight / 2; return el.scrollTop; }") > 0
    anchor = page.locator(".card-title", has_text="Filler 20")
    before = anchor.bounding_box()["y"]

    resp = api_session.post(f"{ui_base_url}/api/columns/{col_b_id}/cards", json={"title": "Inserted above", "order": 0})
    assert resp.status_code == 201
    _card(page, resp.json()["card"]["id"]).wait_for(state="attached", timeout=8000)
    page.wait_for_timeout(100)

    assert abs(anchor.bounding_box()["y"] - before) <= 2, "Visible cards should not shift"
    _assert_no_reload(page)


@pytest.mark.ui
def test_card_event_reloads_when_search_filter_active(logged_in_page, api_session, ui_base_url, board_with_cards):
    """Search runs on the server, so with a search active the board reloads instead of patching."""
    page = logged_in_page
    data = board_with_cards
    _open_board_for_patching(page, data["board"]["id"], query="&q=card")

    resp = api_session.post(f"{ui_base_url}/api/columns/{data['col_a']['id']}/cards", json={"title": "Search card"})
    assert resp.status_code == 201
    _card(page, resp.json()["card"]["id"]).wait_for(state="visible", timeout=8000)

    load_calls, _ = _reload_calls(page)
    assert load_calls >= 1


@pytest.mark.ui
def test_card_event_reloads_in_archived_view(logged_in_page, api_session, ui_base_url, board_with_cards):
    page = logged_in_page
    data = board_with_cards
    _open_board_for_patching(page, data["board"]["id"])
    page.evaluate("() => window.boardManager.toggleArchiveView()")
    page.wait_for_function(
        "() => window.boardManager.showArchived && !window.boardManager.currentLoadController", timeout=8000
    )
    page.evaluate("() => { window.__aftLoadBoardCalls = 0; window.__aftRenderBoardCalls = 0; }")

    card_id = data["short_card"]["id"]
    assert api_session.patch(f"{ui_base_url}/api/cards/{card_id}/archive").status_code == 200
    _card(page, card_id).wait_for(state="visible", timeout=8000)

    load_calls, _ = _reload_calls(page)
    assert load_calls >= 1
