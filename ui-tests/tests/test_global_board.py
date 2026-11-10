"""UI tests for the global board page (#663).

The test admin sees every promoted card on the instance board, including any
left by other tests, so cards are found by id rather than by position.
"""
import time

import pytest

DESKTOP = {"width": 1280, "height": 800}
MOBILE = {"width": 390, "height": 800}


@pytest.fixture
def global_board(api_session, ui_base_url):
    response = api_session.get(f"{ui_base_url}/api/global-boards")
    assert response.status_code == 200, response.text
    board = response.json()["global_boards"][0]
    yield board
    api_session.patch(
        f"{ui_base_url}/api/global-boards/{board['id']}",
        json={"name": "Global", "done_visible_days": 14},
    )


@pytest.fixture
def epic(api_session, ui_base_url, board):
    """An agile board with two feature columns."""
    response = api_session.put(
        f"{ui_base_url}/api/boards/{board['id']}/settings/working-style", json={"value": "agile"}
    )
    assert response.status_code == 200, response.text
    column_ids = []
    for name in ("Feature A", "Feature B"):
        column = api_session.post(f"{ui_base_url}/api/boards/{board['id']}/columns", json={"name": name})
        assert column.status_code == 201, column.text
        column_ids.append(column.json()["column"]["id"])
    return {"board": board, "column_ids": column_ids}


def _make_card(api_session, ui_base_url, column_id, title):
    response = api_session.post(f"{ui_base_url}/api/columns/{column_id}/cards", json={"title": title})
    assert response.status_code == 201, response.text
    return response.json()["card"]["id"]


def _promote(api_session, ui_base_url, global_board, card_id, state="new"):
    response = api_session.post(
        f"{ui_base_url}/api/global-boards/{global_board['id']}/cards",
        json={"card_id": card_id, "state": state},
    )
    assert response.status_code == 201, response.text


@pytest.fixture
def stories(api_session, ui_base_url, global_board, epic):
    """Two promoted cards in New, on different features."""
    first = _make_card(api_session, ui_base_url, epic["column_ids"][0], "First story")
    second = _make_card(api_session, ui_base_url, epic["column_ids"][1], "Second story")
    for card_id in (first, second):
        _promote(api_session, ui_base_url, global_board, card_id)
    return {"first": first, "second": second}


def _open(page, global_board, viewport=DESKTOP):
    page.set_viewport_size(viewport)
    page.goto(f"/global-board.html?id={global_board['id']}")
    page.wait_for_function("() => window.globalBoardPage?.hasLoaded", timeout=8000)


def _card(page, card_id):
    return page.locator(f'.gb-card[data-card-id="{card_id}"]')


def _column_list(page, state):
    return page.locator(f'.gb-card-list[data-state="{state}"]')


def _card_state(api_session, ui_base_url, global_board, card_id):
    response = api_session.get(f"{ui_base_url}/api/global-boards/{global_board['id']}/cards")
    assert response.status_code == 200, response.text
    for state, cards in response.json()["states"].items():
        if any(card["card_id"] == card_id for card in cards):
            return state
    return None


def _wait_for_api(check, timeout=8):
    """Poll until check() is true. The page moves a dragged card before its request ends."""
    deadline = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < deadline, "Timed out waiting for the server to record the move"
        time.sleep(0.2)


def _wait_for_card_in(page, card_id, state):
    page.wait_for_function(
        """([cardId, state]) => !!document.querySelector(
            `.gb-card-list[data-state="${state}"] .gb-card[data-card-id="${cardId}"]`)""",
        arg=[card_id, state],
        timeout=8000,
    )


@pytest.mark.ui
def test_shows_columns_and_card_details(logged_in_page, global_board, epic, stories):
    page = logged_in_page
    _open(page, global_board)

    headings = page.locator(".gb-column h2").all_inner_texts()
    assert [h.split(" (")[0] for h in headings] == ["New", "In Progress", "Waiting", "Done"]
    assert page.locator(".gb-column-note").inner_text() == "Done in the last 14 days"

    card = _card(page, stories["first"])
    assert card.locator(".gb-card-title").inner_text() == "First story"
    assert card.locator(".gb-card-context").inner_text() == f"{epic['board']['name']} › Feature A"
    assert card.locator(".gb-card-title").get_attribute("href") == (
        f"/board.html?id={epic['board']['id']}&card={stories['first']}"
    )
    assert card.get_attribute("draggable") == "true"
    assert page.evaluate("document.querySelector('#nav-board-name-text').textContent") == global_board["name"]


@pytest.mark.ui
@pytest.mark.parametrize("viewport", [DESKTOP, MOBILE], ids=["desktop", "mobile"])
def test_done_note_keeps_columns_in_line(logged_in_page, global_board, stories, viewport):
    """The Done window note shares the heading's line, so every column's cards start level."""
    page = logged_in_page
    _open(page, global_board, viewport)
    note = page.locator(".gb-column-note")
    assert note.get_attribute("title") == "Done in the last 14 days"

    tops = page.evaluate(
        "() => [...document.querySelectorAll('.gb-card-list')].map(l => l.getBoundingClientRect().top)"
    )
    assert len(tops) == 4
    assert max(tops) - min(tops) < 1, f"card lists don't start level: {tops}"


@pytest.mark.ui
def test_card_title_is_not_html(logged_in_page, api_session, ui_base_url, global_board, epic):
    page = logged_in_page
    title = '<img src=x onerror="window.__gbXss=1">'
    card_id = _make_card(api_session, ui_base_url, epic["column_ids"][0], title)
    _promote(api_session, ui_base_url, global_board, card_id)
    _open(page, global_board)

    assert _card(page, card_id).locator(".gb-card-title").inner_text() == title
    assert page.evaluate("window.__gbXss") is None


@pytest.mark.ui
def test_drag_between_states_and_into_done(
    logged_in_page, api_session, ui_base_url, global_board, stories
):
    page = logged_in_page
    _open(page, global_board)

    _card(page, stories["first"]).drag_to(_column_list(page, "in_progress"))
    _wait_for_api(lambda: _card_state(api_session, ui_base_url, global_board, stories["first"]) == "in_progress")
    _wait_for_card_in(page, stories["first"], "in_progress")

    _card(page, stories["first"]).drag_to(_column_list(page, "done"))
    _wait_for_api(lambda: api_session.get(f"{ui_base_url}/api/cards/{stories['first']}/done").json()["done"])
    _wait_for_card_in(page, stories["first"], "done")


@pytest.mark.ui
def test_drag_reorders_within_a_state(logged_in_page, api_session, ui_base_url, global_board, stories):
    page = logged_in_page
    _open(page, global_board)
    second = _card(page, stories["second"])
    first = _card(page, stories["first"])

    box = first.bounding_box()
    second.drag_to(first, target_position={"x": box["width"] / 2, "y": 2})
    page.wait_for_function(
        """([a, b]) => {
            const ids = [...document.querySelectorAll('.gb-card-list[data-state="new"] .gb-card')]
              .map((el) => Number(el.dataset.cardId));
            return ids.indexOf(b) !== -1 && ids.indexOf(b) < ids.indexOf(a);
        }""",
        arg=[stories["first"], stories["second"]],
        timeout=8000,
    )

    def second_is_just_above_first():
        response = api_session.get(f"{ui_base_url}/api/global-boards/{global_board['id']}/cards")
        ids = [card["card_id"] for card in response.json()["states"]["new"]]
        return ids.index(stories["second"]) == ids.index(stories["first"]) - 1

    _wait_for_api(second_is_just_above_first)


@pytest.mark.ui
def test_mobile_uses_move_to_control(logged_in_page, api_session, ui_base_url, global_board, stories):
    page = logged_in_page
    _open(page, global_board, MOBILE)
    card = _card(page, stories["first"])
    assert card.get_attribute("draggable") == "false"

    select = card.locator(".gb-card-move")
    assert select.is_visible()
    assert select.get_attribute("aria-label") == "Move First story to"
    select.select_option("waiting")

    _wait_for_card_in(page, stories["first"], "waiting")
    assert _card_state(api_session, ui_base_url, global_board, stories["first"]) == "waiting"
    assert page.locator(".gb-columns").evaluate("el => el.scrollWidth > el.clientWidth")
    assert page.evaluate("document.documentElement.scrollWidth") <= MOBILE["width"]


@pytest.mark.ui
def test_filters_by_epic_and_assignee(logged_in_page, api_session, ui_base_url, global_board, epic, stories):
    page = logged_in_page
    me = api_session.get(f"{ui_base_url}/api/auth/me").json()["user"]
    assigned = api_session.put(
        f"{ui_base_url}/api/cards/{stories['first']}/assignees", json={"assigned_to_id": me["id"]}
    )
    assert assigned.status_code == 200, assigned.text
    _open(page, global_board)

    page.locator("#gb-epic-filter").select_option(str(epic["board"]["id"]))
    assert page.locator(".gb-card").count() == 2

    page.locator(f'.gb-assignee-btn[data-filter-key="user-{me["id"]}"]').click()
    assert page.locator(".gb-card").count() == 1
    assert _card(page, stories["first"]).is_visible()

    page.locator('[data-filter-key="unassigned"]').click()
    assert page.locator(".gb-card").count() == 2

    # Filters are kept for the next visit.
    page.reload()
    page.wait_for_function("() => window.globalBoardPage?.hasLoaded", timeout=8000)
    assert page.locator(".gb-card").count() == 2
    assert page.locator('[data-filter-key="unassigned"]').get_attribute("aria-pressed") == "true"

    page.locator('[data-filter-key="clear"]').click()
    assert page.locator('[data-filter-key="clear"]').count() == 0
    assert page.locator("#gb-epic-filter").input_value() == ""


@pytest.mark.ui
def test_changes_elsewhere_appear_without_reload(
    logged_in_page, api_session, ui_base_url, global_board, epic, stories
):
    page = logged_in_page
    _open(page, global_board)
    page.wait_for_function("() => window.globalBoardPage.roomJoined", timeout=8000)

    # Promoted elsewhere: arrives through the global board room.
    third = _make_card(api_session, ui_base_url, epic["column_ids"][0], "Third story")
    _promote(api_session, ui_base_url, global_board, third)
    _card(page, third).wait_for(state="visible", timeout=8000)

    # Ticked done on the epic board: arrives through the board's own room.
    done = api_session.patch(f"{ui_base_url}/api/cards/{stories['second']}/done", json={"done": True})
    assert done.status_code == 200, done.text
    _wait_for_card_in(page, stories["second"], "done")

    # Renamed on the epic board.
    rename = api_session.patch(f"{ui_base_url}/api/cards/{stories['first']}", json={"title": "Renamed"})
    assert rename.status_code == 200, rename.text
    page.wait_for_function(
        """(cardId) => document.querySelector(
            `.gb-card[data-card-id="${cardId}"] .gb-card-title`)?.textContent === 'Renamed'""",
        arg=stories["first"],
        timeout=8000,
    )


@pytest.mark.ui
def test_view_menu_links_to_global_board(logged_in_page, global_board, epic):
    page = logged_in_page
    page.set_viewport_size(DESKTOP)
    page.goto(f"/board.html?id={epic['board']['id']}")
    item = page.locator("#global-board-view-item")
    item.wait_for(state="attached", timeout=8000)

    assert item.get_attribute("href") == f"/global-board.html?id={global_board['id']}"
    assert item.inner_text().strip() == global_board["name"]
    assert item.get_attribute("data-view") is None
    # Compact Cards stays last.
    assert page.evaluate(
        "document.querySelector('#views-dropdown-menu').lastElementChild.id"
    ) == "compact-cards-toggle"

    page.locator("#views-dropdown-btn").click()
    item.click()
    page.wait_for_url("**/global-board.html?id=*", timeout=8000)
    page.wait_for_function("() => window.globalBoardPage?.hasLoaded", timeout=8000)


@pytest.mark.ui
def test_mobile_drawer_links_to_global_board(logged_in_page, global_board, epic):
    page = logged_in_page
    page.set_viewport_size(MOBILE)
    page.goto(f"/board.html?id={epic['board']['id']}")
    link = page.locator("#mobile-global-board-link")
    link.wait_for(state="attached", timeout=8000)

    page.locator("#mobile-menu-toggle").click()
    link.click()
    page.wait_for_url("**/global-board.html?id=*", timeout=8000)
    page.wait_for_function("() => window.globalBoardPage?.hasLoaded", timeout=8000)


# ---------------------------------------------------------------------------
# Epic board integration: promote and demote, the badge and the deep link
# ---------------------------------------------------------------------------


def _open_epic(page, epic, query=""):
    page.set_viewport_size(DESKTOP)
    page.goto(f"/board.html?id={epic['board']['id']}{query}")
    page.wait_for_function("() => window.boardManager?.hasLoadedBoardData", timeout=8000)


def _board_card(page, card_id):
    return page.locator(f'.card[data-card-id="{card_id}"]')


def _open_card_modal(page, card_id):
    _board_card(page, card_id).locator(".card-title").click()
    page.locator("#edit-card-modal").wait_for(state="visible", timeout=5000)


@pytest.mark.ui
def test_promote_and_demote_from_edit_modal(
    logged_in_page, api_session, ui_base_url, global_board, epic
):
    page = logged_in_page
    card_id = _make_card(api_session, ui_base_url, epic["column_ids"][0], "Promote me")
    _open_epic(page, epic)
    assert _board_card(page, card_id).locator(".card-global-badge").count() == 0

    _open_card_modal(page, card_id)
    state_text = page.locator("#card-global-state-value")
    assert state_text.inner_text() == "Not promoted"
    button = page.locator("#promote-card-detail-btn")
    assert button.get_attribute("aria-label") == "Promote to global board"
    button.click()
    page.wait_for_function(
        "() => document.querySelector('#promote-card-detail-btn')?.getAttribute('aria-label')"
        " === 'Demote from global board'",
        timeout=5000,
    )
    assert _card_state(api_session, ui_base_url, global_board, card_id) == "new"
    badge = _board_card(page, card_id).locator(".card-global-badge")
    badge.wait_for(state="attached", timeout=5000)
    assert badge.inner_text() == "New"
    assert page.locator("#edit-card-modal").is_visible()
    assert state_text.inner_text() == "New"

    button.click()
    page.wait_for_function(
        "() => document.querySelector('#promote-card-detail-btn')?.getAttribute('aria-label')"
        " === 'Promote to global board'",
        timeout=5000,
    )
    assert _card_state(api_session, ui_base_url, global_board, card_id) is None
    badge.wait_for(state="detached", timeout=5000)
    assert state_text.inner_text() == "Not promoted"


@pytest.mark.ui
def test_badge_follows_changes_on_the_global_board(
    logged_in_page, api_session, ui_base_url, global_board, epic
):
    page = logged_in_page
    card_id = _make_card(api_session, ui_base_url, epic["column_ids"][0], "Badge story")
    _promote(api_session, ui_base_url, global_board, card_id, state="waiting")
    _open_epic(page, epic)
    badge = _board_card(page, card_id).locator(".card-global-badge")
    assert badge.inner_text() == "Waiting"
    assert badge.get_attribute("data-global-state") == "waiting"

    move = api_session.patch(
        f"{ui_base_url}/api/global-boards/{global_board['id']}/cards/{card_id}",
        json={"state": "in_progress"},
    )
    assert move.status_code == 200, move.text
    page.wait_for_function(
        """(cardId) => document.querySelector(
            `.card[data-card-id="${cardId}"] .card-global-badge`)?.textContent === 'In Progress'""",
        arg=card_id,
        timeout=8000,
    )

    demote = api_session.delete(f"{ui_base_url}/api/global-boards/{global_board['id']}/cards/{card_id}")
    assert demote.status_code == 200, demote.text
    page.wait_for_function(
        """(cardId) => {
            const card = document.querySelector(`.card[data-card-id="${cardId}"]`);
            return card && !card.querySelector('.card-global-badge');
        }""",
        arg=card_id,
        timeout=8000,
    )


@pytest.mark.ui
def test_no_promote_on_kanban_board_or_done_card(
    logged_in_page, api_session, ui_base_url, global_board, epic
):
    page = logged_in_page
    done_id = _make_card(api_session, ui_base_url, epic["column_ids"][0], "Already done")
    done = api_session.patch(f"{ui_base_url}/api/cards/{done_id}/done", json={"done": True})
    assert done.status_code == 200, done.text
    open_id = _make_card(api_session, ui_base_url, epic["column_ids"][0], "Open story")

    # Done cards are listed in the Done view, but the modal opens from the API.
    _open_epic(page, epic, f"&card={done_id}")
    page.locator("#edit-card-modal").wait_for(state="visible", timeout=5000)
    assert page.locator("#card-global-metadata").count() == 0
    page.locator("#cancel-edit-card-btn").click()

    switch = api_session.put(
        f"{ui_base_url}/api/boards/{epic['board']['id']}/settings/working-style", json={"value": "kanban"}
    )
    assert switch.status_code == 200, switch.text
    _open_epic(page, epic)
    _open_card_modal(page, open_id)
    assert page.locator("#done-card-detail-btn").count() == 0
    assert page.locator("#card-global-metadata").count() == 0


@pytest.mark.ui
def test_deep_link_opens_card(logged_in_page, api_session, ui_base_url, global_board, epic, stories):
    page = logged_in_page
    _open(page, global_board)
    _card(page, stories["first"]).locator(".gb-card-title").click()
    page.wait_for_url(f"**/board.html?id={epic['board']['id']}**", timeout=8000)
    page.wait_for_function("() => window.boardManager?.hasLoadedBoardData", timeout=8000)
    page.locator("#edit-card-modal").wait_for(state="visible", timeout=5000)
    assert page.locator("#edit-card-title").input_value() == "First story"
    assert page.locator("#promote-card-detail-btn").get_attribute("aria-label") == "Demote from global board"
    assert page.locator("#card-global-state-value").inner_text() == "New"
    assert "card=" not in page.url


@pytest.mark.ui
def test_deep_link_waits_for_database_check(logged_in_page, epic, stories):
    """The modal refuses to open until the header's first database check passes."""
    page = logged_in_page

    def slow_health(route):
        time.sleep(1.5)
        route.continue_()

    # The service worker makes the requests, so route on the context.
    page.context.route("**/api/health/live", slow_health)
    _open_epic(page, epic, f"&card={stories['first']}")
    page.locator("#edit-card-modal").wait_for(state="visible", timeout=8000)
    assert page.locator("#edit-card-title").input_value() == "First story"
    assert page.locator(".error-toast").count() == 0


@pytest.mark.ui
@pytest.mark.parametrize("card_param", ["999999999", "abc", "-1", "1e3"])
def test_deep_link_to_missing_card_fails_quietly(logged_in_page, epic, card_param):
    page = logged_in_page
    _open_epic(page, epic, f"&card={card_param}")
    page.wait_for_timeout(1000)
    assert page.locator("#edit-card-modal").count() == 0
    assert page.locator(".error-toast").count() == 0
    assert "card=" not in page.url


@pytest.mark.ui
def test_deep_link_to_card_on_another_board_fails_quietly(
    logged_in_page, api_session, ui_base_url, epic
):
    page = logged_in_page
    other = api_session.post(f"{ui_base_url}/api/boards", json={"name": "Other UI board"})
    assert other.status_code == 201, other.text
    other_id = other.json()["board"]["id"]
    try:
        column = api_session.post(f"{ui_base_url}/api/boards/{other_id}/columns", json={"name": "Col"})
        assert column.status_code == 201, column.text
        card_id = _make_card(api_session, ui_base_url, column.json()["column"]["id"], "Elsewhere")
        _open_epic(page, epic, f"&card={card_id}")
        page.wait_for_timeout(1000)
        assert page.locator("#edit-card-modal").count() == 0
    finally:
        api_session.delete(f"{ui_base_url}/api/boards/{other_id}")


# ---------------------------------------------------------------------------
# Instance Settings tab and the epic done/total count
# ---------------------------------------------------------------------------


def _open_global_board_settings(page, global_board):
    page.set_viewport_size(DESKTOP)
    page.goto("/settings.html#global-board")
    page.locator("#settings-tab-global-board[aria-selected='true']").wait_for(timeout=8000)
    form = page.locator(f'.global-board-settings-form[data-global-board-id="{global_board["id"]}"]')
    form.wait_for(timeout=8000)
    return form


def _saved_global_board(api_session, ui_base_url, global_board):
    response = api_session.get(f"{ui_base_url}/api/global-boards")
    assert response.status_code == 200, response.text
    return next(b for b in response.json()["global_boards"] if b["id"] == global_board["id"])


@pytest.mark.ui
def test_settings_tab_renames_board_and_sets_done_window(
    logged_in_page, api_session, ui_base_url, global_board, epic
):
    page = logged_in_page
    form = _open_global_board_settings(page, global_board)
    prefix = f"#global-board-{global_board['id']}"

    assert page.locator("#settings-panel-instance").is_hidden()
    assert form.locator(f"{prefix}-name").input_value() == global_board["name"]
    assert form.locator(f"{prefix}-done-mode").input_value() == "days"
    assert form.locator(f"{prefix}-done-days").input_value() == "14"

    form.locator(f"{prefix}-name").fill("Sprint 42")
    form.locator(f"{prefix}-done-days").fill("7")
    form.locator(".global-board-save-btn").click()
    form.locator(".settings-status.success").wait_for(timeout=5000)
    saved = _saved_global_board(api_session, ui_base_url, global_board)
    assert (saved["name"], saved["done_visible_days"]) == ("Sprint 42", 7)

    form.locator(f"{prefix}-done-mode").select_option("always")
    assert form.locator(f"{prefix}-done-days").is_hidden()
    form.locator(".global-board-save-btn").click()
    form.locator(".settings-status.success").wait_for(timeout=5000)
    assert _saved_global_board(api_session, ui_base_url, global_board)["done_visible_days"] is None

    # The new name reaches the view menu and the page title.
    page.goto(f"/board.html?id={epic['board']['id']}")
    item = page.locator("#global-board-view-item")
    item.wait_for(state="attached", timeout=8000)
    assert item.inner_text().strip() == "Sprint 42"
    _open(page, global_board)
    assert page.evaluate("document.querySelector('#nav-board-name-text').textContent") == "Sprint 42"
    assert page.locator(".gb-column-note").count() == 0


@pytest.mark.ui
@pytest.mark.parametrize("name, days, message", [
    ("   ", "14", "Please enter a name."),
    ("Global", "0", "Enter a whole number of days from 1 to 3650."),
    ("Global", "3651", "Enter a whole number of days from 1 to 3650."),
    ("Global", "2.5", "Enter a whole number of days from 1 to 3650."),
])
def test_settings_tab_rejects_invalid_values(
    logged_in_page, api_session, ui_base_url, global_board, name, days, message
):
    page = logged_in_page
    form = _open_global_board_settings(page, global_board)
    prefix = f"#global-board-{global_board['id']}"
    requests_sent = []
    page.on("request", lambda r: requests_sent.append(r) if r.method == "PATCH" else None)

    form.locator(f"{prefix}-name").fill(name)
    form.locator(f"{prefix}-done-days").fill(days)
    form.locator(".global-board-save-btn").click()

    assert form.locator(".settings-status.error").inner_text() == message
    assert requests_sent == []
    saved = _saved_global_board(api_session, ui_base_url, global_board)
    assert (saved["name"], saved["done_visible_days"]) == (global_board["name"], 14)


@pytest.mark.ui
def test_settings_tab_shows_name_as_text(logged_in_page, api_session, ui_base_url, global_board):
    name = '<img src=x onerror="window.__gbSettingsXss=1">'
    response = api_session.patch(
        f"{ui_base_url}/api/global-boards/{global_board['id']}", json={"name": name}
    )
    assert response.status_code == 200, response.text
    page = logged_in_page
    form = _open_global_board_settings(page, global_board)

    assert form.locator(f"#global-board-{global_board['id']}-name").input_value() == name
    assert page.evaluate("window.__gbSettingsXss") is None


def _done_count(page):
    return page.locator("#board-done-count")


@pytest.mark.ui
def test_epic_header_shows_done_count(logged_in_page, api_session, ui_base_url, epic):
    page = logged_in_page
    first = _make_card(api_session, ui_base_url, epic["column_ids"][0], "Count one")
    _make_card(api_session, ui_base_url, epic["column_ids"][0], "Count two")
    third = _make_card(api_session, ui_base_url, epic["column_ids"][1], "Count three")
    response = api_session.patch(f"{ui_base_url}/api/cards/{third}/done", json={"done": True})
    assert response.status_code == 200, response.text

    _open_epic(page, epic)
    count = _done_count(page)
    count.wait_for(state="visible", timeout=5000)
    assert count.inner_text() == "1/3"
    assert count.get_attribute("aria-label") == "1 of 3 cards done on this board"

    # Ticking done on the board updates the count.
    _board_card(page, first).hover()
    _board_card(page, first).locator(".card-done-btn").click()
    page.wait_for_function(
        "() => document.querySelector('#board-done-count')?.textContent === '2/3'", timeout=5000
    )

    # So does a change made elsewhere, and a new card.
    response = api_session.patch(f"{ui_base_url}/api/cards/{third}/done", json={"done": False})
    assert response.status_code == 200, response.text
    page.wait_for_function(
        "() => document.querySelector('#board-done-count')?.textContent === '1/3'", timeout=5000
    )
    _make_card(api_session, ui_base_url, epic["column_ids"][1], "Count four")
    page.wait_for_function(
        "() => document.querySelector('#board-done-count')?.textContent === '1/4'", timeout=5000
    )

    # Up to 1200px the board title needs the room.
    page.set_viewport_size({"width": 1024, "height": 800})
    assert count.is_hidden()


@pytest.mark.ui
def test_no_done_count_on_kanban_board(logged_in_page, api_session, ui_base_url, board, column):
    page = logged_in_page
    response = api_session.put(
        f"{ui_base_url}/api/boards/{board['id']}/settings/working-style", json={"value": "kanban"}
    )
    assert response.status_code == 200, response.text
    _make_card(api_session, ui_base_url, column["id"], "Kanban card")
    page.set_viewport_size(DESKTOP)
    page.goto(f"/board.html?id={board['id']}")
    page.wait_for_function("() => window.boardManager?.hasLoadedBoardData", timeout=8000)
    page.wait_for_timeout(300)
    assert _done_count(page).is_hidden()


# ---------------------------------------------------------------------------
# Boards dropdown and boards page
# ---------------------------------------------------------------------------


@pytest.mark.ui
def test_boards_dropdown_pins_global_board(logged_in_page, global_board, epic):
    page = logged_in_page
    _open_epic(page, epic)
    link = page.locator("#boards-dropdown-global-board")
    link.wait_for(state="attached", timeout=8000)

    assert page.evaluate(
        "document.querySelector('#boards-dropdown-menu').firstElementChild.id"
    ) == "boards-dropdown-global-board"
    assert link.inner_text().strip() == global_board["name"]
    assert link.get_attribute("href") == f"/global-board.html?id={global_board['id']}"
    assert page.locator('#boards-dropdown-menu a.boards-dropdown-item[href^="/board.html"]').count() > 0


@pytest.mark.ui
def test_boards_page_links_to_global_board(logged_in_page, global_board, epic):
    page = logged_in_page
    page.set_viewport_size(DESKTOP)
    page.goto("/?show_boards=1")
    card = page.locator("#boards-global-board-card")
    card.wait_for(state="visible", timeout=8000)

    assert page.evaluate("document.querySelector('#boards-list').firstElementChild.id") == (
        "boards-global-board-card"
    )
    assert card.locator("h4").inner_text() == global_board["name"]
    assert page.locator(".board-card").count() > 0

    card.click()
    page.wait_for_url("**/global-board.html?id=*", timeout=8000)
    page.wait_for_function("() => window.globalBoardPage?.hasLoaded", timeout=8000)


# ---------------------------------------------------------------------------
# Editing a card in place
# ---------------------------------------------------------------------------


def _open_in_place(page, card_id):
    """Click the card itself, away from its links and controls."""
    card = _card(page, card_id)
    box = card.bounding_box()
    footer = card.locator(".gb-card-footer").bounding_box()
    # The middle of the footer row, left of Move to and right of the avatar.
    page.mouse.click(box["x"] + box["width"] * 0.45, footer["y"] + footer["height"] / 2)
    page.locator(".gb-card-overlay.is-ready").wait_for(timeout=15000)
    frame = page.frame_locator(".gb-card-frame")
    frame.locator("#edit-card-modal").wait_for(state="visible", timeout=5000)
    return frame


def _wait_overlay_closed(page):
    page.wait_for_function(
        "() => !document.querySelector('.gb-card-overlay:not(.is-closed)')", timeout=8000
    )


@pytest.mark.ui
@pytest.mark.parametrize("viewport", [DESKTOP, MOBILE], ids=["desktop", "mobile"])
def test_clicking_a_card_edits_it_in_place(
    logged_in_page, api_session, ui_base_url, global_board, stories, viewport
):
    page = logged_in_page
    _open(page, global_board, viewport)
    url = page.url
    frame = _open_in_place(page, stories["first"])

    assert page.url == url
    assert frame.locator("#edit-card-title").input_value() == "First story"
    # Only the modal shows: the frame's board and header are hidden.
    assert frame.locator(".canvas").is_hidden()
    assert frame.locator(".header").is_hidden()
    assert frame.locator("#view-planner-btn").is_hidden()

    frame.locator("#edit-card-title").fill("Renamed in place")
    frame.locator("#cancel-edit-card-btn").click()
    _wait_overlay_closed(page)

    assert page.url == url
    page.wait_for_function(
        """(id) => document.querySelector(`.gb-card[data-card-id="${id}"] .gb-card-title`)
            ?.textContent === 'Renamed in place'""",
        arg=stories["first"],
        timeout=8000,
    )
    response = api_session.get(f"{ui_base_url}/api/cards/{stories['first']}")
    assert response.json()["card"]["title"] == "Renamed in place"
    assert page.evaluate("document.activeElement?.dataset?.cardId") == str(stories["first"])


@pytest.mark.ui
def test_escape_closes_the_card_and_keyboard_opens_it(logged_in_page, global_board, stories):
    page = logged_in_page
    _open(page, global_board)
    _card(page, stories["second"]).focus()
    page.keyboard.press("Enter")
    page.locator(".gb-card-overlay.is-ready").wait_for(timeout=15000)
    frame = page.frame_locator(".gb-card-frame")
    frame.locator("#edit-card-modal").wait_for(state="visible", timeout=5000)

    frame.locator("#edit-card-title").press("Escape")
    _wait_overlay_closed(page)
    assert page.url.endswith(f"/global-board.html?id={global_board['id']}")


@pytest.mark.ui
def test_card_that_cannot_open_closes_with_a_message(
    logged_in_page, api_session, ui_base_url, global_board, stories
):
    page = logged_in_page
    _open(page, global_board)
    # Archive it behind the page's back, then open the stale card.
    page.evaluate("() => window.globalBoardPage.socket?.disconnect()")
    response = api_session.patch(f"{ui_base_url}/api/cards/{stories['first']}/archive")
    assert response.status_code == 200, response.text

    _card(page, stories["first"]).dispatch_event("click")
    _wait_overlay_closed(page)
    page.get_by_text("This card can't be opened").wait_for(timeout=5000)


@pytest.mark.ui
def test_context_links_to_the_board_without_opening_the_card(logged_in_page, global_board, epic, stories):
    page = logged_in_page
    _open(page, global_board)
    link = _card(page, stories["first"]).locator(".gb-card-board-link")
    assert link.get_attribute("href") == f"/board.html?id={epic['board']['id']}"
    assert link.inner_text() == f"{epic['board']['name']} › Feature A"

    link.click()
    page.wait_for_url(f"**/board.html?id={epic['board']['id']}", timeout=8000)
    page.wait_for_function("() => window.boardManager?.hasLoadedBoardData", timeout=8000)
    page.wait_for_timeout(500)
    assert page.locator("#edit-card-modal").count() == 0


# ---------------------------------------------------------------------------
# Default board and navigation shortcuts
# ---------------------------------------------------------------------------


@pytest.fixture
def reset_default_board(api_session, ui_base_url):
    yield
    api_session.put(f"{ui_base_url}/api/settings/default_board", json={"value": None})


@pytest.mark.ui
def test_global_board_can_be_the_default_board(
    logged_in_page, api_session, ui_base_url, global_board, epic, reset_default_board
):
    page = logged_in_page
    page.goto("/profile.html#preferences")
    value = f"global:{global_board['id']}"
    option = page.locator(f'#default-board option[value="{value}"]')
    option.wait_for(state="attached", timeout=8000)
    assert option.inner_text() == f"{global_board['name']} (global board)"
    page.wait_for_load_state("networkidle")

    page.select_option("#default-board", value)
    page.locator("#settings-status", has_text="Saved").wait_for(state="visible", timeout=5000)
    assert api_session.get(f"{ui_base_url}/api/settings/default_board").json()["value"] == value

    page.goto("/")
    page.wait_for_url(f"**/global-board.html?id={global_board['id']}", timeout=8000)
    page.wait_for_function("() => window.globalBoardPage?.hasLoaded", timeout=8000)

    page.goto("/profile.html#preferences")
    page.wait_for_load_state("networkidle")
    assert page.locator("#default-board").input_value() == value


def _press_and_wait(page, key, url_glob):
    page.locator("body").click(position={"x": 5, "y": 400})
    page.keyboard.press(key)
    page.wait_for_url(url_glob, timeout=8000)


@pytest.mark.ui
def test_g_and_b_move_between_boards_and_the_global_board(logged_in_page, global_board, epic):
    page = logged_in_page
    _open_epic(page, epic)
    page.wait_for_function("() => !!window.header?.menuGlobalBoardPromise", timeout=8000)

    _press_and_wait(page, "g", f"**/global-board.html?id={global_board['id']}")
    page.wait_for_function("() => window.globalBoardPage?.hasLoaded", timeout=8000)
    page.keyboard.press("g")  # no-op here
    _press_and_wait(page, "b", "**/?show_boards=1")
    page.locator(".board-card").first.wait_for(timeout=8000)
    _press_and_wait(page, "G", f"**/global-board.html?id={global_board['id']}")

    _open_epic(page, epic)
    _press_and_wait(page, "b", "**/?show_boards=1")


@pytest.mark.ui
def test_g_and_b_are_ignored_while_typing_or_editing(logged_in_page, global_board, epic, stories):
    page = logged_in_page
    _open_epic(page, epic)
    url = page.url
    page.locator("#board-header-search-input").fill("gb")
    page.wait_for_timeout(500)
    assert page.url == url

    _open(page, global_board)
    frame = _open_in_place(page, stories["first"])
    frame.locator("#edit-card-title").press("End")
    page.keyboard.press("b")
    page.wait_for_timeout(500)
    assert "global-board.html" in page.url
    frame.locator("#cancel-edit-card-btn").click()
    _wait_overlay_closed(page)


@pytest.mark.ui
def test_card_frame_without_a_database_check_says_so(logged_in_page, global_board, stories):
    """If the database check never passes, the message blames the connection, not the card."""
    page = logged_in_page
    _open(page, global_board)
    page.context.route("**/api/health/live", lambda route: route.abort())

    _card(page, stories["first"]).dispatch_event("click")
    page.get_by_text("Couldn't open the card. Check your connection").wait_for(timeout=15000)
    _wait_overlay_closed(page)
