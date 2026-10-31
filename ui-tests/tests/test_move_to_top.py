"""UI tests for moving a card to the top of its column (#394)."""
import pytest

DESKTOP = {"width": 1280, "height": 800}
MOBILE = {"width": 390, "height": 800}


@pytest.fixture
def cards(api_session, ui_base_url, column):
    created = []
    for title in ("First card", "Second card", "Third card"):
        response = api_session.post(f"{ui_base_url}/api/columns/{column['id']}/cards", json={"title": title})
        assert response.status_code == 201, response.text
        created.append(response.json()["card"])
    return created


@pytest.fixture
def set_card_actions(api_session, ui_base_url):
    url = f"{ui_base_url}/api/settings/card_actions"

    def _set(desktop, mobile):
        response = api_session.put(url, json={"value": {"desktop": desktop, "mobile": mobile}})
        assert response.status_code == 200, response.text

    yield _set
    api_session.put(url, json={"value": None})


def _open_board(page, column, viewport=DESKTOP):
    page.set_viewport_size(viewport)
    page.goto(f"/board.html?id={column['board_id']}")
    page.wait_for_function(
        "() => window.boardManager?.hasLoadedBoardData && window.header?.dbConnected", timeout=8000
    )


def _open_card(page, card):
    page.locator(f'.card[data-card-id="{card["id"]}"] .card-title').click()
    page.locator("#edit-card-title").wait_for(state="visible", timeout=5000)


def _titles(page, column):
    return page.locator(f'.column-cards[data-column-id="{column["id"]}"] .card-title').all_inner_texts()


def _wait_for_top(page, column, title):
    page.wait_for_function(
        """([columnId, title]) => document.querySelector(
            `.column-cards[data-column-id="${columnId}"] .card-title`
        )?.textContent.trim() === title""",
        arg=[column["id"], title],
        timeout=5000,
    )


@pytest.mark.ui
def test_top_button_moves_card_and_closes_modal(logged_in_page, column, cards):
    page = logged_in_page
    _open_board(page, column)
    _open_card(page, cards[2])

    page.locator("#move-to-top-detail-btn").click()

    page.locator("#edit-card-modal").wait_for(state="detached", timeout=5000)
    _wait_for_top(page, column, "Third card")
    assert _titles(page, column) == ["Third card", "First card", "Second card"]


@pytest.mark.ui
def test_order_is_saved(logged_in_page, api_session, ui_base_url, column, cards):
    page = logged_in_page
    _open_board(page, column)
    _open_card(page, cards[1])
    page.locator("#move-to-top-detail-btn").click()
    _wait_for_top(page, column, "Second card")

    page.reload()
    page.wait_for_function("() => window.boardManager?.hasLoadedBoardData", timeout=8000)
    assert _titles(page, column) == ["Second card", "First card", "Third card"]


@pytest.mark.ui
def test_top_button_disabled_for_first_card(logged_in_page, column, cards):
    page = logged_in_page
    _open_board(page, column)
    _open_card(page, cards[0])

    top_btn = page.locator("#move-to-top-detail-btn")
    assert top_btn.is_disabled()
    assert top_btn.get_attribute("title") == "Already at the top"


@pytest.mark.ui
def test_top_button_saves_edits_first(logged_in_page, api_session, ui_base_url, column, cards):
    page = logged_in_page
    _open_board(page, column)
    _open_card(page, cards[2])

    page.fill("#edit-card-title", "Renamed then moved")
    page.locator("#move-to-top-detail-btn").click()

    _wait_for_top(page, column, "Renamed then moved")
    card = api_session.get(f"{ui_base_url}/api/cards/{cards[2]['id']}").json()["card"]
    assert card["title"] == "Renamed then moved"


@pytest.mark.ui
def test_card_button_leaves_first_card_first(logged_in_page, column, cards, set_card_actions):
    set_card_actions(["top"], ["top"])
    page = logged_in_page
    _open_board(page, column)

    button = page.locator(f'.card-top-btn[data-card-id="{cards[0]["id"]}"]')
    button.wait_for(state="visible", timeout=5000)
    button.click()

    page.wait_for_timeout(500)
    assert _titles(page, column) == ["First card", "Second card", "Third card"]


@pytest.mark.ui
def test_no_top_button_when_read_only(logged_in_page, column, cards):
    page = logged_in_page
    _open_board(page, column)
    page.evaluate(
        """async (id) => {
            window.boardManager.canEdit = false;
            const data = await window.boardManager.getCardData(id);
            window.boardManager.openEditCardModal(id, data);
        }""",
        cards[2]["id"],
    )
    page.locator("#edit-card-title").wait_for(state="visible", timeout=5000)

    assert page.locator("#move-to-top-detail-btn").count() == 0


@pytest.mark.ui
@pytest.mark.parametrize("viewport", [DESKTOP, MOBILE])
def test_card_button_hidden_by_default(logged_in_page, column, cards, viewport):
    page = logged_in_page
    _open_board(page, column, viewport)

    assert page.locator(".card-top-btn").first.is_hidden()


@pytest.mark.ui
@pytest.mark.parametrize("viewport", [DESKTOP, MOBILE])
def test_card_button_moves_card_when_chosen(logged_in_page, column, cards, set_card_actions, viewport):
    set_card_actions(["top"], ["top"])
    page = logged_in_page
    _open_board(page, column, viewport)

    button = page.locator(f'.card-top-btn[data-card-id="{cards[2]["id"]}"]')
    button.wait_for(state="visible", timeout=5000)
    button.click()

    _wait_for_top(page, column, "Third card")
    assert page.locator("#edit-card-modal").count() == 0


@pytest.mark.ui
@pytest.mark.parametrize("viewport, max_height", [(DESKTOP, 36), (MOBILE, 36)])
def test_action_row_stays_on_one_line(logged_in_page, column, cards, viewport, max_height):
    page = logged_in_page
    _open_board(page, column, viewport)
    _open_card(page, cards[2])

    assert page.locator("#edit-card-modal .modal-header-actions").bounding_box()["height"] <= max_height


@pytest.mark.ui
def test_t_shortcut_moves_hovered_card(logged_in_page, column, cards):
    page = logged_in_page
    _open_board(page, column)

    page.locator(f'.card[data-card-id="{cards[2]["id"]}"] .card-title').hover()
    page.keyboard.press("t")

    _wait_for_top(page, column, "Third card")


@pytest.mark.ui
def test_t_shortcut_needs_a_hovered_card(logged_in_page, column, cards):
    page = logged_in_page
    _open_board(page, column)

    page.mouse.move(0, 0)
    page.keyboard.press("t")

    page.wait_for_timeout(300)
    assert _titles(page, column) == ["First card", "Second card", "Third card"]


@pytest.mark.ui
def test_t_shortcut_ignored_while_typing(logged_in_page, column, cards):
    page = logged_in_page
    _open_board(page, column)
    _open_card(page, cards[2])

    title = page.locator("#edit-card-title")
    title.fill("")
    title.type("t")

    assert title.input_value() == "t"
    assert page.locator("#edit-card-modal").count() == 1


def _search(page, text):
    search = page.locator("#board-header-search-input")
    search.fill(text)
    page.wait_for_function(
        """expected => document.querySelectorAll('.card').length === expected""",
        arg=1 if text else 3,
        timeout=8000,
    )


@pytest.mark.ui
def test_top_button_goes_above_cards_hidden_by_search(logged_in_page, column, cards):
    """Filter to find a card, move it up, and it's first after clearing the filter."""
    page = logged_in_page
    _open_board(page, column)

    _search(page, "Third")
    _open_card(page, cards[2])
    top_btn = page.locator("#move-to-top-detail-btn")
    assert top_btn.is_enabled()
    top_btn.click()
    page.locator("#edit-card-modal").wait_for(state="detached", timeout=5000)

    _search(page, "")
    assert _titles(page, column) == ["Third card", "First card", "Second card"]


@pytest.mark.ui
def test_t_shortcut_goes_above_cards_hidden_by_search(logged_in_page, api_session, ui_base_url, column, cards):
    page = logged_in_page
    _open_board(page, column)

    _search(page, "Third")
    # Shortcuts are ignored while the search box has focus
    page.locator("#board-header-search-input").blur()
    page.locator(f'.card[data-card-id="{cards[2]["id"]}"] .card-title').hover()
    page.keyboard.press("t")

    def _order():
        return api_session.get(f"{ui_base_url}/api/cards/{cards[2]['id']}").json()["card"]["order"]

    for _ in range(50):
        if _order() == 0:
            break
        page.wait_for_timeout(100)
    assert _order() == 0

    _search(page, "")
    assert _titles(page, column) == ["Third card", "First card", "Second card"]


@pytest.mark.ui
def test_t_types_into_search_box_while_it_has_focus(logged_in_page, column, cards):
    page = logged_in_page
    _open_board(page, column)

    search = page.locator("#board-header-search-input")
    search.fill("Third")
    page.locator(f'.card[data-card-id="{cards[2]["id"]}"] .card-title').hover()
    page.keyboard.press("t")

    assert search.input_value() == "Thirdt"
