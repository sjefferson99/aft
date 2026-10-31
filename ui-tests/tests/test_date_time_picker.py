"""UI tests for the date and time picker and the schedule modals (#163)."""
import re
from datetime import datetime, timedelta, timezone

import pytest

DESKTOP = {"width": 1280, "height": 800}
PHONE = {"width": 375, "height": 667}


def _open_board(page, column, viewport=DESKTOP):
    page.set_viewport_size(viewport)
    page.goto(f"/board.html?id={column['board_id']}")
    page.wait_for_function(
        "() => window.boardManager?.hasLoadedBoardData && window.header?.dbConnected", timeout=8000
    )


def _open_new_card(page, column):
    page.evaluate("id => window.boardManager.openAddCardModal(id)", column["id"])
    page.locator("#add-card-modal").wait_for(state="visible", timeout=5000)


def _open_template_modal(page, column):
    page.evaluate("id => window.boardManager.openAddTemplateWithScheduleModal(id)", column["id"])
    page.locator("#add-template-schedule-modal").wait_for(state="visible", timeout=5000)


def _picker_button(page, input_id):
    return page.locator(f"#{input_id} + .date-time-picker-btn")


def _open_picker(page, input_id):
    _picker_button(page, input_id).click()
    popover = page.locator(".date-time-popover")
    popover.wait_for(state="visible", timeout=3000)
    return popover


@pytest.fixture
def card(api_session, ui_base_url, column):
    response = api_session.post(
        f"{ui_base_url}/api/columns/{column['id']}/cards", json={"title": "Picker card"}
    )
    assert response.status_code == 201, response.text
    return response.json()["card"]


@pytest.fixture
def schedule(api_session, ui_base_url, card):
    start = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
    response = api_session.post(f"{ui_base_url}/api/schedules", json={
        "card_id": card["id"], "run_every": 1, "unit": "day", "start_datetime": start,
    })
    assert response.status_code == 201, response.text
    return response.json()["schedule"]


@pytest.mark.ui
def test_grids_set_the_time_and_keep_the_date(logged_in_page, column):
    page = logged_in_page
    _open_board(page, column)
    _open_new_card(page, column)
    page.fill("#card-start-date", "2030-03-04T09:15")

    popover = _open_picker(page, "card-start-date")
    assert popover.locator(".date-time-picker-date").input_value() == "2030-03-04"
    assert popover.locator('[data-hour="09"]').get_attribute("aria-pressed") == "true"
    assert popover.locator('[data-minute="15"]').get_attribute("aria-pressed") == "true"

    popover.locator('[data-hour="17"]').click()
    popover.locator('[data-minute="40"]').click()

    assert page.input_value("#card-start-date") == "2030-03-04T17:40"
    assert popover.locator('[data-hour="17"]').get_attribute("aria-pressed") == "true"
    assert popover.locator('[data-hour="09"]').get_attribute("aria-pressed") == "false"


@pytest.mark.ui
def test_date_change_keeps_the_time(logged_in_page, column):
    page = logged_in_page
    _open_board(page, column)
    _open_new_card(page, column)
    page.fill("#card-start-date", "2030-03-04T09:15")

    popover = _open_picker(page, "card-start-date")
    popover.locator(".date-time-picker-date").fill("2031-05-06")

    assert page.input_value("#card-start-date") == "2031-05-06T09:15"


@pytest.mark.ui
def test_picking_a_time_on_an_empty_field_uses_today(logged_in_page, column):
    page = logged_in_page
    _open_board(page, column)
    _open_new_card(page, column)

    popover = _open_picker(page, "card-end-date")
    popover.locator('[data-hour="08"]').click()

    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T08:00", page.input_value("#card-end-date"))


@pytest.mark.ui
def test_picker_updates_card_date_sync(logged_in_page, column):
    page = logged_in_page
    _open_board(page, column)
    _open_new_card(page, column)
    page.fill("#card-start-date", "2030-03-04T09:00")
    page.fill("#card-end-date", "2030-03-04T10:00")

    popover = _open_picker(page, "card-end-date")
    popover.locator('[data-hour="12"]').click()

    assert page.input_value("#card-duration-hours") == "3"


@pytest.mark.ui
def test_now_and_clear(logged_in_page, column):
    page = logged_in_page
    _open_board(page, column)
    _open_template_modal(page, column)
    page.fill("#template-schedule-end-datetime", "2030-03-04T09:00")

    popover = _open_picker(page, "template-schedule-end-datetime")
    popover.locator('[data-action="clear"]').click()
    assert page.input_value("#template-schedule-end-datetime") == ""
    popover.locator('[data-action="now"]').click()
    value = page.input_value("#template-schedule-end-datetime")
    browser_now = page.evaluate("() => Date.now()")
    picked = page.evaluate("v => new Date(v).getTime()", value)
    assert abs(browser_now - picked) < 2 * 60 * 1000


@pytest.mark.ui
def test_required_field_has_no_clear(logged_in_page, column):
    page = logged_in_page
    _open_board(page, column)
    _open_template_modal(page, column)

    popover = _open_picker(page, "template-schedule-start-datetime")

    assert popover.locator('[data-action="now"]').count() == 1
    assert popover.locator('[data-action="clear"]').count() == 0


@pytest.mark.ui
def test_escape_closes_only_the_picker(logged_in_page, column):
    page = logged_in_page
    _open_board(page, column)
    _open_new_card(page, column)
    _open_picker(page, "card-start-date")

    page.keyboard.press("Escape")

    assert page.locator(".date-time-popover").count() == 0
    assert page.locator("#add-card-modal").is_visible()


@pytest.mark.ui
def test_clicking_outside_closes_only_the_picker(logged_in_page, column):
    page = logged_in_page
    _open_board(page, column)
    _open_new_card(page, column)
    _open_picker(page, "card-start-date")

    page.locator("#add-card-modal h2").first.click()

    assert page.locator(".date-time-popover").count() == 0
    assert page.locator("#add-card-modal").is_visible()


@pytest.mark.ui
def test_edit_card_saves_a_picked_time(logged_in_page, api_session, ui_base_url, column, card):
    page = logged_in_page
    _open_board(page, column)
    page.locator(f'.card[data-card-id="{card["id"]}"] .card-title').click()
    page.locator("#edit-card-modal .card-dates").wait_for(state="visible", timeout=5000)

    popover = _open_picker(page, "edit-card-start-date")
    popover.locator('[data-hour="10"]').click()
    popover.locator('[data-action="done"]').click()

    expected = page.evaluate(
        "() => new Date(document.getElementById('edit-card-start-date').value).toISOString()"
    )

    def saved():
        return api_session.get(f"{ui_base_url}/api/cards/{card['id']}").json()["card"].get("start_date") or ""

    for _ in range(20):
        if saved()[:16] == expected[:16]:
            break
        page.wait_for_timeout(100)
    assert saved()[:16] == expected[:16]


@pytest.mark.ui
def test_buttons_are_named_after_their_field(logged_in_page, column):
    page = logged_in_page
    _open_board(page, column)
    _open_new_card(page, column)

    assert _picker_button(page, "card-start-date").get_attribute("aria-label") == "Pick Start"
    assert _picker_button(page, "card-end-date").get_attribute("aria-label") == "Pick End"


@pytest.mark.ui
def test_picker_works_by_keyboard(logged_in_page, column):
    page = logged_in_page
    _open_board(page, column)
    _open_new_card(page, column)
    page.fill("#card-start-date", "2030-03-04T09:15")

    _picker_button(page, "card-start-date").focus()
    page.keyboard.press("Enter")
    page.locator(".date-time-popover").wait_for(state="visible", timeout=3000)
    assert page.evaluate("document.activeElement.classList.contains('date-time-picker-date')")

    page.locator('[data-hour="17"]').focus()
    page.keyboard.press("Enter")
    assert page.input_value("#card-start-date") == "2030-03-04T17:15"

    page.keyboard.press("Escape")
    assert page.evaluate("document.activeElement.classList.contains('date-time-picker-btn')")


@pytest.mark.ui
def test_disabled_field_has_a_disabled_button(logged_in_page, column):
    page = logged_in_page
    _open_board(page, column)
    page.evaluate("""() => {
      const holder = document.createElement('div');
      holder.innerHTML = '<input type="datetime-local" id="locked" disabled>';
      document.body.appendChild(holder);
      setupDateTimePickers(holder);
    }""")

    assert _picker_button(page, "locked").is_disabled()


@pytest.mark.ui
def test_picker_fits_on_a_phone(logged_in_page, column):
    page = logged_in_page
    _open_board(page, column, PHONE)
    _open_new_card(page, column)

    box = _open_picker(page, "card-end-date").bounding_box()

    assert box["x"] >= 0
    assert box["y"] >= 0
    assert box["x"] + box["width"] <= PHONE["width"]
    assert box["y"] + box["height"] <= PHONE["height"]


@pytest.mark.ui
def test_preview_includes_a_start_of_now(logged_in_page, column):
    page = logged_in_page
    _open_board(page, column)
    _open_template_modal(page, column)

    popover = _open_picker(page, "template-schedule-start-datetime")
    popover.locator('[data-action="now"]').click()
    popover.locator('[data-action="done"]').click()

    first_run = page.locator("#next-runs-list .next-run-item").first.inner_text()
    expected = page.evaluate(
        "() => new Date().toLocaleDateString('en-US', {year: 'numeric', month: 'short', day: 'numeric'})"
    )
    assert expected in first_run


@pytest.mark.ui
def test_create_card_now_from_edit_schedule(logged_in_page, api_session, ui_base_url, column, card, schedule):
    page = logged_in_page
    _open_board(page, column)
    page.evaluate(
        "([id, data]) => window.boardManager.openScheduleModal(id, data, true)",
        [card["id"], {**card, "schedule": schedule["id"]}],
    )
    button = page.locator("#create-card-now-btn")
    button.wait_for(state="visible", timeout=5000)

    button.click()

    page.wait_for_function(
        "() => document.querySelectorAll('.card .card-title').length >= 2", timeout=5000
    )
    assert page.locator("#schedule-modal").is_visible()
    cards = api_session.get(f"{ui_base_url}/api/columns/{column['id']}/cards").json()["cards"]
    assert len(cards) == 2


@pytest.mark.ui
def test_no_create_card_now_on_a_new_schedule(logged_in_page, column, card):
    page = logged_in_page
    _open_board(page, column)
    page.evaluate(
        "([id, data]) => window.boardManager.openScheduleModal(id, data, false)", [card["id"], card]
    )
    page.locator("#schedule-modal").wait_for(state="visible", timeout=5000)

    assert page.locator("#create-card-now-btn").count() == 0
