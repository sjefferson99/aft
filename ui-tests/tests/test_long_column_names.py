"""UI tests for long column names in the column header (#628)."""
import pytest

WORDS = ("Review and sign off by the wider team " * 7)[:255].strip()
UNBROKEN = "X" * 255
SIZES = [(1280, 800), (390, 800)]


def _open_board(page, api_session, ui_base_url, column, name, width, height):
    response = api_session.patch(f"{ui_base_url}/api/columns/{column['id']}", json={"name": name})
    assert response.status_code == 200, response.text
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"/board.html?id={column['board_id']}")
    page.wait_for_function("() => window.boardManager?.hasLoadedBoardData", timeout=8000)
    title = page.locator(f'.column[data-column-id="{column["id"]}"] h4')
    title.wait_for(state="visible", timeout=5000)
    return title


def _is_clamped(title):
    return title.evaluate("el => el.scrollHeight > el.clientHeight")


@pytest.mark.ui
@pytest.mark.parametrize("name", [WORDS, UNBROKEN], ids=["words", "unbroken"])
@pytest.mark.parametrize("width, height", SIZES)
def test_long_name_stays_inside_a_compact_header(
    logged_in_page, api_session, ui_base_url, column, name, width, height
):
    page = logged_in_page
    title = _open_board(page, api_session, ui_base_url, column, name, width, height)
    box = page.locator(f'.column[data-column-id="{column["id"]}"]')

    column_box = box.bounding_box()
    for selector in (".column-actions", ".card-count", "h4"):
        item = box.locator(selector).bounding_box()
        assert item["width"] > 0
        assert item["x"] + item["width"] <= column_box["x"] + column_box["width"], selector
    assert box.evaluate("el => el.scrollWidth <= el.clientWidth")
    assert _is_clamped(title)
    assert box.locator(".column-header").bounding_box()["height"] < 70


@pytest.mark.ui
def test_short_name_is_not_clamped(logged_in_page, api_session, ui_base_url, column):
    title = _open_board(logged_in_page, api_session, ui_base_url, column, "To Do", 1280, 800)

    assert not _is_clamped(title)
    assert title.inner_text() == "To Do"


@pytest.mark.ui
def test_full_name_is_in_the_tooltip_with_quotes_intact(
    logged_in_page, api_session, ui_base_url, column
):
    name = f'Say "hello" and it\'s {WORDS}'[:255].strip()
    title = _open_board(logged_in_page, api_session, ui_base_url, column, name, 1280, 800)

    assert title.get_attribute("title") == name


@pytest.mark.ui
@pytest.mark.parametrize("width, height", SIZES)
def test_clicking_the_name_shows_all_of_it(
    logged_in_page, api_session, ui_base_url, column, width, height
):
    title = _open_board(logged_in_page, api_session, ui_base_url, column, WORDS, width, height)
    assert _is_clamped(title)

    title.click()
    assert not _is_clamped(title)

    title.click()
    assert _is_clamped(title)


@pytest.mark.ui
@pytest.mark.browser_context_args(has_touch=True, is_mobile=True, viewport={"width": 412, "height": 915})
def test_tapping_the_name_shows_all_of_it(logged_in_page, api_session, ui_base_url, column):
    title = _open_board(logged_in_page, api_session, ui_base_url, column, WORDS, 412, 915)
    assert _is_clamped(title)

    title.tap()
    assert not _is_clamped(title)


@pytest.mark.ui
@pytest.mark.parametrize(
    "menu_item, description",
    [
        (".column-archive-after-btn", "#archive-after-description"),
        (".column-move-all-cards-btn", "#move-all-cards-modal-desc"),
    ],
)
def test_long_name_wraps_in_modals(
    logged_in_page, api_session, ui_base_url, column, menu_item, description
):
    page = logged_in_page
    # Move all has nothing to offer on an empty column.
    card = api_session.post(f"{ui_base_url}/api/columns/{column['id']}/cards", json={"title": "A card"})
    assert card.status_code == 201, card.text
    _open_board(page, api_session, ui_base_url, column, UNBROKEN, 1280, 800)

    page.locator(f'.column-menu-btn[data-column-id="{column["id"]}"]').click()
    page.locator(f'.column-menu-dropdown[data-column-id="{column["id"]}"] {menu_item}').click()
    text = page.locator(description)
    text.wait_for(state="visible", timeout=5000)

    assert text.evaluate("el => el.scrollWidth <= el.clientWidth")
