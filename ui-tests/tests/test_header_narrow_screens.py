"""UI tests for the header on portrait and narrow screens above the mobile breakpoint."""
import pytest

BOARD_NAME = "Quarterly planning"
NARROW_WIDTHS = [901, 1024, 1200]
ALL_WIDTHS = [901, 1024, 1200, 1280, 1600]


@pytest.fixture
def titled_board(api_session, ui_base_url, board):
    """A public board with a column, so the views dropdown and badge both show."""
    base = f"{ui_base_url}/api/boards/{board['id']}"
    assert api_session.patch(base, json={"name": BOARD_NAME, "is_public": True}).status_code == 200
    assert api_session.post(f"{base}/columns", json={"name": "To Do"}).status_code == 201
    return board


def _open_board(page, board_id, width):
    page.set_viewport_size({"width": width, "height": 800})
    page.goto(f"/board.html?id={board_id}")
    page.wait_for_function("() => window.boardManager?.hasLoadedBoardData && window.header", timeout=8000)
    page.locator("#views-dropdown").wait_for(state="visible", timeout=8000)


@pytest.mark.ui
@pytest.mark.parametrize("width", NARROW_WIDTHS)
def test_board_title_fits_without_collisions(logged_in_page, titled_board, width):
    page = logged_in_page
    _open_board(page, titled_board["id"], width)

    title = page.locator("#nav-board-name-text")
    title.wait_for(state="visible", timeout=8000)
    assert title.evaluate("el => el.scrollWidth <= el.clientWidth"), "title is truncated"
    assert title.get_attribute("title") == BOARD_NAME

    gap = page.evaluate(
        """() => {
          const nav = document.querySelector('.nav-board-name').getBoundingClientRect();
          return document.querySelector('.header-right').getBoundingClientRect().left - nav.right;
        }"""
    )
    assert gap >= 0, "board title area overlaps the header controls"
    assert page.locator("#board-header-search-input").is_hidden()
    assert page.locator(".settings-dropdown .icon-link").is_visible()
    assert page.locator("#mobile-menu-toggle").is_hidden()


@pytest.mark.ui
def test_unhealthy_status_keeps_title_visible_with_search_open(logged_in_page, titled_board):
    page = logged_in_page
    _open_board(page, titled_board["id"], 901)

    page.locator("#board-header-search-toggle-btn").click()
    page.evaluate(
        """() => {
          document.getElementById('status-icon').className = 'status-icon error';
          document.querySelector('.db-status').classList.remove('status-compact');
          document.getElementById('status-text').textContent = 'WebSocket Disconnected';
        }"""
    )

    status = page.locator(".db-status")
    assert status.bounding_box()["width"] <= 32
    assert status.get_attribute("aria-label")
    assert page.locator("#nav-board-name-text").is_visible()
    gap = page.evaluate(
        """() => {
          const nav = document.querySelector('.nav-board-name').getBoundingClientRect();
          return document.querySelector('.header-right').getBoundingClientRect().left - nav.right;
        }"""
    )
    assert gap >= 0, "board title area overlaps the header controls"


@pytest.mark.ui
def test_search_stays_expanded_on_wide_screens(logged_in_page, titled_board):
    page = logged_in_page
    _open_board(page, titled_board["id"], 1280)

    assert page.locator("#board-header-search-input").is_visible()
    assert page.locator("#board-header-search-toggle-btn").is_hidden()


@pytest.mark.ui
def test_collapsed_search_expands_and_keeps_controls_on_screen(logged_in_page, titled_board):
    page = logged_in_page
    _open_board(page, titled_board["id"], 901)

    page.locator("#board-header-search-toggle-btn").click()
    search = page.locator("#board-header-search-input")
    search.wait_for(state="visible", timeout=8000)
    assert page.evaluate("document.activeElement.id") == "board-header-search-input"
    assert page.locator(".db-status").bounding_box()["x"] + 30 <= 901
    assert page.locator("#nav-board-name-text").is_visible()

    page.mouse.click(450, 500)
    search.wait_for(state="hidden", timeout=8000)


@pytest.mark.ui
def test_filter_button_works_from_expanded_search(logged_in_page, titled_board):
    page = logged_in_page
    _open_board(page, titled_board["id"], 1024)

    page.evaluate(
        """() => {
          window.filterToggleRequests = 0;
          window.addEventListener('boardFiltersToggleRequested', () => { window.filterToggleRequests += 1; });
        }"""
    )
    page.locator("#board-header-search-toggle-btn").click()
    # A real click holds the button for a moment, unlike Playwright's click().
    page.locator("#board-header-search-filters-btn").click(delay=100, timeout=4000)
    assert page.evaluate("window.filterToggleRequests") == 1


@pytest.mark.ui
def test_tabbing_to_filter_button_keeps_search_expanded(logged_in_page, titled_board):
    page = logged_in_page
    _open_board(page, titled_board["id"], 1024)

    page.locator("#board-header-search-toggle-btn").click()
    page.keyboard.press("Tab")
    page.wait_for_timeout(100)
    filters_button = page.locator("#board-header-search-filters-btn")
    assert filters_button.is_visible()
    assert page.evaluate("document.activeElement.id") == "board-header-search-filters-btn"

    page.keyboard.press("Tab")
    page.wait_for_timeout(100)
    assert filters_button.is_hidden()


@pytest.mark.ui
@pytest.mark.parametrize("width", ALL_WIDTHS)
@pytest.mark.parametrize("dropdown", ["settings", "user"])
def test_header_menus_stay_on_screen(logged_in_page, titled_board, width, dropdown):
    page = logged_in_page
    _open_board(page, titled_board["id"], width)

    page.locator(f".{dropdown}-dropdown .icon-link").click()
    menu = page.locator(f"#{dropdown}-dropdown-menu")
    menu.wait_for(state="visible", timeout=8000)
    page.wait_for_timeout(350)  # Let the fade-in finish

    box = menu.bounding_box()
    assert box["x"] >= 0
    assert box["x"] + box["width"] <= width
