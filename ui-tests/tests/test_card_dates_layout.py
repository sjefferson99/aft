"""UI tests for the compact card date fields on the new and edit card modals (#649)."""
import pytest

MODALS = [
    ("#add-card-modal", "card"),
    ("#edit-card-modal", "edit-card"),
]


def _open_modal(page, column, card, modal_selector, width, height):
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"/board.html?id={column['board_id']}")
    page.wait_for_function(
        "() => window.boardManager?.hasLoadedBoardData && window.header?.dbConnected", timeout=8000
    )
    if modal_selector == "#add-card-modal":
        page.evaluate("id => window.boardManager.openAddCardModal(id)", column["id"])
    else:
        page.locator(f'.card[data-card-id="{card["id"]}"] .card-title').click()
    page.locator(f"{modal_selector} .card-dates").wait_for(state="visible", timeout=5000)


@pytest.fixture
def card(api_session, ui_base_url, column):
    response = api_session.post(
        f"{ui_base_url}/api/columns/{column['id']}/cards", json={"title": "Layout card"}
    )
    assert response.status_code == 201, response.text
    return response.json()["card"]


@pytest.mark.ui
@pytest.mark.parametrize("modal_selector, prefix", MODALS)
def test_dates_take_one_row_on_desktop(logged_in_page, column, card, modal_selector, prefix):
    page = logged_in_page
    _open_modal(page, column, card, modal_selector, 1280, 800)

    assert page.locator(f"{modal_selector} .card-dates").bounding_box()["height"] <= 60
    tops = {
        page.locator(f"#{prefix}-{name}").bounding_box()["y"]
        for name in ("start-date", "end-date", "duration-days", "duration-hours")
    }
    assert len(tops) == 1


@pytest.mark.ui
@pytest.mark.parametrize("width", [320, 375])
@pytest.mark.parametrize("modal_selector, prefix", MODALS)
def test_dates_stay_compact_and_fit_on_phones(logged_in_page, column, card, modal_selector, prefix, width):
    page = logged_in_page
    _open_modal(page, column, card, modal_selector, width, 667)

    assert page.locator(f"{modal_selector} .card-dates").bounding_box()["height"] <= 130

    content = page.locator(f"{modal_selector} .modal-content")
    assert content.evaluate("el => el.scrollWidth <= el.clientWidth")
    content_box = content.bounding_box()
    for name in ("start-date", "end-date", "duration-days", "duration-hours"):
        box = page.locator(f"#{prefix}-{name}").bounding_box()
        assert box["x"] + box["width"] <= content_box["x"] + content_box["width"]

    # Smaller text makes iOS zoom the page when the input gets focus
    font_size = page.locator(f"#{prefix}-start-date").evaluate("el => getComputedStyle(el).fontSize")
    assert font_size == "16px"


@pytest.mark.ui
@pytest.mark.parametrize("modal_selector, prefix", MODALS)
def test_checklist_is_above_the_dates(logged_in_page, column, card, modal_selector, prefix):
    page = logged_in_page
    _open_modal(page, column, card, modal_selector, 1280, 800)

    assert page.locator(f"{modal_selector} .card-dates").evaluate(
        """el => {
            const checklist = el.closest('form').querySelector('.checklist-section');
            return !!(checklist.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING);
        }"""
    )
