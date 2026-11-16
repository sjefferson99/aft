"""UI tests for searching cards across boards from the boards page (#593)."""
import uuid

import pytest
from playwright.sync_api import expect


def _token():
    return f"srch{uuid.uuid4().hex[:10]}"


def _make_board(api_session, ui_base_url, name, agile=False):
    response = api_session.post(f"{ui_base_url}/api/boards", json={"name": name})
    assert response.status_code == 201, response.text
    board = response.json()["board"]
    column = api_session.post(f"{ui_base_url}/api/boards/{board['id']}/columns", json={"name": "To Do"})
    assert column.status_code == 201, column.text
    board["column_id"] = column.json()["column"]["id"]
    if agile:
        style = api_session.put(
            f"{ui_base_url}/api/boards/{board['id']}/settings/working-style", json={"value": "agile"}
        )
        assert style.status_code == 200, style.text
    return board


def _make_card(api_session, ui_base_url, column_id, title):
    response = api_session.post(f"{ui_base_url}/api/columns/{column_id}/cards", json={"title": title})
    assert response.status_code == 201, response.text
    return response.json()["card"]["id"]


@pytest.fixture
def search_data(api_session, ui_base_url):
    """An agile and a kanban board with task, done and archived cards sharing a token."""
    token = _token()
    agile = _make_board(api_session, ui_base_url, f"Agile {token}", agile=True)
    kanban = _make_board(api_session, ui_base_url, f"Kanban {token}")
    cards = {
        "task": _make_card(api_session, ui_base_url, agile["column_id"], f"{token} task"),
        "done": _make_card(api_session, ui_base_url, agile["column_id"], f"{token} done"),
        "archived": _make_card(api_session, ui_base_url, agile["column_id"], f"{token} archived"),
        "kanban": _make_card(api_session, ui_base_url, kanban["column_id"], f"{token} kanban"),
    }
    done = api_session.patch(f"{ui_base_url}/api/cards/{cards['done']}/done", json={"done": True})
    assert done.status_code == 200, done.text
    archived = api_session.patch(f"{ui_base_url}/api/cards/{cards['archived']}/archive")
    assert archived.status_code == 200, archived.text

    yield {"token": token, "agile": agile, "kanban": kanban, "cards": cards}

    for board in (agile, kanban):
        api_session.delete(f"{ui_base_url}/api/boards/{board['id']}")


def _search(page, query):
    page.goto("/index.html")
    page.locator("#card-search-input").wait_for(state="visible", timeout=5000)
    page.fill("#card-search-input", query)


@pytest.mark.ui
def test_search_groups_results_by_board_and_view(logged_in_page, search_data):
    """Typing a query lists matches from every board, grouped by board then view."""
    page = logged_in_page
    _search(page, search_data["token"])

    agile = page.locator(f'.card-search-board[data-board-id="{search_data["agile"]["id"]}"]')
    agile.wait_for(state="visible", timeout=5000)
    kanban = page.locator(f'.card-search-board[data-board-id="{search_data["kanban"]["id"]}"]')
    expect(kanban).to_be_visible()

    cards = search_data["cards"]
    for view in ("task", "done", "archived"):
        link = agile.locator(f'.card-search-view[data-view="{view}"] .card-search-card')
        expect(link).to_have_count(1)
        expect(link).to_have_attribute("data-card-id", str(cards[view]))
    expect(kanban.locator(f'.card-search-card[data-card-id="{cards["kanban"]}"]')).to_be_visible()

    expect(page.locator("#card-search-status")).to_have_text("4 cards on 2 boards.")
    # The boards grid gives way to the results, and comes back when cleared.
    expect(page.locator("#boards-list")).to_be_hidden()
    page.click("#card-search-clear-btn")
    expect(page.locator("#boards-list")).to_be_visible()
    expect(page.locator(".card-search-board")).to_have_count(0)


@pytest.mark.ui
def test_search_reports_no_matches_and_short_queries(logged_in_page):
    page = logged_in_page
    _search(page, "x")
    expect(page.locator("#card-search-status")).to_have_text("Type at least 2 characters to search.")

    page.fill("#card-search-input", _token())
    expect(page.locator("#card-search-status")).to_have_text("No cards match your search.", timeout=5000)
    expect(page.locator("#boards-list")).to_be_visible()


@pytest.mark.ui
def test_search_can_be_limited_to_chosen_boards(logged_in_page, search_data):
    page = logged_in_page
    _search(page, search_data["token"])
    page.locator(".card-search-board").first.wait_for(state="visible", timeout=5000)

    page.click('.card-search-scope-btn[data-scope="chosen"]')
    expect(page.locator('.card-search-scope-btn[data-scope="chosen"]')).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#card-search-status")).to_have_text("Choose at least one board to search.")

    page.locator(f'#card-search-board-options input[value="{search_data["kanban"]["id"]}"]').check()
    expect(page.locator(".card-search-board")).to_have_count(1, timeout=5000)
    expect(page.locator(".card-search-board")).to_have_attribute(
        "data-board-id", str(search_data["kanban"]["id"])
    )

    page.click('.card-search-scope-btn[data-scope="all"]')
    expect(page.locator(".card-search-board")).to_have_count(2, timeout=5000)
    expect(page.locator("#card-search-board-picker")).to_be_hidden()


@pytest.mark.ui
def test_archived_boards_are_searched_only_when_included(logged_in_page, api_session, ui_base_url, search_data):
    archive = api_session.patch(f"{ui_base_url}/api/boards/{search_data['kanban']['id']}/archive")
    assert archive.status_code == 200, archive.text

    page = logged_in_page
    _search(page, search_data["token"])
    expect(page.locator(".card-search-board")).to_have_count(1, timeout=5000)

    page.check("#card-search-include-archived")
    expect(page.locator(".card-search-board")).to_have_count(2, timeout=5000)
    kanban = page.locator(f'.card-search-board[data-board-id="{search_data["kanban"]["id"]}"]')
    expect(kanban.locator(".card-search-archived-badge")).to_have_text("Archived board")


@pytest.mark.ui
@pytest.mark.parametrize("view,label", [
    ("task", "Task View"),
    ("done", "Done View"),
    ("archived", "Archived View"),
])
def test_result_opens_the_card_in_its_view(logged_in_page, search_data, view, label):
    """A result opens the board in the card's view with the card open."""
    page = logged_in_page
    _search(page, search_data["token"])
    card_id = search_data["cards"][view]
    page.locator(f'.card-search-card[data-card-id="{card_id}"]').click()

    page.wait_for_url(lambda url: "board.html" in url, timeout=10000)
    page.locator("#edit-card-modal").wait_for(state="visible", timeout=10000)
    expect(page.locator("#edit-card-modal")).to_contain_text(f"{search_data['token']} {view}")
    expect(page.locator("#views-dropdown-label")).to_have_text(label)
    expect(page.locator(f'.card[data-card-id="{card_id}"]')).to_have_count(1)
    # The view and card are read once, so a reload returns to the task view.
    assert "view=" not in page.url
    assert "card=" not in page.url


@pytest.mark.ui
def test_done_view_link_falls_back_to_task_view_on_kanban_board(logged_in_page, search_data):
    """Kanban boards have no done view, so view=done opens the task view."""
    page = logged_in_page
    board_id = search_data["kanban"]["id"]
    card_id = search_data["cards"]["kanban"]
    page.goto(f"/board.html?id={board_id}&view=done&card={card_id}")

    page.locator("#edit-card-modal").wait_for(state="visible", timeout=10000)
    expect(page.locator("#views-dropdown-label")).to_have_text("Task View")
