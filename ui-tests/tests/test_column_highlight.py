"""UI tests for column highlighting (#414).

The column under the mouse is outlined, as that's where the N and M shortcuts
add a card, and the column a dragged card will drop into is highlighted more
clearly, in both board layouts.
"""
import uuid

import pytest

pytestmark = pytest.mark.ui


@pytest.fixture
def two_column_board(api_session, ui_base_url):
    base = ui_base_url
    response = api_session.post(f"{base}/api/boards", json={"name": f"Highlight {uuid.uuid4().hex[:8]}"})
    assert response.status_code == 201, response.text
    board = response.json()["board"]
    columns = []
    for name in ("From", "To"):
        response = api_session.post(f"{base}/api/boards/{board['id']}/columns", json={"name": name})
        assert response.status_code == 201, response.text
        columns.append(response.json()["column"])
    response = api_session.post(f"{base}/api/columns/{columns[0]['id']}/cards", json={"title": "Mover"})
    assert response.status_code == 201, response.text

    yield {"board": board, "columns": columns, "card": response.json()["card"]}

    api_session.delete(f"{base}/api/boards/{board['id']}")


def _center(locator):
    box = locator.bounding_box()
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def _classes(page, selector):
    return page.locator(selector).evaluate_all("els => els.map(el => el.dataset.columnId)")


def test_hovered_column_is_outlined(logged_in_page, two_column_board):
    page = logged_in_page
    page.set_viewport_size({"width": 1280, "height": 800})
    data = two_column_board
    page.goto(f"/board.html?id={data['board']['id']}")
    from_id, to_id = (str(column["id"]) for column in data["columns"])
    to_column = page.locator(f'.column[data-column-id="{to_id}"]')
    to_column.wait_for(state="visible", timeout=8000)

    page.mouse.move(*_center(to_column))
    assert _classes(page, ".column.column-hovered") == [to_id]
    shadow = to_column.evaluate("el => getComputedStyle(el).boxShadow")
    assert shadow != "none"

    page.mouse.move(*_center(page.locator(f'.column[data-column-id="{from_id}"]')))
    assert _classes(page, ".column.column-hovered") == [from_id]

    page.mouse.move(5, 790)
    page.wait_for_timeout(100)
    assert _classes(page, ".column.column-hovered") == []


@pytest.mark.parametrize("layout", ["columns", "sections"])
def test_drop_target_column_is_highlighted_while_dragging(
    logged_in_page, api_session, ui_base_url, two_column_board, layout
):
    data = two_column_board
    response = api_session.put(
        f"{ui_base_url}/api/boards/{data['board']['id']}/settings/layout", json={"value": layout}
    )
    assert response.status_code == 200, response.text
    page = logged_in_page
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"/board.html?id={data['board']['id']}")
    card = page.locator(f'.card[data-card-id="{data["card"]["id"]}"] .card-title')
    card.wait_for(state="visible", timeout=8000)
    from_id, to_id = (str(column["id"]) for column in data["columns"])

    start_x, start_y = _center(card)
    page.mouse.move(start_x, start_y)
    page.mouse.down()
    page.mouse.move(start_x + 10, start_y + 5, steps=3)
    page.wait_for_timeout(100)
    assert _classes(page, ".column.column-drop-target") == [from_id]

    target_x, target_y = _center(page.locator(f'.column-cards[data-column-id="{to_id}"]'))
    page.mouse.move(target_x, target_y, steps=6)
    page.wait_for_timeout(100)
    assert _classes(page, ".column.column-drop-target") == [to_id]

    page.mouse.up()
    page.wait_for_timeout(300)
    assert _classes(page, ".column.column-drop-target") == []


@pytest.mark.browser_context_args(has_touch=True, is_mobile=True, viewport={"width": 412, "height": 915})
def test_tapping_a_column_does_not_outline_it(logged_in_page, two_column_board):
    page = logged_in_page
    data = two_column_board
    page.goto(f"/board.html?id={data['board']['id']}")
    to_id = str(data["columns"][1]["id"])
    header = page.locator(f'.column[data-column-id="{to_id}"] .column-header')
    header.scroll_into_view_if_needed()
    header.wait_for(state="visible", timeout=8000)
    # Chromium's touch emulation reports a mouse over the target before the
    # touch, so this also checks touch boards ignore mouse hover. Its mouse
    # may already rest on a column, so only check that the tap doesn't move
    # the outline.
    x, y = _center(header)
    cdp = page.context.new_cdp_session(page)
    cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y, "id": 1}]})
    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    page.wait_for_timeout(200)
    assert to_id not in _classes(page, ".column.column-hovered")
