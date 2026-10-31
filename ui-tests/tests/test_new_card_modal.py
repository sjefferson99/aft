"""UI tests for new card modal parity with the edit card modal (#626)."""
import pytest


def _open_add_modal(page, column):
    page.goto(f"/board.html?id={column['board_id']}")
    page.wait_for_function(
        "() => window.boardManager?.hasLoadedBoardData && window.header?.dbConnected", timeout=8000
    )
    page.locator(f'.column-add-card-btn[data-column-id="{column["id"]}"]').click()
    page.locator("#card-title").wait_for(state="visible", timeout=5000)


def _closed(page):
    page.locator("#add-card-modal").wait_for(state="detached", timeout=5000)


def _new_card(page, api_session, ui_base_url, column, title):
    card_title = page.locator(".card .card-title", has_text=title)
    card_title.wait_for(timeout=5000)
    card_id = card_title.evaluate("el => el.closest('.card').dataset.cardId")
    response = api_session.get(f"{ui_base_url}/api/cards/{card_id}")
    assert response.status_code == 200, response.text
    return response.json()["card"]


@pytest.mark.ui
def test_modal_matches_edit_layout_without_edit_only_options(logged_in_page, column):
    page = logged_in_page
    _open_add_modal(page, column)

    for selector in ("#card-start-date", "#card-end-date", "#card-duration-days", "#card-duration-hours",
                     "#assign-new-card-btn", "#new-card-schedule-btn", "#add-checklist-item-initial-btn"):
        assert page.locator(f"#add-card-modal {selector}").is_visible()

    header_create = page.locator('#add-card-modal .modal-header-actions button[type="submit"]')
    assert header_create.inner_text() == "Create"

    for selector in ("#delete-card-detail-btn", "#move-card-detail-btn", "#view-planner-btn",
                     "#archive-card-detail-btn", "#new-comment-input"):
        assert page.locator(f"#add-card-modal {selector}").count() == 0


@pytest.mark.ui
def test_dates_and_duration_sync_and_save(logged_in_page, api_session, ui_base_url, column):
    page = logged_in_page
    _open_add_modal(page, column)

    page.fill("#card-title", "Dated card")
    page.fill("#card-start-date", "2030-03-10T09:00")
    page.fill("#card-duration-days", "2")
    page.fill("#card-duration-hours", "3")
    assert page.input_value("#card-end-date") == "2030-03-12T12:00"

    page.locator("#add-card-modal button[type='submit']").click()
    _closed(page)
    card = _new_card(page, api_session, ui_base_url, column, "Dated card")
    assert card["start_date"] is not None
    assert card["end_date"] is not None


@pytest.mark.ui
def test_end_before_start_stays_open(logged_in_page, column):
    page = logged_in_page
    _open_add_modal(page, column)

    page.fill("#card-title", "Bad dates")
    page.fill("#card-start-date", "2030-03-10T09:00")
    page.fill("#card-end-date", "2030-03-09T09:00")
    page.locator("#add-card-modal button[type='submit']").click()

    page.wait_for_timeout(300)
    assert page.locator("#add-card-modal").count() == 1
    assert page.locator(".card .card-title", has_text="Bad dates").count() == 0


@pytest.mark.ui
def test_enter_creates_and_shift_enter_adds_line(logged_in_page, api_session, ui_base_url, column):
    page = logged_in_page
    _open_add_modal(page, column)

    page.fill("#card-title", "Keyboard card")
    description = page.locator("#card-description")
    description.fill("Line one")
    description.press("Shift+Enter")
    description.type("Line two")
    assert page.locator("#add-card-modal").count() == 1

    description.press("Enter")
    _closed(page)
    card = _new_card(page, api_session, ui_base_url, column, "Keyboard card")
    assert card["description"] == "Line one\nLine two"


@pytest.mark.ui
def test_enter_in_date_field_creates(logged_in_page, api_session, ui_base_url, column):
    page = logged_in_page
    _open_add_modal(page, column)

    page.fill("#card-title", "Date Enter card")
    page.fill("#card-duration-days", "1")
    page.locator("#card-duration-days").press("Enter")

    _closed(page)
    _new_card(page, api_session, ui_base_url, column, "Date Enter card")


@pytest.mark.ui
def test_enter_adds_line_in_touchscreen_mode(logged_in_page, column):
    page = logged_in_page
    page.goto(f"/board.html?id={column['board_id']}")
    page.wait_for_function(
        "() => window.boardManager?.hasLoadedBoardData && window.header?.dbConnected", timeout=8000
    )
    page.evaluate(
        """(id) => {
            document.body.classList.add('touchscreen-mode');
            window.boardManager.openAddCardModal(id);
        }""",
        column["id"],
    )

    description = page.locator("#card-description")
    description.fill("Line one")
    description.press("Enter")

    assert description.input_value() == "Line one\n"
    assert page.locator("#add-card-modal").count() == 1


@pytest.mark.ui
def test_escape_warns_only_when_there_is_content(logged_in_page, column):
    page = logged_in_page
    _open_add_modal(page, column)

    page.keyboard.press("Escape")
    _closed(page)

    page.locator(f'.column-add-card-btn[data-column-id="{column["id"]}"]').click()
    page.fill("#card-title", "Keep this")
    page.keyboard.press("Escape")

    page.locator(".modal-app.show").wait_for(timeout=5000)
    assert page.locator("#add-card-modal").count() == 1


@pytest.mark.ui
def test_checklist_saved_in_order_and_empty_row_stays(logged_in_page, api_session, ui_base_url, column):
    page = logged_in_page
    _open_add_modal(page, column)

    page.fill("#card-title", "Checklist card")
    page.locator("#add-checklist-item-initial-btn").click()
    item_input = page.locator("#new-card-checklist-items input.checklist-item-input")
    item_input.fill("First")
    item_input.press("Enter")
    page.locator("#new-card-checklist-items .checklist-item-name", has_text="First").wait_for(timeout=5000)
    item_input.fill("Second")
    item_input.press("Enter")
    page.locator("#new-card-checklist-items .checklist-item-name", has_text="Second").wait_for(timeout=5000)

    # The empty row left by Enter survives blur, and isn't saved
    page.locator("#card-title").click()
    page.wait_for_timeout(100)
    assert page.locator("#new-card-checklist-items input.checklist-item-input").count() == 1
    assert page.locator("#checklist-summary").inner_text() == "0/2 (0%)"

    page.locator("#add-card-modal button[type='submit']").click()
    _closed(page)
    card = _new_card(page, api_session, ui_base_url, column, "Checklist card")
    items = sorted(card["checklist_items"], key=lambda item: item["order"])
    assert [item["name"] for item in items] == ["First", "Second"]


@pytest.mark.ui
def test_assignee_is_saved_with_new_card(logged_in_page, api_session, ui_base_url, column):
    page = logged_in_page
    _open_add_modal(page, column)

    page.fill("#card-title", "Assigned card")
    page.locator("#assign-new-card-btn").click()
    option = page.locator('#assignee-modal .primary-assignee-option:not([data-user-id=""])').first
    user_id = int(option.get_attribute("data-user-id"))
    option.click()
    page.locator("#owner-modal-save-btn").click()

    assert page.locator("#new-card-primary-assignee").inner_text() != ""
    page.locator("#add-card-modal button[type='submit']").click()
    _closed(page)

    card = _new_card(page, api_session, ui_base_url, column, "Assigned card")
    assignees = api_session.get(f"{ui_base_url}/api/cards/{card['id']}/assignees").json()
    assert assignees["primary_assignee"]["id"] == user_id


@pytest.mark.ui
def test_escape_closes_assignee_picker_first(logged_in_page, column):
    page = logged_in_page
    _open_add_modal(page, column)

    page.locator("#assign-new-card-btn").click()
    page.locator("#assignee-modal").wait_for(timeout=5000)
    page.keyboard.press("Escape")

    page.locator("#assignee-modal").wait_for(state="detached", timeout=5000)
    assert page.locator("#add-card-modal").count() == 1


@pytest.mark.ui
def test_create_schedule_creates_card_then_opens_schedule(logged_in_page, api_session, ui_base_url, column):
    page = logged_in_page
    _open_add_modal(page, column)

    page.fill("#card-title", "Scheduled card")
    page.locator("#new-card-schedule-btn").click()

    _closed(page)
    page.locator("#schedule-modal").wait_for(timeout=5000)
    _new_card(page, api_session, ui_base_url, column, "Scheduled card")


@pytest.mark.ui
def test_create_schedule_needs_a_title(logged_in_page, column):
    page = logged_in_page
    _open_add_modal(page, column)

    page.locator("#new-card-schedule-btn").click()

    page.wait_for_timeout(300)
    assert page.locator("#add-card-modal").count() == 1
    assert page.locator("#schedule-modal").count() == 0


@pytest.mark.ui
def test_planner_dates_prefill_the_fields(logged_in_page, column):
    page = logged_in_page
    page.goto(f"/board.html?id={column['board_id']}")
    page.wait_for_function(
        "() => window.boardManager?.hasLoadedBoardData && window.header?.dbConnected", timeout=8000
    )
    page.evaluate(
        """(id) => {
            const start = new Date(2030, 2, 10, 9, 0);
            const end = new Date(2030, 2, 10, 17, 0);
            window.boardManager.openAddCardModal(id, null, false, start.toISOString(), end.toISOString());
        }""",
        column["id"],
    )

    assert page.input_value("#card-start-date") == "2030-03-10T09:00"
    assert page.input_value("#card-end-date") == "2030-03-10T17:00"
    assert page.input_value("#card-duration-hours") == "8"

    # Prefilled dates alone aren't a reason to warn
    page.keyboard.press("Escape")
    _closed(page)
