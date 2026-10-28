"""UI tests for the core column/card workflow inside a board."""
import pytest


@pytest.mark.ui
def test_add_column_to_board(logged_in_page, board):
    """Adding a column through the modal renders it on the board."""
    page = logged_in_page
    page.goto(f"/board.html?id={board['id']}")

    # Either the empty-state button or the inline "+ Add Column" button is
    # present depending on whether any columns already exist.
    page.locator("#add-column-empty-btn, #add-column-inline-btn").click()
    page.fill("#column-name", "To Do")
    page.click("#add-column-form button[type='submit']")

    column = page.locator(".column", has_text="To Do")
    column.wait_for(state="visible", timeout=5000)


@pytest.mark.ui
def test_add_card_to_column(logged_in_page, column):
    """Adding a card through the modal renders it inside the target column."""
    page = logged_in_page
    page.goto(f"/board.html?id={column['board_id']}")

    page.locator(f'.column-add-card-btn[data-column-id="{column["id"]}"]').click()
    page.fill("#card-title", "Write the docs")
    page.click("#add-card-form button[type='submit']")

    card_in_column = page.locator(
        f'.column-cards[data-column-id="{column["id"]}"] .card-title',
        has_text="Write the docs",
    )
    card_in_column.wait_for(state="visible", timeout=5000)


@pytest.mark.ui
def test_card_timestamp_tooltip_format(logged_in_page, api_session, ui_base_url, column):
    """The card's last-updated tooltip matches the toLocale*String format it replaced.

    utils.js caches Intl.DateTimeFormat instances rather than calling
    toLocaleDateString/toLocaleTimeString per timestamp; the output must not change.
    """
    resp = api_session.post(f"{ui_base_url}/api/columns/{column['id']}/cards", json={"title": "Timestamped"})
    assert resp.status_code == 201
    card = resp.json()["card"]

    page = logged_in_page
    page.goto(f"/board.html?id={column['board_id']}")
    timestamp = page.locator(f'.card[data-card-id="{card["id"]}"] .card-timestamp')
    timestamp.wait_for(state="attached", timeout=5000)

    expected = page.evaluate(
        """(updatedAt) => {
          const date = parseTimestampAsUtc(updatedAt);
          const timeZone = sessionStorage.getItem('timezone') || 'UTC';
          const twelveHour = sessionStorage.getItem('timeFormat') === '12';
          const datePart = date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone });
          const timePart = twelveHour
            ? date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true, timeZone })
            : date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone });
          return `${datePart} ${timePart}`;
        }""",
        card["updated_at"],
    )
    assert timestamp.get_attribute("data-tooltip") == expected
    assert timestamp.get_attribute("aria-label") == f"Last updated {expected}"
