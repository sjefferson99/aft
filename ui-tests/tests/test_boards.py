"""UI tests for creating and deleting boards from the boards list page."""
import uuid

import pytest


@pytest.mark.ui
def test_create_board_appears_in_list(logged_in_page, api_session, ui_base_url):
    """Creating a board through the UI modal adds it to the boards grid."""
    page = logged_in_page
    board_name = f"UI Test Board {uuid.uuid4().hex[:8]}"

    page.goto("/index.html")
    # Either the empty-state button or the inline "+ New Board" button is
    # present depending on whether any boards already exist.
    page.locator("#empty-state-new-board-btn, #add-board-inline-btn").click()
    page.fill("#board-name", board_name)
    page.click("#new-board-form button[type='submit']")

    board_card = page.locator(".board-card", has_text=board_name)
    board_card.wait_for(state="visible", timeout=5000)

    # Clean up via the API rather than the UI, so this test only exercises
    # (and only fails on) board creation.
    board_id = board_card.get_attribute("data-board-id")
    cleanup_response = api_session.delete(f"{ui_base_url}/api/boards/{board_id}")
    assert cleanup_response.status_code == 200, (
        f"Failed to clean up test board {board_id}: "
        f"{cleanup_response.status_code} {cleanup_response.text}"
    )


@pytest.mark.ui
def test_delete_board_removes_it_from_list(logged_in_page, board):
    """Deleting a board through its card and confirming removes it from the grid."""
    page = logged_in_page
    page.goto("/index.html")

    board_card = page.locator(f'.board-card[data-board-id="{board["id"]}"]')
    board_card.wait_for(state="visible", timeout=5000)

    board_card.locator(".board-delete-btn").click()
    page.click("#appModalConfirmBtn")

    board_card.wait_for(state="detached", timeout=5000)
