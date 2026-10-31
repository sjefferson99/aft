"""UI tests for edit card auto save and keyboard behaviour (#625)."""
import pytest


def _create_card(api_session, ui_base_url, column, **fields):
    payload = {"title": "Autosave card", **fields}
    response = api_session.post(f"{ui_base_url}/api/columns/{column['id']}/cards", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["card"]


def _add_item(api_session, ui_base_url, card, name):
    response = api_session.post(f"{ui_base_url}/api/cards/{card['id']}/checklist-items", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["checklist_item"]


def _get_card(api_session, ui_base_url, card):
    response = api_session.get(f"{ui_base_url}/api/cards/{card['id']}")
    assert response.status_code == 200, response.text
    return response.json()["card"]


def _open_card(page, board_id, card):
    page.goto(f"/board.html?id={board_id}")
    page.locator(f'.card[data-card-id="{card["id"]}"] .card-title').click()
    page.locator("#edit-card-title").wait_for(state="visible", timeout=5000)


def _wait_saved(page):
    page.locator("#card-save-status", has_text="Saved").wait_for(timeout=5000)


def _closed(page):
    page.locator("#edit-card-modal").wait_for(state="detached", timeout=5000)


def _checklist_names(api_session, ui_base_url, card):
    items = _get_card(api_session, ui_base_url, card)["checklist_items"]
    return [item["name"] for item in sorted(items, key=lambda item: item["order"])]


@pytest.mark.ui
def test_modal_has_no_save_button(logged_in_page, api_session, ui_base_url, column):
    card = _create_card(api_session, ui_base_url, column)
    page = logged_in_page
    _open_card(page, column["board_id"], card)

    assert page.locator('#edit-card-modal button[type="submit"]').count() == 0
    assert page.locator("#cancel-edit-card-btn").inner_text() == "Close"


@pytest.mark.ui
def test_fields_save_on_blur_with_indicator(logged_in_page, api_session, ui_base_url, column):
    card = _create_card(api_session, ui_base_url, column)
    page = logged_in_page
    _open_card(page, column["board_id"], card)

    page.fill("#edit-card-title", "Renamed on blur")
    page.locator("#edit-card-description").click()
    _wait_saved(page)
    assert _get_card(api_session, ui_base_url, card)["title"] == "Renamed on blur"

    page.fill("#edit-card-description", "Described on blur")
    page.locator("#edit-card-title").click()
    page.wait_for_function(
        "() => document.querySelector('#card-save-status').textContent !== 'Saving...'", timeout=5000
    )
    _wait_saved(page)
    assert _get_card(api_session, ui_base_url, card)["description"] == "Described on blur"


@pytest.mark.ui
def test_clearing_dates_saves(logged_in_page, api_session, ui_base_url, column):
    card = _create_card(api_session, ui_base_url, column, start_date="2030-01-15T09:00:00Z")
    page = logged_in_page
    _open_card(page, column["board_id"], card)

    page.fill("#edit-card-start-date", "")
    page.locator("#edit-card-title").click()
    _wait_saved(page)
    assert _get_card(api_session, ui_base_url, card)["start_date"] is None


@pytest.mark.ui
def test_empty_title_is_not_saved(logged_in_page, api_session, ui_base_url, column):
    card = _create_card(api_session, ui_base_url, column)
    page = logged_in_page
    _open_card(page, column["board_id"], card)

    page.fill("#edit-card-title", "   ")
    page.locator("#edit-card-description").click()

    assert page.input_value("#edit-card-title") == "Autosave card"
    assert _get_card(api_session, ui_base_url, card)["title"] == "Autosave card"


@pytest.mark.ui
def test_enter_in_description_saves_and_closes(logged_in_page, api_session, ui_base_url, column):
    card = _create_card(api_session, ui_base_url, column)
    page = logged_in_page
    _open_card(page, column["board_id"], card)

    description = page.locator("#edit-card-description")
    description.fill("Line one")
    description.press("Shift+Enter")
    description.type("Line two")
    assert description.input_value() == "Line one\nLine two"

    description.press("Enter")
    _closed(page)
    assert _get_card(api_session, ui_base_url, card)["description"] == "Line one\nLine two"


@pytest.mark.ui
def test_enter_in_title_updates_the_board(logged_in_page, api_session, ui_base_url, column):
    card = _create_card(api_session, ui_base_url, column)
    page = logged_in_page
    _open_card(page, column["board_id"], card)

    page.fill("#edit-card-title", "Renamed with Enter")
    page.locator("#edit-card-title").press("Enter")
    _closed(page)
    page.locator(f'.card[data-card-id="{card["id"]}"] .card-title', has_text="Renamed with Enter").wait_for(
        timeout=5000
    )


@pytest.mark.ui
def test_escape_reverts_then_closes(logged_in_page, api_session, ui_base_url, column):
    card = _create_card(api_session, ui_base_url, column)
    page = logged_in_page
    _open_card(page, column["board_id"], card)

    title = page.locator("#edit-card-title")
    title.fill("Changed my mind")
    title.press("Escape")
    assert title.input_value() == "Autosave card"
    assert page.locator("#edit-card-modal").count() == 1

    title.press("Escape")
    _closed(page)
    assert _get_card(api_session, ui_base_url, card)["title"] == "Autosave card"


@pytest.mark.ui
def test_enter_posts_comment_and_shift_enter_adds_line(logged_in_page, api_session, ui_base_url, column):
    card = _create_card(api_session, ui_base_url, column)
    page = logged_in_page
    _open_card(page, column["board_id"], card)

    comment = page.locator("#new-comment-input")
    comment.fill("First line")
    comment.press("Shift+Enter")
    comment.type("Second line")
    comment.press("Enter")

    page.locator(".comment-text", has_text="Second line").wait_for(timeout=5000)
    assert comment.input_value() == ""
    assert page.locator("#edit-card-modal").count() == 1


@pytest.mark.ui
def test_double_click_edits_checklist_item(logged_in_page, api_session, ui_base_url, column):
    card = _create_card(api_session, ui_base_url, column)
    _add_item(api_session, ui_base_url, card, "Original item")
    page = logged_in_page
    _open_card(page, column["board_id"], card)

    page.locator("#edit-card-modal .checklist-item-name").dblclick()
    item_input = page.locator("#edit-card-modal .checklist-item-input")
    item_input.fill("Edited item")
    item_input.press("Enter")

    _wait_saved(page)
    assert _checklist_names(api_session, ui_base_url, card) == ["Edited item"]
    assert page.locator("#edit-card-modal").count() == 1


@pytest.mark.ui
def test_escape_cancels_checklist_edit_without_closing(logged_in_page, api_session, ui_base_url, column):
    card = _create_card(api_session, ui_base_url, column)
    _add_item(api_session, ui_base_url, card, "Original item")
    page = logged_in_page
    _open_card(page, column["board_id"], card)

    page.locator("#edit-card-modal .checklist-item-name").dblclick()
    item_input = page.locator("#edit-card-modal .checklist-item-input")
    item_input.fill("Abandoned edit")
    item_input.press("Escape")

    assert page.locator("#edit-card-modal .checklist-item-name").inner_text() == "Original item"
    assert page.locator("#edit-card-modal").count() == 1
    assert _checklist_names(api_session, ui_base_url, card) == ["Original item"]


@pytest.mark.ui
def test_checkbox_saves_immediately(logged_in_page, api_session, ui_base_url, column):
    card = _create_card(api_session, ui_base_url, column)
    _add_item(api_session, ui_base_url, card, "Tick me")
    page = logged_in_page
    _open_card(page, column["board_id"], card)

    page.locator("#edit-card-modal .checklist-checkbox").check()
    _wait_saved(page)
    assert _get_card(api_session, ui_base_url, card)["checklist_items"][0]["checked"] is True


@pytest.mark.ui
def test_new_item_saves_and_can_then_be_edited(logged_in_page, api_session, ui_base_url, column):
    card = _create_card(api_session, ui_base_url, column)
    page = logged_in_page
    _open_card(page, column["board_id"], card)

    page.locator("#add-checklist-item-initial-btn").click()
    item_input = page.locator("#edit-card-modal .checklist-item-input").last
    item_input.fill("Brand new")
    page.locator("#edit-card-title").click()
    _wait_saved(page)
    assert _checklist_names(api_session, ui_base_url, card) == ["Brand new"]

    # The new row behaves like any other item without reopening the card
    page.locator("#edit-card-modal .checklist-item-name").dblclick()
    edit_input = page.locator("#edit-card-modal .checklist-item-input")
    edit_input.fill("Renamed new")
    edit_input.press("Enter")
    page.locator("#edit-card-modal .checklist-item-name", has_text="Renamed new").wait_for(timeout=5000)
    assert _checklist_names(api_session, ui_base_url, card) == ["Renamed new"]


@pytest.mark.ui
def test_item_added_at_top_keeps_its_position(logged_in_page, api_session, ui_base_url, column):
    card = _create_card(api_session, ui_base_url, column)
    _add_item(api_session, ui_base_url, card, "Existing")
    page = logged_in_page
    _open_card(page, column["board_id"], card)

    page.locator("#add-checklist-item-top-btn").click()
    page.locator('#edit-card-modal input.checklist-item-input').fill("On top")
    page.locator("#edit-card-title").click()
    _wait_saved(page)
    assert _checklist_names(api_session, ui_base_url, card) == ["On top", "Existing"]


@pytest.mark.ui
def test_dragging_checklist_item_saves_order(logged_in_page, api_session, ui_base_url, column):
    card = _create_card(api_session, ui_base_url, column)
    for name in ("First", "Second", "Third"):
        _add_item(api_session, ui_base_url, card, name)
    page = logged_in_page
    _open_card(page, column["board_id"], card)

    rows = page.locator("#edit-card-modal .checklist-item")
    box = rows.nth(2).bounding_box()
    rows.nth(0).drag_to(rows.nth(2), target_position={"x": 20, "y": box["height"] - 2})

    _wait_saved(page)
    assert _checklist_names(api_session, ui_base_url, card) == ["Second", "Third", "First"]


@pytest.mark.ui
def test_empty_new_item_stays_on_blur(logged_in_page, api_session, ui_base_url, column):
    """An unused new row doesn't vanish and shift the content under the pointer."""
    card = _create_card(api_session, ui_base_url, column)
    _add_item(api_session, ui_base_url, card, "Existing")
    page = logged_in_page
    _open_card(page, column["board_id"], card)

    page.locator("#add-checklist-item-bottom-btn").click()
    empty_input = page.locator("#edit-card-modal input.checklist-item-input")
    bottom_btn = page.locator("#add-checklist-item-bottom-btn")
    position_before = bottom_btn.evaluate("el => el.offsetTop")

    page.locator("#edit-card-title").click()
    page.wait_for_timeout(100)
    assert empty_input.count() == 1
    assert bottom_btn.evaluate("el => el.offsetTop") == position_before

    # Adding again reuses the empty row
    bottom_btn.click()
    assert empty_input.count() == 1

    page.locator("#cancel-edit-card-btn").click()
    _closed(page)
    assert _checklist_names(api_session, ui_base_url, card) == ["Existing"]


@pytest.mark.ui
def test_close_saves_field_still_in_focus(logged_in_page, api_session, ui_base_url, column):
    card = _create_card(api_session, ui_base_url, column)
    page = logged_in_page
    _open_card(page, column["board_id"], card)

    page.fill("#edit-card-title", "Saved by close")
    # The save status appears on blur, so it must not move the button mid-click
    page.locator("#cancel-edit-card-btn").click()
    _closed(page)
    assert _get_card(api_session, ui_base_url, card)["title"] == "Saved by close"


@pytest.mark.ui
def test_failed_save_keeps_the_edit_and_warns(logged_in_page, api_session, ui_base_url, column):
    card = _create_card(api_session, ui_base_url, column)
    page = logged_in_page
    _open_card(page, column["board_id"], card)

    page.context.route(
        f"**/api/cards/{card['id']}",
        lambda route: route.abort() if route.request.method == "PATCH" else route.continue_(),
    )
    page.fill("#edit-card-title", "Will fail")
    page.locator("#edit-card-description").click()

    page.locator("#card-save-status", has_text="Not saved").wait_for(timeout=5000)
    assert page.input_value("#edit-card-title") == "Will fail"


@pytest.mark.ui
def test_enter_adds_lines_on_touch_devices(browser, logged_in_page, api_session, ui_base_url, column):
    """Touch keyboards have no Shift+Enter, so Enter must not close or post."""
    card = _create_card(api_session, ui_base_url, column)
    context = browser.new_context(
        base_url=ui_base_url,
        has_touch=True,
        is_mobile=True,
        viewport={"width": 390, "height": 844},
        storage_state=logged_in_page.context.storage_state(),
        ignore_https_errors=True,
    )
    page = context.new_page()
    try:
        _open_card(page, column["board_id"], card)
        description = page.locator("#edit-card-description")
        description.fill("Line one")
        description.press("Enter")
        description.type("Line two")
        assert description.input_value() == "Line one\nLine two"
        assert page.locator("#edit-card-modal").count() == 1

        comment = page.locator("#new-comment-input")
        comment.fill("Comment one")
        comment.press("Enter")
        assert comment.input_value() == "Comment one\n"
    finally:
        context.close()


@pytest.mark.ui
def test_enter_adds_lines_in_touchscreen_mode(logged_in_page, api_session, ui_base_url, column):
    card = _create_card(api_session, ui_base_url, column)
    page = logged_in_page
    page.goto(f"/board.html?id={column['board_id']}")
    page.locator(f'.card[data-card-id="{card["id"]}"] .card-title').wait_for(timeout=5000)
    page.evaluate("() => document.body.classList.add('touchscreen-mode')")
    page.locator(f'.card[data-card-id="{card["id"]}"] .card-title').click()

    description = page.locator("#edit-card-description")
    description.fill("Line one")
    description.press("Enter")
    assert description.input_value() == "Line one\n"
    assert page.locator("#edit-card-modal").count() == 1


@pytest.mark.ui
def test_read_only_card_without_checklist_closes_with_escape(logged_in_page, api_session, ui_base_url, column):
    card = _create_card(api_session, ui_base_url, column)
    page = logged_in_page
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(f"/board.html?id={column['board_id']}")
    page.wait_for_function("() => window.boardManager?.hasLoadedBoardData && window.header?.dbConnected", timeout=8000)

    page.evaluate(
        """async (id) => {
            window.boardManager.canEdit = false;
            const data = await window.boardManager.getCardData(id);
            window.boardManager.openEditCardModal(id, data);
        }""",
        card["id"],
    )
    page.locator("#edit-card-title").wait_for(state="visible", timeout=5000)
    assert page.locator("#card-save-status").count() == 0

    page.keyboard.press("Escape")
    _closed(page)
    assert errors == []
