"""UI tests for the restore progress display (issue #590).

Every restore request is stubbed, so these tests don't replace the test database.
"""
import json
import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.ui

BACKUP_FILENAME = "aft_backup_20260101_120000.sql"
RESTORE_ENDPOINT = f"**/api/database/backups/restore/{BACKUP_FILENAME}"
PROGRESS_ENDPOINT = "**/api/database/restore/progress/*"


def _json(route, body, status=200):
    route.fulfill(status=status, content_type="application/json", body=json.dumps(body))


def _open_restore_page(page):
    # context.route, because the service worker can make the requests.
    page.context.route(
        "**/api/database/backups/list",
        lambda route: _json(
            route,
            {
                "success": True,
                "backups": [
                    {
                        "filename": BACKUP_FILENAME,
                        "created": "2026-01-01T12:00:00",
                        "size": 1024,
                        "is_manual": True,
                    }
                ],
            },
        ),
    )
    page.goto("/backup-restore.html")


def _start_restore(page):
    page.click(".backup-restore-btn")
    page.click("#restoreModalConfirmBtn")


def test_restore_shows_spinner_until_progress_arrives(logged_in_page):
    page = logged_in_page
    page.context.route(RESTORE_ENDPOINT, lambda route: None)
    page.context.route(
        PROGRESS_ENDPOINT, lambda route: _json(route, {"success": True, "progress": None})
    )
    _open_restore_page(page)

    _start_restore(page)

    expect(page.locator("#restoreProgress .spinner")).to_be_visible()
    expect(page.locator("#restoreProgressText")).to_have_text("Starting the restore")
    expect(page.locator("#restoreProgressBar")).to_be_hidden()


def test_step_without_measurable_progress_shows_no_bar(logged_in_page):
    page = logged_in_page
    page.context.route(RESTORE_ENDPOINT, lambda route: None)
    page.context.route(
        PROGRESS_ENDPOINT,
        lambda route: _json(
            route, {"success": True, "progress": {"message": "Clearing the existing database"}}
        ),
    )
    _open_restore_page(page)

    _start_restore(page)

    expect(page.locator("#restoreProgressText")).to_have_text("Clearing the existing database")
    expect(page.locator("#restoreProgressBar")).to_be_hidden()


def test_import_shows_table_and_real_percentage(logged_in_page):
    page = logged_in_page
    page.context.route(RESTORE_ENDPOINT, lambda route: None)
    page.context.route(
        PROGRESS_ENDPOINT,
        lambda route: _json(
            route,
            {
                "success": True,
                "progress": {
                    "message": "Restoring table 3 of 34: cards",
                    "bytes_done": 250,
                    "bytes_total": 1000,
                },
            },
        ),
    )
    _open_restore_page(page)

    _start_restore(page)

    expect(page.locator("#restoreProgressText")).to_have_text(
        "Restoring table 3 of 34: cards (25%)"
    )
    bar = page.locator("#restoreProgressBar")
    expect(bar).to_be_visible()
    expect(bar).to_have_js_property("value", 25)


def test_escape_does_not_hide_a_running_restore(logged_in_page):
    page = logged_in_page
    page.context.route(RESTORE_ENDPOINT, lambda route: None)
    page.context.route(
        PROGRESS_ENDPOINT, lambda route: _json(route, {"success": True, "progress": None})
    )
    _open_restore_page(page)

    _start_restore(page)
    expect(page.locator("#restoreProgress")).to_be_visible()
    page.keyboard.press("Escape")

    expect(page.locator("#restoreModal")).to_have_class(re.compile(r"\bactive\b"))
    expect(page.locator("#restoreProgress")).to_be_visible()


def test_failed_restore_clears_progress_and_stops_polling(logged_in_page):
    page = logged_in_page
    polls = []

    def handle_progress(route):
        polls.append(route.request.url)
        _json(route, {"success": True, "progress": {"message": "Checking the backup file"}})

    page.context.route(PROGRESS_ENDPOINT, handle_progress)
    held_requests = []
    page.context.route(RESTORE_ENDPOINT, lambda route: held_requests.append(route))
    _open_restore_page(page)

    _start_restore(page)
    expect(page.locator("#restoreProgressText")).to_have_text("Checking the backup file")
    assert held_requests
    _json(held_requests[0], {"success": False, "message": "Schema validation failed"}, status=400)

    expect(page.locator("#restoreModalTitle")).to_have_text("Restore Failed")
    expect(page.locator("#restoreModalMessage")).to_have_text("Schema validation failed")
    expect(page.locator("#restoreProgress")).to_be_hidden()

    polls_at_finish = len(polls)
    page.wait_for_timeout(1500)
    assert len(polls) == polls_at_finish


def test_upload_restore_starts_at_uploading_and_sends_a_progress_id(logged_in_page):
    page = logged_in_page
    held_requests = []
    page.context.route("**/api/database/restore", lambda route: held_requests.append(route))
    page.context.route(
        PROGRESS_ENDPOINT, lambda route: _json(route, {"success": True, "progress": None})
    )
    _open_restore_page(page)
    expect(page.locator(".backup-restore-btn")).to_be_visible()

    page.set_input_files(
        "#restore-file-input",
        {"name": "backup.sql", "mimeType": "application/sql", "buffer": b"-- backup"},
    )
    page.click("#restoreModalConfirmBtn")

    expect(page.locator("#restoreProgressText")).to_have_text("Uploading the backup file")
    page.wait_for_timeout(100)
    progress_id = held_requests[0].request.headers["x-restore-progress-id"]
    assert re.fullmatch(r"[0-9a-f]{32}", progress_id)
