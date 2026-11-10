"""UI tests for the card actions user preference (issue #395)."""
import pytest


DESKTOP = {"width": 1280, "height": 800}
MOBILE = {"width": 390, "height": 800}
BUTTONS = {
    "done": ".card-done-btn",
    "archive": ".card-archive-btn",
    "move": ".card-move-btn",
    "top": ".card-top-btn",
    "delete": ".card-delete-btn",
}


@pytest.fixture
def agile_card(api_session, ui_base_url, column):
    style = api_session.put(
        f"{ui_base_url}/api/boards/{column['board_id']}/settings/working-style", json={"value": "agile"}
    )
    assert style.status_code == 200
    response = api_session.post(f"{ui_base_url}/api/columns/{column['id']}/cards", json={"title": "Card"})
    assert response.status_code == 201
    return response.json()["card"]


@pytest.fixture
def set_card_actions(api_session, ui_base_url):
    url = f"{ui_base_url}/api/settings/card_actions"

    def _set(desktop, mobile):
        assert api_session.put(url, json={"value": {"desktop": desktop, "mobile": mobile}}).status_code == 200

    yield _set
    api_session.put(url, json={"value": None})


def _open_board(page, board_id, viewport):
    page.set_viewport_size(viewport)
    page.goto(f"/board.html?id={board_id}")
    page.locator(".card").first.wait_for(state="visible", timeout=8000)


def _shown_actions(page):
    return {name for name, selector in BUTTONS.items() if page.locator(f".card {selector}").is_visible()}


@pytest.mark.ui
@pytest.mark.parametrize("viewport, expected", [
    (DESKTOP, {"done", "archive", "delete"}),
    (MOBILE, {"done", "move"}),
])
def test_defaults_are_unchanged_without_a_choice(logged_in_page, column, agile_card, viewport, expected):
    page = logged_in_page
    _open_board(page, column["board_id"], viewport)
    assert _shown_actions(page) == expected


@pytest.mark.ui
def test_each_width_uses_its_own_choice(logged_in_page, column, agile_card, set_card_actions):
    page = logged_in_page
    set_card_actions(["done", "move"], ["archive", "delete"])
    _open_board(page, column["board_id"], DESKTOP)
    page.wait_for_function("() => document.body.classList.contains('desktop-card-action-move')", timeout=8000)
    assert _shown_actions(page) == {"done", "move"}

    page.set_viewport_size(MOBILE)
    assert _shown_actions(page) == {"archive", "delete"}


@pytest.mark.ui
def test_hidden_actions_stay_in_the_edit_modal(logged_in_page, column, agile_card, set_card_actions):
    page = logged_in_page
    set_card_actions([], [])
    _open_board(page, column["board_id"], DESKTOP)
    page.wait_for_function("() => document.body.classList.contains('desktop-card-actions')", timeout=8000)
    assert _shown_actions(page) == set()

    page.locator(".card .card-title").click()
    for button in ("done", "archive", "move", "delete"):
        page.locator(f"#{button}-card-detail-btn").wait_for(state="visible", timeout=5000)


@pytest.mark.ui
def test_title_keeps_clear_of_three_actions(logged_in_page, api_session, ui_base_url, column, agile_card, set_card_actions):
    page = logged_in_page
    title = "A long title that has to wrap before it reaches the card action buttons " * 2
    assert api_session.patch(f"{ui_base_url}/api/cards/{agile_card['id']}", json={"title": title}).status_code == 200
    set_card_actions(["archive", "move", "delete"], ["archive", "move", "delete"])

    for viewport in (DESKTOP, MOBILE):
        _open_board(page, column["board_id"], viewport)
        page.wait_for_function("() => document.body.classList.contains('desktop-card-actions')", timeout=8000)
        buttons_left = page.locator(".card .card-action-buttons").bounding_box()["x"]
        title_style = page.locator(".card .card-title").evaluate(
            "el => el.getBoundingClientRect().right - parseFloat(getComputedStyle(el).paddingRight)"
        )
        assert title_style <= buttons_left + 1


@pytest.mark.ui
def test_settings_page_saves_and_limits_choices(logged_in_page, api_session, ui_base_url, set_card_actions):
    page = logged_in_page
    set_card_actions(["done", "archive"], ["done", "move"])
    page.goto("/profile.html")

    desktop = '[data-card-action-screen="desktop"]'
    page.locator(f'{desktop}[data-card-action="archive"]:checked').wait_for(state="attached", timeout=8000)
    page.locator(f'{desktop}[data-card-action="delete"]').check()
    page.locator(".settings-status", has_text="Saved").wait_for(state="visible", timeout=5000)

    assert page.locator(f'{desktop}[data-card-action="move"]').is_disabled()
    value = api_session.get(f"{ui_base_url}/api/settings/card_actions").json()["value"]
    assert set(value["desktop"]) == {"done", "archive", "delete"}
    assert value["mobile"] == ["done", "move"]


@pytest.mark.ui
def test_settings_page_shows_defaults_without_a_choice(logged_in_page):
    page = logged_in_page
    page.goto("/profile.html")
    page.locator('[data-card-action-screen="mobile"][data-card-action="move"]:checked').wait_for(state="attached", timeout=8000)
    assert page.locator('[data-card-action-screen="desktop"]:checked').count() == 3
    assert page.locator('[data-card-action-screen="mobile"]:checked').count() == 2


def _promote_button(page):
    return page.locator(".card .card-promote-btn")


def _global_board_id(api_session, ui_base_url, card_id):
    response = api_session.get(f"{ui_base_url}/api/cards/{card_id}")
    assert response.status_code == 200, response.text
    return response.json()["card"]["global_board_id"]


@pytest.mark.ui
def test_promote_is_hidden_unless_chosen(logged_in_page, column, agile_card):
    page = logged_in_page
    _open_board(page, column["board_id"], DESKTOP)
    assert _promote_button(page).count() == 1
    assert _promote_button(page).is_hidden()


@pytest.mark.ui
@pytest.mark.parametrize("viewport, screen", [(DESKTOP, "desktop"), (MOBILE, "mobile")])
def test_promote_action_promotes_and_demotes(
    logged_in_page, api_session, ui_base_url, column, agile_card, set_card_actions, viewport, screen
):
    page = logged_in_page
    chosen = {"desktop": ["done", "archive", "delete"], "mobile": ["done", "move"]}
    chosen[screen] = ["promote", "done"]
    set_card_actions(chosen["desktop"], chosen["mobile"])
    _open_board(page, column["board_id"], viewport)

    button = _promote_button(page)
    button.wait_for(state="visible", timeout=8000)
    assert button.get_attribute("aria-pressed") == "false"
    assert button.get_attribute("aria-label") == "Promote to global board"

    button.click()
    page.locator(".card .card-promote-btn[aria-pressed='true']").wait_for(timeout=5000)
    assert page.locator(".card .card-global-badge").inner_text() == "New"
    assert _global_board_id(api_session, ui_base_url, agile_card["id"]) is not None
    # The click mustn't also open the card.
    assert page.locator("#edit-card-modal").count() == 0

    _promote_button(page).click()
    page.locator(".card .card-promote-btn[aria-pressed='false']").wait_for(timeout=5000)
    assert page.locator(".card .card-global-badge").count() == 0
    assert _global_board_id(api_session, ui_base_url, agile_card["id"]) is None


@pytest.mark.ui
def test_no_promote_action_on_done_or_kanban_cards(
    logged_in_page, api_session, ui_base_url, column, agile_card, set_card_actions
):
    page = logged_in_page
    set_card_actions(["promote"], ["promote"])
    done = api_session.patch(f"{ui_base_url}/api/cards/{agile_card['id']}/done", json={"done": True})
    assert done.status_code == 200, done.text
    page.set_viewport_size(DESKTOP)
    page.goto(f"/board.html?id={column['board_id']}")
    page.wait_for_function("() => window.boardManager?.hasLoadedBoardData", timeout=8000)
    assert _promote_button(page).count() == 0

    style = api_session.put(
        f"{ui_base_url}/api/boards/{column['board_id']}/settings/working-style", json={"value": "kanban"}
    )
    assert style.status_code == 200
    page.reload()
    page.wait_for_function("() => window.boardManager?.hasLoadedBoardData", timeout=8000)
    assert _promote_button(page).count() == 0


@pytest.mark.ui
def test_settings_page_offers_promote(logged_in_page, api_session, ui_base_url, set_card_actions):
    page = logged_in_page
    set_card_actions(["done"], ["done"])
    page.goto("/profile.html")

    checkbox = page.locator('[data-card-action-screen="desktop"][data-card-action="promote"]')
    page.locator('[data-card-action-screen="desktop"][data-card-action="done"]:checked').wait_for(
        state="attached", timeout=8000
    )
    checkbox.check()
    page.locator(".settings-status", has_text="Saved").wait_for(state="visible", timeout=5000)
    value = api_session.get(f"{ui_base_url}/api/settings/card_actions").json()["value"]
    assert set(value["desktop"]) == {"done", "promote"}
