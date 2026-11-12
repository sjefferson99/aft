"""UI tests for sideways board auto-scroll while dragging a card (#684).

Holding a dragged card near the left or right edge of the board scrolls the
columns, so a card can be dropped in a column that started off screen. The
desktop test uses a native drag, the mobile test the long-press touch drag.
"""
import time
import uuid
import pytest


COLUMN_COUNT = 7


@pytest.fixture
def wide_board(api_session, ui_base_url):
    """A board with more columns than fit on screen and one card in the first."""
    base = ui_base_url
    board_resp = api_session.post(
        f"{base}/api/boards", json={"name": f"Autoscroll Board {uuid.uuid4().hex[:8]}"}
    )
    assert board_resp.status_code == 201
    board = board_resp.json()["board"]
    style_resp = api_session.put(
        f"{base}/api/boards/{board['id']}/settings/working-style", json={"value": "kanban"}
    )
    assert style_resp.status_code == 200

    columns = []
    for i in range(COLUMN_COUNT):
        col_resp = api_session.post(f"{base}/api/boards/{board['id']}/columns", json={"name": f"Column {i}"})
        assert col_resp.status_code == 201
        columns.append(col_resp.json()["column"])

    card_resp = api_session.post(f"{base}/api/columns/{columns[0]['id']}/cards", json={"title": "Travelling card"})
    assert card_resp.status_code == 201

    yield {"board": board, "columns": columns, "card": card_resp.json()["card"]}

    api_session.delete(f"{base}/api/boards/{board['id']}")


def _open_board(page, data):
    page.goto(f"/board.html?id={data['board']['id']}")
    page.locator(f'.card[data-card-id="{data["card"]["id"]}"]').wait_for(state="visible", timeout=5000)
    scroll = _scroll_state(page)
    assert scroll["max"] > 0, "the board must overflow sideways for this test"
    assert scroll["left"] == 0
    return scroll


def _scroll_state(page):
    return page.locator(".columns-container").evaluate(
        "el => ({ left: el.scrollLeft, max: el.scrollWidth - el.clientWidth, rect: el.getBoundingClientRect().toJSON() })"
    )


def _box_center(locator):
    box = locator.bounding_box()
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def _wait_for_card_column(api_session, ui_base_url, card_id, column_id):
    deadline = time.monotonic() + 8
    current = None
    while time.monotonic() < deadline:
        current = api_session.get(f"{ui_base_url}/api/cards/{card_id}").json()["card"]["column_id"]
        if current == column_id:
            return
        time.sleep(0.2)
    assert current == column_id


def _hold_near_right_edge(page, move, y):
    """Keep nudging the pointer at the right edge until the board has scrolled to its end.

    Real browsers repeat dragover while the pointer is still; Playwright only
    sends one per move, so the pointer jiggles by a pixel.
    """
    scroll = _scroll_state(page)
    edge_x = scroll["rect"]["right"] - 12
    deadline = time.monotonic() + 15
    nudge = 0
    while time.monotonic() < deadline:
        move(edge_x - nudge, y)
        nudge = 1 - nudge
        page.wait_for_timeout(100)
        scroll = _scroll_state(page)
        if scroll["left"] >= scroll["max"] - 1:
            return scroll
    raise AssertionError(f"board did not scroll to its end: {scroll}")


@pytest.mark.ui
def test_native_drag_scrolls_board_sideways(logged_in_page, api_session, ui_base_url, wide_board):
    page = logged_in_page
    data = wide_board
    page.set_viewport_size({"width": 1280, "height": 800})
    _open_board(page, data)

    card_id = data["card"]["id"]
    last_column_id = data["columns"][-1]["id"]
    start_x, start_y = _box_center(page.locator(f'.card[data-card-id="{card_id}"] .card-title'))

    page.mouse.move(start_x, start_y)
    page.mouse.down()
    page.mouse.move(start_x + 20, start_y + 5, steps=4)

    _hold_near_right_edge(page, page.mouse.move, start_y + 5)

    target_x, target_y = _box_center(page.locator(f'.column-cards[data-column-id="{last_column_id}"]'))
    page.mouse.move(target_x, target_y, steps=4)
    page.mouse.up()

    _wait_for_card_column(api_session, ui_base_url, card_id, last_column_id)
    assert not page.locator(".columns-container.board-auto-scrolling").count()


@pytest.mark.ui
@pytest.mark.browser_context_args(has_touch=True, is_mobile=True, viewport={"width": 412, "height": 915})
def test_touch_drag_scrolls_board_sideways(logged_in_page, api_session, ui_base_url, wide_board):
    page = logged_in_page
    data = wide_board
    _open_board(page, data)

    card_id = data["card"]["id"]
    last_column_id = data["columns"][-1]["id"]
    start_x, start_y = _box_center(page.locator(f'.card[data-card-id="{card_id}"] .card-title'))
    cdp = page.context.new_cdp_session(page)

    def touch(kind, x, y):
        points = [] if kind == "touchEnd" else [{"x": x, "y": y, "id": 1}]
        cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": points})

    touch("touchStart", start_x, start_y)
    page.wait_for_timeout(700)  # past the long press that arms the drag
    for step in range(1, 5):
        touch("touchMove", start_x + step * 5, start_y + step * 2)

    _hold_near_right_edge(page, lambda x, y: touch("touchMove", x, y), start_y + 8)

    # The card follows the finger as columns pass under it, so it is already
    # in a later column before the finger moves again.
    assert page.locator(
        f'.column-cards[data-column-id="{data["columns"][0]["id"]}"] .card[data-card-id="{card_id}"]'
    ).count() == 0

    target_x, target_y = _box_center(page.locator(f'.column-cards[data-column-id="{last_column_id}"]'))
    touch("touchMove", target_x, target_y)
    page.wait_for_timeout(100)
    touch("touchEnd", target_x, target_y)

    _wait_for_card_column(api_session, ui_base_url, card_id, last_column_id)
    assert not page.locator(".columns-container.board-auto-scrolling").count()
