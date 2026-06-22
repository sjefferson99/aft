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
