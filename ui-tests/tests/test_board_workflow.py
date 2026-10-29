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


LONG_TITLE = "A very long card title that needs to wrap onto several lines on a phone screen"


@pytest.mark.ui
def test_long_card_title_wraps_in_edit_modal_on_mobile(logged_in_page, api_session, ui_base_url, column):
    """A long title in the card modal wraps to fit the phone viewport (#432)."""
    resp = api_session.post(f"{ui_base_url}/api/columns/{column['id']}/cards", json={"title": LONG_TITLE})
    assert resp.status_code == 201
    card = resp.json()["card"]

    page = logged_in_page
    page.set_viewport_size({"width": 375, "height": 740})
    page.goto(f"/board.html?id={column['board_id']}")
    page.locator(f'.card[data-card-id="{card["id"]}"] .card-title').click()

    title = page.locator("#edit-card-title")
    title.wait_for(state="visible", timeout=5000)
    assert title.input_value() == LONG_TITLE

    sizes = title.evaluate(
        "el => ({ scrollWidth: el.scrollWidth, clientWidth: el.clientWidth,"
        " scrollHeight: el.scrollHeight, clientHeight: el.clientHeight,"
        " lineHeight: parseFloat(getComputedStyle(el).lineHeight),"
        " right: el.getBoundingClientRect().right })"
    )
    assert sizes["scrollWidth"] <= sizes["clientWidth"], "title should not scroll sideways"
    assert sizes["scrollHeight"] <= sizes["clientHeight"], "title should grow to show every line"
    assert sizes["clientHeight"] > sizes["lineHeight"] * 2, "long title should span multiple lines"
    assert sizes["right"] <= 375, "title should stay within the viewport"


@pytest.mark.ui
def test_card_title_stays_single_line_and_enter_submits(logged_in_page, column):
    """The wrapping title field still behaves like a one-line input."""
    page = logged_in_page
    page.goto(f"/board.html?id={column['board_id']}")

    page.locator(f'.column-add-card-btn[data-column-id="{column["id"]}"]').click()
    title = page.locator("#card-title")
    title.wait_for(state="visible", timeout=5000)

    # Pasted line breaks become spaces rather than multi-line titles.
    title.evaluate(
        "el => { el.value = 'Line one\\nLine two'; el.dispatchEvent(new Event('input', { bubbles: true })); }"
    )
    assert title.input_value() == "Line one Line two"

    title.press("Enter")
    page.locator("#add-card-modal").wait_for(state="detached", timeout=5000)
    page.locator(
        f'.column-cards[data-column-id="{column["id"]}"] .card-title',
        has_text="Line one Line two",
    ).wait_for(state="visible", timeout=5000)
