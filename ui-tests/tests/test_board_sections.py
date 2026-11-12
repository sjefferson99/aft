"""UI tests for the sections board layout (#297).

The Layout choice in the board menu turns columns into sections, only as tall
as their cards, stacked in lanes. Sections are dragged by their header, or
moved with the column menu. Lanes are as many as fit the board's width.
"""
import time
import uuid

import pytest

pytestmark = pytest.mark.ui

LAYOUT = "#toggle-board-layout-menu-item"
VISIBILITY = "#toggle-board-visibility-menu-item"


@pytest.fixture
def sections_board(api_session, ui_base_url):
    """A board with three columns; the first has more cards than the others."""
    base = ui_base_url
    response = api_session.post(f"{base}/api/boards", json={"name": f"Sections {uuid.uuid4().hex[:8]}"})
    assert response.status_code == 201, response.text
    board = response.json()["board"]

    columns = []
    for name in ("To do", "Doing", "Done"):
        response = api_session.post(f"{base}/api/boards/{board['id']}/columns", json={"name": name})
        assert response.status_code == 201, response.text
        columns.append(response.json()["column"])

    cards = []
    for index in range(5):
        response = api_session.post(
            f"{base}/api/columns/{columns[0]['id']}/cards", json={"title": f"Task {index}"}
        )
        assert response.status_code == 201, response.text
        cards.append(response.json()["card"])

    yield {"board": board, "columns": columns, "cards": cards}

    api_session.delete(f"{base}/api/boards/{board['id']}")


def _set_layout(api_session, ui_base_url, board_id, value):
    response = api_session.put(
        f"{ui_base_url}/api/boards/{board_id}/settings/layout", json={"value": value}
    )
    assert response.status_code == 200, response.text


def _save_sections(api_session, ui_base_url, board_id, sections):
    response = api_session.put(
        f"{ui_base_url}/api/boards/{board_id}/section-layout", json={"sections": sections}
    )
    assert response.status_code == 200, response.text


def _open_board(page, data, sections=True):
    page.goto(f"/board.html?id={data['board']['id']}")
    selector = ".columns-container.sections-layout .section-lane" if sections else ".columns-container .column"
    page.locator(selector).first.wait_for(state="visible", timeout=8000)


def _lanes(page):
    """Column names per lane, top to bottom, as shown."""
    return page.locator(".section-lane").evaluate_all(
        """lanes => lanes.map(lane => Array.from(lane.querySelectorAll(':scope > .column h4'))
            .map(h => h.textContent))"""
    )


def _server_sections(api_session, ui_base_url, board_id):
    board = api_session.get(f"{ui_base_url}/api/boards/{board_id}/cards").json()["board"]
    return {column["name"]: (column["section_lane"], column["section_order"]) for column in board["columns"]}


def _wait_until(check, timeout=8):
    deadline = time.monotonic() + timeout
    result = check()
    while not result and time.monotonic() < deadline:
        time.sleep(0.2)
        result = check()
    return result


def _box_center(locator):
    box = locator.bounding_box()
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def _open_column_menu(page, column_id):
    page.locator(f'.column[data-column-id="{column_id}"] .column-menu-btn').click()
    menu = page.locator(f'.column-menu-dropdown[data-column-id="{column_id}"]')
    menu.wait_for(state="visible", timeout=5000)
    return menu


def test_board_menu_switches_to_sections_and_back(logged_in_page, api_session, ui_base_url, sections_board):
    page = logged_in_page
    page.set_viewport_size({"width": 1400, "height": 900})
    data = sections_board
    _open_board(page, data, sections=False)
    page.wait_for_function(
        f"() => document.querySelector('{LAYOUT}')?.style.display === ''", timeout=8000
    )
    page.locator(".settings-dropdown .icon-link").click()
    page.locator(LAYOUT).get_by_role("button", name="Sections").click()

    page.locator(".columns-container.sections-layout .section-lane").first.wait_for(timeout=5000)
    assert page.locator(f'{LAYOUT} button[aria-pressed="true"]').inner_text() == "Sections"
    board = api_session.get(f"{ui_base_url}/api/boards/{data['board']['id']}/cards").json()["board"]
    assert board["layout"] == "sections"

    # Unarranged sections spread across the lanes in column order, with an
    # empty lane on the right to add or drag a section into.
    assert _lanes(page) == [["To do"], ["Doing"], ["Done"], []]

    # Sections are only as tall as their cards, and the board scrolls up and down.
    heights = page.locator(".section-lane > .column").evaluate_all(
        "columns => columns.map(column => column.getBoundingClientRect().height)"
    )
    assert heights[0] > heights[1] + 100
    container = page.locator(".columns-container").evaluate(
        "el => ({ height: el.clientHeight, overflowY: getComputedStyle(el).overflowY })"
    )
    assert heights[1] < container["height"] / 2
    assert container["overflowY"] == "auto"
    assert page.locator(".column-insert-btn").count() == 0

    page.locator(".settings-dropdown .icon-link").click()
    page.locator(LAYOUT).get_by_role("button", name="Columns").click()
    page.locator(".columns-container:not(.sections-layout) > .column").first.wait_for(timeout=5000)
    names = page.locator(".columns-container > .column h4").all_inner_texts()
    assert names == ["To do", "Doing", "Done"]


def test_drag_section_under_another(logged_in_page, api_session, ui_base_url, sections_board):
    page = logged_in_page
    page.set_viewport_size({"width": 1400, "height": 900})
    data = sections_board
    board_id = data["board"]["id"]
    _set_layout(api_session, ui_base_url, board_id, "sections")
    _open_board(page, data)
    done_id = data["columns"][2]["id"]
    doing_id = data["columns"][1]["id"]

    header = page.locator(f'.column[data-column-id="{done_id}"] .column-header h4')
    start_x, start_y = _box_center(header)
    target = page.locator(f'.column[data-column-id="{doing_id}"]').bounding_box()
    target_x = target["x"] + target["width"] / 2
    target_y = target["y"] + target["height"] + 30

    page.mouse.move(start_x, start_y)
    page.mouse.down()
    page.mouse.move(start_x - 20, start_y + 5, steps=4)
    page.mouse.move(target_x, target_y, steps=8)
    page.wait_for_timeout(100)
    page.mouse.move(target_x, target_y + 2)
    page.mouse.up()

    # The emptied lane is now the empty one on the right.
    assert _wait_until(lambda: _lanes(page) == [["To do"], ["Doing", "Done"], []] or None), _lanes(page)
    saved = _wait_until(
        lambda: (lambda s: s if s["Done"][0] == 1 and s["Done"][1] > s["Doing"][1] else None)(
            _server_sections(api_session, ui_base_url, board_id)
        )
    )
    assert saved, _server_sections(api_session, ui_base_url, board_id)

    # Column order is unchanged.
    page.reload()
    _open_board(page, data)
    assert _lanes(page) == [["To do"], ["Doing", "Done"], []]
    board = api_session.get(f"{ui_base_url}/api/boards/{board_id}/cards").json()["board"]
    assert [column["name"] for column in board["columns"]] == ["To do", "Doing", "Done"]


def test_column_menu_moves_sections(logged_in_page, api_session, ui_base_url, sections_board):
    page = logged_in_page
    page.set_viewport_size({"width": 1400, "height": 900})
    data = sections_board
    board_id = data["board"]["id"]
    _set_layout(api_session, ui_base_url, board_id, "sections")
    _open_board(page, data)
    todo_id, doing_id, _ = (column["id"] for column in data["columns"])

    menu = _open_column_menu(page, todo_id)
    assert menu.get_by_role("button", name="Move to left lane").is_hidden()
    assert menu.get_by_role("button", name="Move up").is_hidden()
    assert menu.get_by_role("button", name="Move left", exact=True).count() == 0
    menu.get_by_role("button", name="Move to right lane").click()

    # The emptied first lane closes up.
    assert _wait_until(lambda: _lanes(page) == [["To do", "Doing"], ["Done"], []] or None), _lanes(page)

    menu = _open_column_menu(page, doing_id)
    assert menu.get_by_role("button", name="Move down").is_hidden()
    menu.get_by_role("button", name="Move up").click()
    assert _wait_until(lambda: _lanes(page) == [["Doing", "To do"], ["Done"], []] or None), _lanes(page)

    saved = _wait_until(
        lambda: (lambda s: s if s["Doing"] == (0, 0) and s["To do"] == (0, 1) else None)(
            _server_sections(api_session, ui_base_url, board_id)
        )
    )
    assert saved, _server_sections(api_session, ui_base_url, board_id)


def test_card_drag_between_sections(logged_in_page, api_session, ui_base_url, sections_board):
    page = logged_in_page
    page.set_viewport_size({"width": 1400, "height": 900})
    data = sections_board
    _set_layout(api_session, ui_base_url, data["board"]["id"], "sections")
    _open_board(page, data)
    card_id = data["cards"][0]["id"]
    target_column_id = data["columns"][2]["id"]

    start_x, start_y = _box_center(page.locator(f'.card[data-card-id="{card_id}"] .card-title'))
    target_x, target_y = _box_center(page.locator(f'.column-cards[data-column-id="{target_column_id}"]'))
    page.mouse.move(start_x, start_y)
    page.mouse.down()
    page.mouse.move(start_x + 20, start_y + 5, steps=4)
    page.mouse.move(target_x, target_y, steps=8)
    page.mouse.up()

    moved = _wait_until(
        lambda: api_session.get(f"{ui_base_url}/api/cards/{card_id}").json()["card"]["column_id"]
        == target_column_id
    )
    assert moved
    # The section the card left still exists and the layout didn't change.
    assert _lanes(page) == [["To do"], ["Doing"], ["Done"], []]


def test_lanes_scroll_sideways_when_they_dont_fit(
    logged_in_page, api_session, ui_base_url, sections_board
):
    page = logged_in_page
    data = sections_board
    board_id = data["board"]["id"]
    _set_layout(api_session, ui_base_url, board_id, "sections")
    to_do, doing, done = data["columns"]
    _save_sections(api_session, ui_base_url, board_id, [
        {"column_id": to_do["id"], "lane": 0},
        {"column_id": doing["id"], "lane": 1},
        {"column_id": done["id"], "lane": 2},
    ])

    page.set_viewport_size({"width": 1400, "height": 900})
    _open_board(page, data)
    assert _lanes(page) == [["To do"], ["Doing"], ["Done"], []]

    # A narrow window keeps every lane, including the empty one on the right,
    # and the board scrolls sideways to reach them.
    page.set_viewport_size({"width": 920, "height": 900})
    page.wait_for_timeout(300)
    assert _lanes(page) == [["To do"], ["Doing"], ["Done"], []]
    scroll = page.locator(".columns-container").evaluate(
        "el => ({ width: el.scrollWidth, client: el.clientWidth })"
    )
    assert scroll["width"] > scroll["client"]
    last_add = page.locator('.section-lane[data-lane="3"] .section-lane-add-column-btn')
    last_add.scroll_into_view_if_needed()
    assert last_add.is_visible()

    # A phone keeps the same lanes, narrower, and scrolls sideways to them.
    page.set_viewport_size({"width": 412, "height": 900})
    page.wait_for_timeout(300)
    assert _lanes(page) == [["To do"], ["Doing"], ["Done"], []]
    lane_width = page.locator(".section-lane").first.evaluate("el => el.getBoundingClientRect().width")
    assert lane_width < 300
    scroll = page.locator(".columns-container").evaluate(
        "el => ({ width: el.scrollWidth, client: el.clientWidth })"
    )
    assert scroll["width"] > scroll["client"]

    assert _server_sections(api_session, ui_base_url, board_id)["Done"] == (2, 2)
    page.set_viewport_size({"width": 1400, "height": 900})
    assert _wait_until(lambda: _lanes(page) == [["To do"], ["Doing"], ["Done"], []] or None), _lanes(page)


def test_phone_can_move_sections_between_lanes(
    logged_in_page, api_session, ui_base_url, sections_board
):
    page = logged_in_page
    data = sections_board
    board_id = data["board"]["id"]
    _set_layout(api_session, ui_base_url, board_id, "sections")
    to_do, doing, done = data["columns"]
    _save_sections(api_session, ui_base_url, board_id, [
        {"column_id": to_do["id"], "lane": 0},
        {"column_id": doing["id"], "lane": 1},
        {"column_id": done["id"], "lane": 2},
    ])

    page.set_viewport_size({"width": 412, "height": 900})
    _open_board(page, data)
    assert _lanes(page) == [["To do"], ["Doing"], ["Done"], []]

    menu = _open_column_menu(page, done["id"])
    menu.get_by_role("button", name="Move to left lane").click()
    # It keeps its row, so it goes to the top of the lane, and its old lane
    # closes up.
    assert _wait_until(lambda: _lanes(page) == [["To do"], ["Done", "Doing"], []] or None), _lanes(page)
    saved = _wait_until(
        lambda: (lambda s: s if s["Done"][0] == 1 else None)(
            _server_sections(api_session, ui_base_url, board_id)
        )
    )
    assert saved, _server_sections(api_session, ui_base_url, board_id)


@pytest.mark.browser_context_args(has_touch=True, is_mobile=True, viewport={"width": 412, "height": 915})
def test_touch_scrolls_sections_sideways_and_down(
    logged_in_page, api_session, ui_base_url, sections_board
):
    page = logged_in_page
    data = sections_board
    _set_layout(api_session, ui_base_url, data["board"]["id"], "sections")
    for index in range(10):
        response = api_session.post(
            f"{ui_base_url}/api/columns/{data['columns'][0]['id']}/cards", json={"title": f"Extra {index}"}
        )
        assert response.status_code == 201, response.text
    # Arranged in three lanes, as on a desktop.
    _save_sections(api_session, ui_base_url, data["board"]["id"], [
        {"column_id": column["id"], "lane": index} for index, column in enumerate(data["columns"])
    ])
    _open_board(page, data)
    container = page.locator(".columns-container")
    box = container.bounding_box()
    cdp = page.context.new_cdp_session(page)

    def swipe(dx, dy):
        x, y = box["x"] + box["width"] / 2, box["y"] + 200
        cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y, "id": 1}]})
        for step in range(1, 9):
            cdp.send("Input.dispatchTouchEvent", {
                "type": "touchMove", "touchPoints": [{"x": x + dx * step / 8, "y": y + dy * step / 8, "id": 1}],
            })
        cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        page.wait_for_timeout(600)

    swipe(-160, 0)
    assert container.evaluate("el => el.scrollLeft") > 100

    # The first lane is tall enough to scroll down.
    swipe(0, -150)
    assert container.evaluate("el => el.scrollTop") > 50


def test_viewer_sees_sections_but_cannot_arrange_them(
    logged_in_page, api_session, ui_base_url, sections_board
):
    data = sections_board
    board_id = data["board"]["id"]
    _set_layout(api_session, ui_base_url, board_id, "sections")
    response = api_session.patch(f"{ui_base_url}/api/boards/{board_id}", json={"is_public": True})
    assert response.status_code == 200, response.text
    slug = response.json()["board"]["public_slug"]

    page = logged_in_page
    page.set_viewport_size({"width": 1400, "height": 900})
    page.goto(f"/public-board.html?slug={slug}")
    page.locator(".columns-container.sections-layout .section-lane").first.wait_for(timeout=8000)
    assert len(_lanes(page)) == 3
    assert page.locator('.column-header[draggable="true"]').count() == 0
    assert page.locator(".column-menu-section-move-btn").count() == 0


def test_layout_toggle_hidden_without_board_edit(logged_in_page, api_session, ui_base_url, sections_board):
    page = logged_in_page
    data = sections_board
    page.context.route(
        f"**/api/boards/{data['board']['id']}/settings/working-style",
        lambda route: route.fulfill(
            json={"success": True, "value": "kanban", "can_edit": False, "key": "working_style",
                  "board_id": data["board"]["id"]}
        ) if route.request.method == "GET" else route.fallback(),
    )
    _open_board(page, data, sections=False)
    page.wait_for_function(
        f"() => document.querySelector('{VISIBILITY}') !== null", timeout=8000
    )
    page.wait_for_timeout(500)
    assert page.locator(LAYOUT).evaluate("el => el.style.display") == "none"


def test_failed_section_move_shows_an_error_and_restores(
    logged_in_page, api_session, ui_base_url, sections_board
):
    page = logged_in_page
    page.set_viewport_size({"width": 1400, "height": 900})
    data = sections_board
    board_id = data["board"]["id"]
    _set_layout(api_session, ui_base_url, board_id, "sections")
    page.context.route(
        f"**/api/boards/{board_id}/section-layout",
        lambda route: route.fulfill(status=500, json={"success": False, "message": "Nope"}),
    )
    _open_board(page, data)

    menu = _open_column_menu(page, data["columns"][0]["id"])
    menu.get_by_role("button", name="Move to right lane").click()

    toast = page.locator(".error-toast")
    toast.wait_for(state="visible", timeout=5000)
    assert "section" in toast.inner_text().lower()
    assert _wait_until(lambda: _lanes(page) == [["To do"], ["Doing"], ["Done"], []] or None), _lanes(page)
    assert _server_sections(api_session, ui_base_url, board_id)["To do"] == (None, None)


def test_each_lane_adds_a_section_at_its_bottom(logged_in_page, api_session, ui_base_url, sections_board):
    page = logged_in_page
    page.set_viewport_size({"width": 1400, "height": 900})
    data = sections_board
    board_id = data["board"]["id"]
    _set_layout(api_session, ui_base_url, board_id, "sections")
    _open_board(page, data)

    # One Add Column per lane, last in it, and no shared one.
    assert page.locator(".add-column-placeholder").count() == 0
    buttons = page.locator(".section-lane > .section-lane-add-column-btn")
    assert buttons.count() == len(_lanes(page))
    assert page.locator(".section-lane").evaluate_all(
        "lanes => lanes.every(lane => lane.lastElementChild.matches('.section-lane-add-column-btn'))"
    )

    assert buttons.first.inner_text() == "+ Add Section"
    page.locator('.section-lane[data-lane="1"] .section-lane-add-column-btn').click()
    assert page.locator("#add-column-modal h2").inner_text() == "Add New Section"
    page.locator("#add-column-modal #column-name").fill("Below doing")
    page.locator("#add-column-modal").get_by_role("button", name="Create Section").click()
    page.locator("#add-column-modal").wait_for(state="detached", timeout=5000)

    assert _wait_until(
        lambda: _lanes(page) == [["To do"], ["Doing", "Below doing"], ["Done"], []] or None
    ), _lanes(page)
    saved = _server_sections(api_session, ui_base_url, board_id)
    assert saved["Below doing"][0] == 1
    assert saved["Below doing"][1] > saved["Doing"][1]

    # The empty lane on the right starts a new lane.
    page.locator('.section-lane[data-lane="3"] .section-lane-add-column-btn').click()
    page.locator("#add-column-modal #column-name").fill("New lane")
    page.locator("#add-column-modal").get_by_role("button", name="Create Section").click()
    page.locator("#add-column-modal").wait_for(state="detached", timeout=5000)
    assert _wait_until(lambda: _lanes(page)[3:4] == [["New lane"]] or None), _lanes(page)


def test_sections_layout_calls_columns_sections(logged_in_page, api_session, ui_base_url, sections_board):
    page = logged_in_page
    page.set_viewport_size({"width": 1400, "height": 900})
    data = sections_board
    _set_layout(api_session, ui_base_url, data["board"]["id"], "sections")
    _open_board(page, data)
    column_id = data["columns"][1]["id"]

    menu = _open_column_menu(page, column_id)
    labels = menu.locator(".column-menu-item").all_inner_texts()
    text = " ".join(labels).lower()
    assert "rename section" in text
    assert "delete section" in text
    assert "column" not in text
    assert page.locator(f'.column[data-column-id="{column_id}"] .column-menu-btn').get_attribute("title") == "Section menu"

    menu.get_by_role("button", name="Rename section").click()
    modal = page.locator("#edit-column-modal")
    modal.wait_for(state="visible", timeout=5000)
    assert modal.locator("h2").inner_text() == "Edit Section"
    assert modal.locator("label").first.inner_text() == "Section Name:"
    modal.get_by_role("button", name="Cancel").click()

    menu = _open_column_menu(page, column_id)
    menu.get_by_role("button", name="Delete section").click()
    dialog = page.get_by_text("Are you sure you want to delete this section?")
    dialog.wait_for(state="visible", timeout=5000)
