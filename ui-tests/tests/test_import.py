"""UI tests for the board import feature (AFT and Trello formats)."""
import json
import uuid

import pytest


def _minimal_trello_payload(board_name):
    return {
        "id": "trello_board_ui_test",
        "name": board_name,
        "desc": "",
        "closed": False,
        "lists": [
            {"id": "list_1", "name": "To Do", "pos": 16384, "closed": False},
        ],
        "cards": [
            {
                "id": "card_1",
                "idList": "list_1",
                "name": "Test Card",
                "desc": "A test card",
                "closed": False,
                "pos": 16384,
                "idLabels": ["lbl_1"],
                "attachments": [
                    {"id": "att_1", "name": "file.pdf", "url": "https://trello.com/download/file.pdf", "isUpload": True},
                ],
                "idChecklists": [],
                "due": None,
                "start": None,
                "dueComplete": False,
            },
        ],
        "checklists": [],
        "labels": [{"id": "lbl_1", "name": "Important", "color": "red"}],
        "labelNames": {},
        "actions": [],
        "members": [],
        "memberships": [],
    }


@pytest.mark.ui
def test_import_modal_shows_trello_options_on_trello_file(logged_in_page, tmp_path, api_session, ui_base_url):
    """Selecting a Trello file reveals the Trello-specific options panel."""
    page = logged_in_page
    page.goto("/index.html")

    board_name = f"UI Trello Test {uuid.uuid4().hex[:8]}"
    trello_file = tmp_path / "trello_board.json"
    trello_file.write_text(json.dumps(_minimal_trello_payload(board_name)), encoding="utf-8")

    page.locator("#add-board-inline-btn, #empty-state-new-board-btn").first.wait_for(state="visible", timeout=5000)

    import_btn = page.locator("button", has_text="Import Board").first
    import_btn.click()

    page.locator("#import-board-modal").wait_for(state="visible", timeout=5000)

    trello_options = page.locator("#import-trello-options")
    assert not trello_options.is_visible(), "Trello options should be hidden before file selection"

    page.set_input_files("#import-board-file", str(trello_file))

    trello_options.wait_for(state="visible", timeout=3000)
    assert page.locator("#import-include-archived-cards").is_visible()
    assert page.locator("#import-include-archived-lists").is_visible()


@pytest.mark.ui
def test_import_modal_shows_warnings_for_labelled_cards(logged_in_page, tmp_path):
    """A Trello file with labelled cards shows a label warning in the modal."""
    page = logged_in_page
    page.goto("/index.html")

    board_name = f"UI Trello Warnings {uuid.uuid4().hex[:8]}"
    trello_file = tmp_path / "trello_labels.json"
    trello_file.write_text(json.dumps(_minimal_trello_payload(board_name)), encoding="utf-8")

    page.locator("#add-board-inline-btn, #empty-state-new-board-btn").first.wait_for(state="visible", timeout=5000)

    import_btn = page.locator("button", has_text="Import Board").first
    import_btn.click()

    page.locator("#import-board-modal").wait_for(state="visible", timeout=5000)
    page.set_input_files("#import-board-file", str(trello_file))

    warnings_panel = page.locator("#import-warnings-panel")
    warnings_panel.wait_for(state="visible", timeout=3000)

    warnings_text = warnings_panel.inner_text()
    assert "label" in warnings_text.lower()
    assert "file attachment" in warnings_text.lower()


@pytest.mark.ui
def test_trello_import_creates_board(logged_in_page, tmp_path, api_session, ui_base_url):
    """Full happy-path: import a Trello file and verify the board appears in the list."""
    page = logged_in_page
    page.goto("/index.html")

    board_name = f"UI Trello Full {uuid.uuid4().hex[:8]}"

    payload = _minimal_trello_payload(board_name)
    # Remove file attachment so it imports cleanly without warnings blocking
    payload["cards"][0]["attachments"] = []

    trello_file = tmp_path / "trello_full.json"
    trello_file.write_text(json.dumps(payload), encoding="utf-8")

    page.locator("#add-board-inline-btn, #empty-state-new-board-btn").first.wait_for(state="visible", timeout=5000)

    import_btn = page.locator("button", has_text="Import Board").first
    import_btn.click()

    page.locator("#import-board-modal").wait_for(state="visible", timeout=5000)
    page.set_input_files("#import-board-file", str(trello_file))

    # Wait for Trello options to appear (confirms format detected)
    page.locator("#import-trello-options").wait_for(state="visible", timeout=3000)

    page.click("#import-submit-btn")

    board_card = page.locator(".board-card", has_text=board_name)
    board_card.wait_for(state="visible", timeout=10000)

    board_id = board_card.get_attribute("data-board-id")
    cleanup = api_session.delete(f"{ui_base_url}/api/boards/{board_id}")
    assert cleanup.status_code in (200, 403, 404)
