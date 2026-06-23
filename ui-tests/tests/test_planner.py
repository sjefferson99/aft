"""UI tests for the planner view: the edit-card modal's planner button and
the month view's column/time display toggles."""
import calendar
from datetime import datetime, timezone

import pytest


def _create_card(api_session, ui_base_url, column_id, **kwargs):
    payload = {'title': kwargs.pop('title', 'Planner UI test card')}
    payload.update(kwargs)
    response = api_session.post(f'{ui_base_url}/api/columns/{column_id}/cards', json=payload)
    assert response.status_code == 201, response.text
    return response.json()['card']


def _future_month_date(months_ahead, day=15, hour=9, minute=0):
    """A UTC datetime `months_ahead` months from now, fixed on `day` to dodge
    end-of-month rollover (e.g. Feb 30). UTC matches the 'Z' suffix sent to
    the API; the browser then renders it back in local time."""
    now = datetime.now(timezone.utc)
    total_months = now.month - 1 + months_ahead
    year = now.year + total_months // 12
    month = total_months % 12 + 1
    return datetime(year, month, day, hour, minute)


def _to_local(naive_utc_dt):
    """Convert a naive UTC datetime to the test runner's local time, to
    match what the browser (running on the same host) renders."""
    return naive_utc_dt.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)


@pytest.mark.ui
def test_place_in_planner_always_enabled_and_places_card(logged_in_page, api_session, ui_base_url, column):
    """A card with no dates shows the always-enabled "Place in Planner"
    button; using it drops the card into placement mode, and clicking a day
    in the resulting month grid schedules it (defaulting to a 1 hour task)."""
    card = _create_card(api_session, ui_base_url, column['id'], title='Unscheduled task')

    page = logged_in_page
    page.goto(f"/board.html?id={column['board_id']}")
    page.locator(f'.card[data-card-id="{card["id"]}"]').click()

    planner_btn = page.locator('#view-planner-btn')
    planner_btn.wait_for(state='visible', timeout=5000)
    assert 'Place in Planner' in planner_btn.inner_text()
    assert planner_btn.get_attribute('disabled') is None

    planner_btn.click()

    # Lands on the year view in placement mode - drill into the current
    # month, then click any day to place the card there.
    current_month = datetime.now().month
    page.locator(f'.planner-month-block[data-month="{current_month}"]').click()
    page.locator('.planner-day-cell').first.click()

    toast = page.locator('.success-toast')
    toast.wait_for(state='visible', timeout=5000)
    assert 'Unscheduled task' in toast.inner_text()


@pytest.mark.ui
def test_view_in_planner_jumps_to_month_of_start_date(logged_in_page, api_session, ui_base_url, column):
    """A card with only a start date set shows "View in Planner" and jumps
    straight to that date's month instead of entering placement mode."""
    target = _future_month_date(months_ahead=2)
    card = _create_card(
        api_session, ui_base_url, column['id'], title='Scheduled task',
        start_date=target.strftime('%Y-%m-%dT%H:%M:%S') + 'Z',
    )

    page = logged_in_page
    page.goto(f"/board.html?id={column['board_id']}")
    page.locator(f'.card[data-card-id="{card["id"]}"]').click()

    planner_btn = page.locator('#view-planner-btn')
    planner_btn.wait_for(state='visible', timeout=5000)
    assert 'View in Planner' in planner_btn.inner_text()

    planner_btn.click()

    month_label = page.locator('.planner-month-label')
    month_label.wait_for(state='visible', timeout=5000)
    local_target = _to_local(target)
    expected = f'{calendar.month_name[local_target.month]} {local_target.year}'
    assert month_label.inner_text() == expected


@pytest.mark.ui
def test_typing_start_date_then_view_in_planner_saves_and_jumps_to_month(logged_in_page, api_session, ui_base_url, column):
    """Regression test: typing just a start date into the edit-card modal
    (rather than it arriving already-set from the API) used to (a) never
    autosave on blur, since that required both start and end, and (b) race
    showPlannerView()'s default "open on the current year" render, so the
    button sometimes landed on the year view instead of the card's month."""
    card = _create_card(api_session, ui_base_url, column['id'], title='Typed date task')

    now = datetime.now()
    total_months = now.month - 1 + 4
    target_year = now.year + total_months // 12
    target_month = total_months % 12 + 1
    local_value = f'{target_year:04d}-{target_month:02d}-15T09:00'

    page = logged_in_page
    page.goto(f"/board.html?id={column['board_id']}")
    page.locator(f'.card[data-card-id="{card["id"]}"]').click()

    start_input = page.locator('#edit-card-start-date')
    start_input.wait_for(state='visible', timeout=5000)
    start_input.fill(local_value)
    page.locator('#edit-card-title').click()  # blur the date field to trigger autosave

    planner_btn = page.locator('#view-planner-btn')
    assert 'View in Planner' in planner_btn.inner_text()
    planner_btn.click()

    month_label = page.locator('.planner-month-label')
    month_label.wait_for(state='visible', timeout=5000)
    expected = f'{calendar.month_name[target_month]} {target_year}'
    assert month_label.inner_text() == expected
    assert page.locator('.planner-year-grid').count() == 0

    card_response = api_session.get(f'{ui_base_url}/api/cards/{card["id"]}')
    assert card_response.status_code == 200, card_response.text
    assert card_response.json()['card']['start_date'] is not None


@pytest.mark.ui
def test_overflow_expand_collapse(logged_in_page, api_session, ui_base_url, column):
    """Creating more than PLANNER_MAX_CHIPS_PER_DAY (3) cards on the same day
    shows a '+N more' button. Clicking it reveals the hidden chips and changes
    the button text to 'Show less'. Clicking again collapses back."""
    target = _future_month_date(months_ahead=1, day=15)
    date_str = target.strftime('%Y-%m-%dT%H:%M:%S') + 'Z'

    cards = []
    for i in range(4):
        cards.append(_create_card(
            api_session, ui_base_url, column['id'],
            title=f'Overflow card {i + 1}',
            start_date=date_str,
        ))

    page = logged_in_page
    page.goto(f"/board.html?id={column['board_id']}")
    page.locator(f'.card[data-card-id="{cards[0]["id"]}"]').click()
    page.locator('#view-planner-btn').click()
    page.locator('.planner-month-label').wait_for(state='visible', timeout=5000)

    more_btn = page.locator('.planner-day-more')
    more_btn.wait_for(state='visible', timeout=5000)
    assert '+1 more' in more_btn.inner_text()

    # Exactly 3 of the 4 chips should be in the DOM before expanding
    def chip_dom_count():
        return sum(
            page.locator(f'.planner-card-chip[data-card-id="{c["id"]}"]').count()
            for c in cards
        )

    assert chip_dom_count() == 3

    more_btn.click()

    # All 4 chips now in DOM; button text flipped
    page.locator(f'.planner-day-more:text("Show less")').wait_for(state='visible', timeout=3000)
    assert chip_dom_count() == 4

    more_btn.click()

    # Overflow chip removed from DOM on collapse; button reverts
    page.locator(f'.planner-day-more:text("more")').wait_for(state='visible', timeout=3000)
    assert chip_dom_count() == 3
    assert '+1 more' in more_btn.inner_text()


@pytest.mark.ui
def test_show_columns_and_show_times_toggles_render_on_chip(logged_in_page, api_session, ui_base_url, column):
    """The month view's "Show columns"/"Show times" checkboxes add the
    card's column name and start/end time to its chip when checked."""
    target = _future_month_date(months_ahead=3, hour=9, minute=0)
    end = target.replace(hour=10, minute=30)
    card = _create_card(
        api_session, ui_base_url, column['id'], title='Timed task',
        start_date=target.strftime('%Y-%m-%dT%H:%M:%S') + 'Z',
        end_date=end.strftime('%Y-%m-%dT%H:%M:%S') + 'Z',
    )

    page = logged_in_page
    page.goto(f"/board.html?id={column['board_id']}")
    page.locator(f'.card[data-card-id="{card["id"]}"]').click()
    page.locator('#view-planner-btn').click()
    page.locator('.planner-month-label').wait_for(state='visible', timeout=5000)

    chip = page.locator(f'.planner-card-chip[data-card-id="{card["id"]}"]')
    chip.wait_for(state='visible', timeout=5000)
    assert chip.locator('.planner-card-chip-column').count() == 0
    assert chip.locator('.planner-card-chip-time').count() == 0

    page.locator('#planner-show-columns-toggle').check()
    chip = page.locator(f'.planner-card-chip[data-card-id="{card["id"]}"]')
    assert chip.locator('.planner-card-chip-column').inner_text() == column['name']

    page.locator('#planner-show-times-toggle').check()
    chip = page.locator(f'.planner-card-chip[data-card-id="{card["id"]}"]')
    time_text = chip.locator('.planner-card-chip-time').inner_text()
    assert _to_local(target).strftime('%H:%M') in time_text
    assert _to_local(end).strftime('%H:%M') in time_text
