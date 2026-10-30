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


def _create_columns(api_session, ui_base_url, board, names):
    for name in names:
        response = api_session.post(f"{ui_base_url}/api/boards/{board['id']}/columns", json={"name": name})
        assert response.status_code == 201


def _column_names(page):
    return [name.split(" (")[0] for name in page.locator(".column h4").all_inner_texts()]


def _column_named(page, name):
    return page.locator(".column").filter(has=page.locator("h4", has_text=name))


def _submit_new_column(page, name):
    page.fill("#column-name", name)
    page.click("#add-column-form button[type='submit']")
    _column_named(page, name).wait_for(state="visible", timeout=5000)


def _hover_column_side(page, name, side):
    """Rest the mouse over the left or right quarter of a column."""
    box = _column_named(page, name).bounding_box()
    fraction = 0.25 if side == "left" else 0.75
    page.mouse.move(box["x"] + box["width"] * fraction, box["y"] + box["height"] / 2)


@pytest.mark.ui
def test_column_insert_button_adds_column_in_the_gap(logged_in_page, api_session, ui_base_url, board):
    """The + between two columns inserts the new column there."""
    _create_columns(api_session, ui_base_url, board, ["A", "B"])
    page = logged_in_page
    page.goto(f"/board.html?id={board['id']}")

    page.locator(".column-insert-btn").click()
    _submit_new_column(page, "Between")

    assert _column_names(page) == ["A", "Between", "B"]


@pytest.mark.ui
def test_column_insert_button_sits_in_gap_without_widening_board(logged_in_page, api_session, ui_base_url, board):
    """The + fits in the margin between columns, and its tooltip appears after a pause."""
    _create_columns(api_session, ui_base_url, board, ["A", "B", "C"])
    page = logged_in_page
    page.goto(f"/board.html?id={board['id']}")

    buttons = page.locator(".column-insert-btn")
    buttons.first.wait_for(state="visible", timeout=5000)
    assert buttons.count() == 2  # only between columns, not after the last one

    first = page.locator(".column").nth(0).bounding_box()
    second = page.locator(".column").nth(1).bounding_box()
    button = buttons.nth(0).bounding_box()
    left_edge = first["x"] + first["width"]
    assert second["x"] - left_edge == 20
    assert button["x"] >= left_edge
    assert button["x"] + button["width"] <= second["x"]

    scroll_width = page.locator(".columns-container").evaluate("el => el.scrollWidth")
    tooltip_opacity = "el => Number(getComputedStyle(el, '::after').opacity)"
    buttons.nth(0).hover()
    assert buttons.nth(0).evaluate(tooltip_opacity) == 0  # the pause, not shown at once
    page.wait_for_function(
        "el => getComputedStyle(el, '::after').opacity === '1'",
        arg=buttons.nth(0).element_handle(),
        timeout=2000,
    )
    assert buttons.nth(0).get_attribute("data-tooltip") == "Add new column"
    assert page.locator(".column").nth(1).bounding_box()["x"] == second["x"]
    assert page.locator(".columns-container").evaluate("el => el.scrollWidth") == scroll_width


@pytest.mark.ui
@pytest.mark.parametrize(
    "hover_column, side, expected",
    [
        ("A", "left", ["New", "A", "B"]),
        ("B", "left", ["A", "New", "B"]),
        ("A", "right", ["A", "New", "B"]),
        ("B", "right", ["A", "B", "New"]),
    ],
)
def test_c_shortcut_adds_column_nearest_mouse(
    logged_in_page, api_session, ui_base_url, board, hover_column, side, expected
):
    """Pressing C inserts on whichever side of the hovered column the mouse is on."""
    _create_columns(api_session, ui_base_url, board, ["A", "B"])
    page = logged_in_page
    page.goto(f"/board.html?id={board['id']}")
    _column_named(page, "A").wait_for(state="visible", timeout=5000)

    _hover_column_side(page, hover_column, side)
    page.keyboard.press("c")

    assert page.input_value("#column-name") == ""  # the key must not reach the input
    _submit_new_column(page, "New")
    assert _column_names(page) == expected


@pytest.mark.ui
def test_ctrl_c_does_not_open_add_column_modal(logged_in_page, column):
    """Copying on a board must not trigger the C shortcut."""
    page = logged_in_page
    page.goto(f"/board.html?id={column['board_id']}")
    page.locator(".column", has_text=column["name"]).wait_for(state="visible", timeout=5000)

    page.keyboard.press("Control+c")

    assert page.locator("#add-column-modal").count() == 0


@pytest.mark.ui
def test_shortcuts_ignored_while_confirm_dialog_open(logged_in_page, column):
    """Board shortcuts must not open a modal over an app confirm dialog."""
    page = logged_in_page
    page.goto(f"/board.html?id={column['board_id']}")

    page.locator(f'.column-menu-btn[data-column-id="{column["id"]}"]').click()
    page.locator(f'.column-delete-btn[data-column-id="{column["id"]}"]').click()
    page.locator("#appModal").wait_for(state="visible", timeout=5000)

    page.keyboard.press("c")

    assert page.locator("#add-column-modal").count() == 0


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
    _assert_title_wraps(title)


@pytest.mark.ui
def test_long_title_wraps_in_template_schedule_modal_on_mobile(logged_in_page, column):
    """The add template + schedule modal's title wraps the same way (#432)."""
    page = logged_in_page
    page.set_viewport_size({"width": 375, "height": 740})
    page.goto(f"/board.html?id={column['board_id']}")
    page.locator(f'.column-cards[data-column-id="{column["id"]}"]').wait_for(state="attached", timeout=5000)
    page.evaluate("columnId => window.boardManager.openAddTemplateWithScheduleModal(columnId)", column["id"])

    title = page.locator("#template-title")
    title.wait_for(state="visible", timeout=5000)
    title.fill(LONG_TITLE)
    _assert_title_wraps(title)


def _open_long_mobile_column(page, api_session, ui_base_url, column, width=360, height=726):
    """Open a board on a phone-sized viewport with enough cards to scroll the column."""
    for index in range(12):
        resp = api_session.post(
            f"{ui_base_url}/api/columns/{column['id']}/cards",
            json={"title": f"Card {index}", "description": "Some text " * 8},
        )
        assert resp.status_code == 201

    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"/board.html?id={column['board_id']}")
    page.locator(f'.column-cards[data-column-id="{column["id"]}"] .add-card-btn').wait_for(state="attached", timeout=5000)


def _add_card_button_bottom_at_max_scroll(page, column):
    """Scroll the column to its end and return the Add Card button's bottom edge."""
    return page.evaluate(
        """columnId => {
          const list = document.querySelector(`.column-cards[data-column-id="${columnId}"]`);
          list.scrollTop = list.scrollHeight;
          return list.querySelector('.add-card-btn').getBoundingClientRect().bottom;
        }""",
        column["id"],
    )


@pytest.mark.ui
def test_mobile_board_height_follows_measured_viewport(logged_in_page, api_session, ui_base_url, column):
    """The board is sized from the measured space, not 100dvh less a fixed header height (#515)."""
    page = logged_in_page
    _open_long_mobile_column(page, api_session, ui_base_url, column)

    # A taller header would push the board off screen with a fixed offset.
    page.add_style_tag(content=".header { padding-bottom: 60px !important; }")
    page.evaluate("window.dispatchEvent(new Event('resize'))")
    page.wait_for_function(
        "() => document.querySelector('.canvas').getBoundingClientRect().bottom <= window.innerHeight",
        timeout=5000,
    )

    assert _add_card_button_bottom_at_max_scroll(page, column) <= 726


@pytest.mark.ui
def test_mobile_board_height_updates_when_header_loads_late(logged_in_page, api_session, ui_base_url, column):
    """A header that arrives after the board must not leave a stale height (#515)."""
    page = logged_in_page
    held_header_requests = []
    # On the context, not the page: the service worker makes this request.
    page.context.route("**/components/header.html", lambda route: held_header_requests.append(route))
    _open_long_mobile_column(page, api_session, ui_base_url, column)
    page.wait_for_timeout(300)
    assert held_header_requests, "Header should still be loading after the board has rendered"

    held_header_requests[0].continue_()
    page.locator(".header").wait_for(state="attached", timeout=5000)

    page.wait_for_function(
        "() => document.querySelector('.canvas').getBoundingClientRect().bottom <= window.innerHeight",
        timeout=5000,
    )


@pytest.mark.ui
def test_mobile_board_fits_short_viewport(logged_in_page, api_session, ui_base_url, column):
    """The minimum board height must not push the board off a short landscape screen (#515)."""
    page = logged_in_page
    _open_long_mobile_column(page, api_session, ui_base_url, column, width=740, height=320)

    page.wait_for_function(
        "() => document.querySelector('.canvas').getBoundingClientRect().bottom <= window.innerHeight",
        timeout=5000,
    )


@pytest.mark.ui
def test_add_card_button_reachable_when_column_overflows_screen(logged_in_page, api_session, ui_base_url, column):
    """Add Card stays reachable when the board overshoots the screen, as in an installed PWA (#515)."""
    page = logged_in_page
    _open_long_mobile_column(page, api_session, ui_base_url, column)

    # The overshoot measured on an affected phone: 50px past the visible area.
    page.add_style_tag(content=".board-page .canvas { height: calc(100dvh - 12px) !important; }")

    assert _add_card_button_bottom_at_max_scroll(page, column) <= 726


def _assert_title_wraps(title):
    """Assert a title field shows every line of a long title within a 375px viewport."""
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
