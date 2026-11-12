"""UI tests for the Add Column button below each column.

It adds a column straight after its own, so a wide board doesn't need
scrolling to its end. The sections layout (#297) has its own Add Column.
"""
import time
import uuid

import pytest

pytestmark = pytest.mark.ui


@pytest.fixture
def three_column_board(api_session, ui_base_url):
    base = ui_base_url
    response = api_session.post(f"{base}/api/boards", json={"name": f"Add Below {uuid.uuid4().hex[:8]}"})
    assert response.status_code == 201, response.text
    board = response.json()["board"]
    columns = []
    for name in ("First", "Second", "Third"):
        response = api_session.post(f"{base}/api/boards/{board['id']}/columns", json={"name": name})
        assert response.status_code == 201, response.text
        columns.append(response.json()["column"])

    yield {"board": board, "columns": columns}

    api_session.delete(f"{base}/api/boards/{board['id']}")


def _column_names(api_session, ui_base_url, board_id):
    board = api_session.get(f"{ui_base_url}/api/boards/{board_id}/cards").json()["board"]
    return [column["name"] for column in board["columns"]]


def _add_below(page, column_id, name):
    page.locator(f'.column[data-column-id="{column_id}"] .column-add-column-btn').click()
    page.locator("#add-column-modal #column-name").fill(name)
    page.locator("#add-column-modal").get_by_role("button", name="Create Column").click()
    page.locator("#add-column-modal").wait_for(state="detached", timeout=5000)


def _wait_for_names(api_session, ui_base_url, board_id, expected):
    deadline = time.monotonic() + 8
    names = _column_names(api_session, ui_base_url, board_id)
    while names != expected and time.monotonic() < deadline:
        time.sleep(0.2)
        names = _column_names(api_session, ui_base_url, board_id)
    assert names == expected


@pytest.mark.parametrize("width", [1280, 390])
def test_add_column_below_inserts_after_that_column(
    logged_in_page, api_session, ui_base_url, three_column_board, width
):
    page = logged_in_page
    page.set_viewport_size({"width": width, "height": 800})
    data = three_column_board
    board_id = data["board"]["id"]
    page.goto(f"/board.html?id={board_id}")
    buttons = page.locator(".column .column-add-column-btn")
    buttons.first.wait_for(state="visible", timeout=8000)
    assert buttons.count() == 3
    assert buttons.first.get_attribute("aria-label") == "Add a column after First"

    _add_below(page, data["columns"][0]["id"], "After first")
    _wait_for_names(api_session, ui_base_url, board_id, ["First", "After first", "Second", "Third"])


def test_add_column_below_last_column_adds_at_the_end(
    logged_in_page, api_session, ui_base_url, three_column_board
):
    page = logged_in_page
    data = three_column_board
    board_id = data["board"]["id"]
    page.goto(f"/board.html?id={board_id}")
    page.locator(".column .column-add-column-btn").first.wait_for(state="visible", timeout=8000)

    _add_below(page, data["columns"][2]["id"], "Last")
    _wait_for_names(api_session, ui_base_url, board_id, ["First", "Second", "Third", "Last"])


def test_not_shown_in_sections_layout_or_read_only(
    logged_in_page, api_session, ui_base_url, three_column_board
):
    data = three_column_board
    board_id = data["board"]["id"]
    response = api_session.put(
        f"{ui_base_url}/api/boards/{board_id}/settings/layout", json={"value": "sections"}
    )
    assert response.status_code == 200, response.text

    page = logged_in_page
    page.goto(f"/board.html?id={board_id}")
    page.locator(".section-lane .column").first.wait_for(state="visible", timeout=8000)
    # Sections have an Add Column per lane instead.
    assert page.locator(".column .column-add-column-btn").count() == 0

    response = api_session.put(
        f"{ui_base_url}/api/boards/{board_id}/settings/layout", json={"value": "columns"}
    )
    assert response.status_code == 200, response.text
    response = api_session.patch(f"{ui_base_url}/api/boards/{board_id}", json={"is_public": True})
    assert response.status_code == 200, response.text
    page.goto(f"/public-board.html?slug={response.json()['board']['public_slug']}")
    page.locator(".columns-container .column").first.wait_for(state="visible", timeout=8000)
    assert page.locator(".column-add-column-btn").count() == 0
