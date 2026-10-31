"""UI tests for the views button and public badge in the mobile header."""
import pytest

VIEWS_BUTTON = "#views-dropdown-btn"
VIEWS_MENU = "#views-dropdown-menu"
MOBILE = {"width": 390, "height": 800}


def _open_board(page, board_id, viewport=MOBILE):
    page.set_viewport_size(viewport)
    page.goto(f"/board.html?id={board_id}")
    page.wait_for_function("() => window.boardManager?.hasLoadedBoardData && window.header", timeout=8000)
    page.locator(VIEWS_BUTTON).wait_for(state="visible", timeout=8000)


@pytest.mark.ui
def test_views_button_shows_in_every_view(logged_in_page, column):
    page = logged_in_page
    _open_board(page, column["board_id"])
    button = page.locator(VIEWS_BUTTON)

    box = button.bounding_box()
    assert box["width"] == 34 and box["height"] == 34
    assert page.locator("#views-dropdown-label").is_hidden()
    assert button.get_attribute("aria-label") == "Switch View"

    for view in ("scheduled", "archived", "planner", "task"):
        page.evaluate("(view) => window.header.setView(view)", view)
        assert button.is_visible(), f"button hidden in {view} view"


@pytest.mark.ui
def test_views_button_opens_menu_and_switches_view(logged_in_page, column):
    page = logged_in_page
    _open_board(page, column["board_id"])

    page.locator(VIEWS_BUTTON).click()
    menu = page.locator(VIEWS_MENU)
    menu.wait_for(state="visible", timeout=8000)
    box = menu.bounding_box()
    assert box["x"] >= 0 and box["x"] + box["width"] <= MOBILE["width"]

    menu.locator('[data-view="scheduled"]').click()
    menu.wait_for(state="hidden", timeout=8000)
    assert page.evaluate("window.header.getView()") == "scheduled"
    page.wait_for_function("() => window.boardManager.currentView === 'scheduled'", timeout=8000)

    page.locator(VIEWS_BUTTON).click()
    menu.locator('[data-view="task"]').click()
    page.wait_for_function("() => window.boardManager.currentView === 'task'", timeout=8000)


@pytest.mark.ui
def test_agile_board_lists_done_view(logged_in_page, api_session, ui_base_url, column):
    page = logged_in_page
    resp = api_session.put(
        f"{ui_base_url}/api/boards/{column['board_id']}/settings/working-style", json={"value": "agile"}
    )
    assert resp.status_code == 200
    _open_board(page, column["board_id"])

    page.locator(VIEWS_BUTTON).click()
    page.locator(f'{VIEWS_MENU} [data-view="done"]').wait_for(state="visible", timeout=8000)


@pytest.mark.ui
def test_header_order_and_fit_on_a_small_phone(logged_in_page, column):
    page = logged_in_page
    _open_board(page, column["board_id"], {"width": 320, "height": 640})

    search = page.locator("#board-header-search-toggle-btn").bounding_box()
    views = page.locator(VIEWS_BUTTON).bounding_box()
    menu = page.locator("#mobile-menu-toggle").bounding_box()
    assert search["x"] + search["width"] <= views["x"]
    assert views["x"] + views["width"] <= menu["x"]
    assert menu["x"] + menu["width"] <= 320
    assert page.locator("#header-mobile-board-name").is_visible()


@pytest.mark.ui
def test_open_search_does_not_overlap_views_button_on_a_small_phone(logged_in_page, column):
    page = logged_in_page
    _open_board(page, column["board_id"], {"width": 320, "height": 640})

    page.locator("#board-header-search-toggle-btn").click()
    page.locator("#board-header-search-input").wait_for(state="visible", timeout=8000)
    assert page.locator(VIEWS_BUTTON).is_hidden()

    page.mouse.click(160, 400)
    page.locator(VIEWS_BUTTON).wait_for(state="visible", timeout=8000)


@pytest.mark.ui
def test_public_badge_sits_next_to_the_title(logged_in_page, api_session, ui_base_url, column):
    page = logged_in_page
    resp = api_session.patch(f"{ui_base_url}/api/boards/{column['board_id']}", json={"is_public": True})
    assert resp.status_code == 200
    _open_board(page, column["board_id"])

    badge = page.locator("#public-board-badge-mobile-btn")
    badge.wait_for(state="visible", timeout=8000)
    gap = page.evaluate(
        """() => {
          const title = document.getElementById('header-mobile-board-name').getBoundingClientRect();
          const badge = document.getElementById('public-board-badge-mobile-btn').getBoundingClientRect();
          return badge.left - title.right;
        }"""
    )
    assert 0 <= gap <= 16
    assert badge.bounding_box()["x"] < page.locator("#board-header-search-toggle-btn").bounding_box()["x"]


@pytest.mark.ui
@pytest.mark.parametrize("width", [320, 390])
def test_long_title_truncates_before_the_controls(logged_in_page, api_session, ui_base_url, column, width):
    page = logged_in_page
    resp = api_session.patch(
        f"{ui_base_url}/api/boards/{column['board_id']}",
        json={"name": "Quarterly planning and delivery roadmap", "is_public": True},
    )
    assert resp.status_code == 200
    _open_board(page, column["board_id"], {"width": width, "height": 800})

    badge = page.locator("#public-board-badge-mobile-btn")
    badge.wait_for(state="visible", timeout=8000)
    assert page.locator("#header-mobile-board-name").is_visible()

    def badge_clears_search():
        badge_box = badge.bounding_box()
        search_box = page.locator("#board-header-search-control").bounding_box()
        return badge_box["x"] + badge_box["width"] <= search_box["x"]

    assert badge_clears_search()
    page.locator("#board-header-search-toggle-btn").click()
    page.locator("#board-header-search-input").wait_for(state="visible", timeout=8000)
    assert badge_clears_search()
    input_box = page.locator("#board-header-search-input").bounding_box()
    assert input_box["x"] + input_box["width"] <= page.locator("#mobile-menu-toggle").bounding_box()["x"]


@pytest.mark.ui
def test_desktop_views_dropdown_keeps_its_label(logged_in_page, column):
    page = logged_in_page
    _open_board(page, column["board_id"], {"width": 1280, "height": 800})

    assert page.locator("#views-dropdown-label").is_visible()
    assert page.locator(".views-dropdown-mobile-icon").is_hidden()


@pytest.mark.ui
def test_boards_list_keeps_views_in_the_menu(logged_in_page):
    page = logged_in_page
    page.set_viewport_size(MOBILE)
    page.goto("/?show_boards=1")
    page.wait_for_function("() => window.header", timeout=8000)
    page.locator("#mobile-menu-toggle").click()

    page.locator("#mobile-views-section").wait_for(state="visible", timeout=8000)
    assert page.locator(VIEWS_BUTTON).is_hidden()


@pytest.mark.ui
def test_board_menu_no_longer_lists_views(logged_in_page, column):
    page = logged_in_page
    _open_board(page, column["board_id"])
    page.locator("#mobile-menu-toggle").click()

    assert page.locator("#mobile-views-section").is_hidden()
