"""UI tests for the per-user touchscreen mode."""
import pytest


@pytest.fixture
def touchscreen_mode(api_session, ui_base_url):
    """Turn touchscreen mode on for test-admin, and off again afterwards."""
    url = f"{ui_base_url}/api/settings/touchscreen_mode"
    assert api_session.put(url, json={"value": True}).status_code == 200
    yield
    assert api_session.put(url, json={"value": False}).status_code == 200


def _open_board(page, board_id, width=1600):
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"/board.html?id={board_id}")
    page.wait_for_function("() => window.boardManager?.hasLoadedBoardData && window.header", timeout=8000)
    page.wait_for_function("() => document.body.classList.contains('touchscreen-mode')", timeout=8000)


@pytest.mark.ui
def test_setting_turns_mode_on_and_off(logged_in_page, api_session, ui_base_url):
    page = logged_in_page
    page.goto("/settings.html")
    checkbox = page.locator("#touchscreen-mode")
    page.wait_for_load_state("networkidle")  # Settings binds its listeners after loading
    assert not checkbox.is_checked()

    try:
        checkbox.check()
        page.wait_for_function("() => document.body.classList.contains('touchscreen-mode')", timeout=8000)

        page.reload()
        page.wait_for_function("() => document.getElementById('touchscreen-mode')?.checked", timeout=8000)

        page.wait_for_load_state("networkidle")
        page.locator("#touchscreen-mode").uncheck()
        page.wait_for_function("() => !document.body.classList.contains('touchscreen-mode')", timeout=8000)
    finally:
        api_session.put(f"{ui_base_url}/api/settings/touchscreen_mode", json={"value": False})


@pytest.mark.ui
def test_mode_is_off_by_default(logged_in_page, board):
    page = logged_in_page
    page.goto(f"/board.html?id={board['id']}")
    page.wait_for_function("() => window.boardManager?.hasLoadedBoardData && window.header", timeout=8000)
    page.wait_for_timeout(300)

    assert page.evaluate("document.body.classList.contains('touchscreen-mode')") is False
    assert page.evaluate("window.boardManager.isMobileTouchViewport()") is False


@pytest.mark.ui
def test_stale_cached_mode_is_corrected(logged_in_page, board):
    """A kiosk tab keeps session storage when the signed-in user changes."""
    page = logged_in_page
    page.goto("/settings.html")
    page.evaluate("sessionStorage.setItem('touchscreenMode', '1')")
    page.goto(f"/board.html?id={board['id']}")

    page.wait_for_function("() => !document.body.classList.contains('touchscreen-mode')", timeout=8000)


@pytest.mark.ui
@pytest.mark.parametrize("width", [1024, 1600])
def test_header_targets_are_finger_sized(logged_in_page, touchscreen_mode, column, width):
    page = logged_in_page
    _open_board(page, column["board_id"], width)
    page.locator("#views-dropdown").wait_for(state="visible", timeout=8000)

    for selector in ("#notifications-icon-link", ".settings-dropdown .icon-link", ".user-dropdown .icon-link",
                     "#views-dropdown-btn", ".nav-link"):
        box = page.locator(selector).first.bounding_box()
        assert box["height"] >= 44, f"{selector} is too short at {width}px"
        assert box["width"] >= 44, f"{selector} is too narrow at {width}px"
    assert page.locator("#mobile-menu-toggle").is_hidden()
    assert page.locator("#nav-board-name-text").is_visible()
    assert page.evaluate("document.documentElement.scrollWidth") <= width


@pytest.mark.ui
def test_board_targets_are_finger_sized(logged_in_page, touchscreen_mode, api_session, ui_base_url, column):
    resp = api_session.post(f"{ui_base_url}/api/columns/{column['id']}/cards", json={"title": "Tap me"})
    assert resp.status_code == 201
    page = logged_in_page
    _open_board(page, column["board_id"])
    page.locator(".card").first.wait_for(state="visible", timeout=8000)
    page.wait_for_timeout(350)  # Column buttons animate to their larger size

    for selector in (".column-menu-btn", ".column-add-card-btn", ".card-delete-btn", ".card-move-btn"):
        box = page.locator(selector).first.bounding_box()
        assert box["height"] >= 44 and box["width"] >= 44, selector

    actions = page.locator(".card-action-buttons").first.bounding_box()
    title = page.locator(".card-title").first.bounding_box()
    assert actions["y"] + actions["height"] <= title["y"], "card actions overlap the title"


@pytest.mark.ui
@pytest.mark.parametrize("dropdown", ["settings", "user"])
def test_menus_open_by_tap_and_ignore_stuck_hover(logged_in_page, touchscreen_mode, board, dropdown):
    page = logged_in_page
    _open_board(page, board["id"])
    trigger = page.locator(f".{dropdown}-dropdown .icon-link")
    menu = page.locator(f"#{dropdown}-dropdown-menu")

    trigger.hover()
    page.wait_for_timeout(100)
    assert menu.is_hidden()

    trigger.click()
    menu.wait_for(state="visible", timeout=8000)
    trigger.click()
    menu.wait_for(state="hidden", timeout=8000)


@pytest.mark.ui
def test_boards_link_has_no_hover_menu(logged_in_page, touchscreen_mode, board):
    page = logged_in_page
    _open_board(page, board["id"])

    page.locator(".nav-link").hover()
    page.wait_for_timeout(100)
    assert page.locator("#boards-dropdown-menu").is_hidden()


@pytest.mark.ui
def test_touch_behaviour_applies_above_mobile_width(browser, ui_base_url, touchscreen_mode, column):
    context = browser.new_context(base_url=ui_base_url, has_touch=True, viewport={"width": 1600, "height": 900})
    page = context.new_page()
    try:
        page.goto("/login.html")
        page.fill("#email", "test-admin@localhost")
        page.fill("#password", "TestAdmin123!")
        page.click("#loginButton")
        page.wait_for_url(lambda url: "login.html" not in url, timeout=10000)
        _open_board(page, column["board_id"])

        assert page.evaluate("window.boardManager.isMobileTouchViewport()") is True
        action = page.locator(".columns-container").evaluate("el => getComputedStyle(el).touchAction")
        assert action == "none"
    finally:
        context.close()
