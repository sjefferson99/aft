"""UI tests for restoring a backup from the first-time setup page (issue #499).

Setup status and the restore request are stubbed, so these tests don't replace
the test database. server/tests/test_api_authentication.py runs real restores.
"""
import json
import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.ui

RESTORE_ENDPOINT = "**/api/auth/setup/restore"
PROGRESS_ENDPOINT = "**/api/database/restore/progress/*"
BACKUP_FILE = {"name": "backup.sql", "mimeType": "application/sql", "buffer": b"-- backup"}


def _json(route, body, status=200):
    route.fulfill(status=status, content_type="application/json", body=json.dumps(body))


def _open_setup_page(page):
    # context.route, because the service worker can make the requests.
    page.context.route(
        "**/api/auth/setup/status",
        lambda route: _json(route, {"setup_complete": False, "has_users": False}),
    )
    page.context.route(
        PROGRESS_ENDPOINT, lambda route: _json(route, {"success": True, "progress": None})
    )
    page.goto("/setup.html")


def _start_restore(page):
    page.set_input_files("#restoreFile", BACKUP_FILE)
    page.click("#restoreButton")


def test_restore_button_needs_a_file(page):
    _open_setup_page(page)

    expect(page.locator("#restoreButton")).to_be_disabled()
    page.set_input_files("#restoreFile", BACKUP_FILE)
    expect(page.locator("#restoreButton")).to_be_enabled()


def test_running_restore_replaces_the_form_and_sends_a_progress_id(page):
    held_requests = []
    page.context.route(RESTORE_ENDPOINT, lambda route: held_requests.append(route))
    _open_setup_page(page)

    _start_restore(page)

    expect(page.locator("#restoreProgressText")).to_have_text("Uploading the backup file")
    expect(page.locator("#setupForm")).to_be_hidden()
    expect(page.locator("#restoreControls")).to_be_hidden()
    page.wait_for_timeout(100)
    progress_id = held_requests[0].request.headers["x-restore-progress-id"]
    assert re.fullmatch(r"[0-9a-f]{32}", progress_id)


def test_import_progress_is_shown(page):
    page.context.route(RESTORE_ENDPOINT, lambda route: None)
    _open_setup_page(page)
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

    _start_restore(page)

    expect(page.locator("#restoreProgressText")).to_have_text(
        "Restoring table 3 of 34: cards (25%)"
    )
    expect(page.locator("#restoreProgressBar")).to_be_visible()


def test_successful_restore_goes_to_sign_in(page):
    page.context.route(
        RESTORE_ENDPOINT,
        lambda route: _json(route, {"success": True, "message": "Database restored successfully"}),
    )
    _open_setup_page(page)

    _start_restore(page)

    expect(page.locator("#restoreComplete")).to_be_visible()
    expect(page.locator("#restoreProgress")).to_be_hidden()
    page.wait_for_url("**/login.html*")


def test_failed_restore_shows_why_and_brings_the_form_back(page):
    page.context.route(
        RESTORE_ENDPOINT,
        lambda route: _json(
            route, {"success": False, "message": "Schema validation failed"}, status=400
        ),
    )
    _open_setup_page(page)

    _start_restore(page)

    expect(page.locator("#errorMessage")).to_have_text("Schema validation failed")
    expect(page.locator("#restoreProgress")).to_be_hidden()
    expect(page.locator("#setupForm")).to_be_visible()
    expect(page.locator("#restoreButton")).to_be_visible()


def test_lost_connection_says_the_restore_may_still_be_running(page):
    page.context.route(RESTORE_ENDPOINT, lambda route: route.abort())
    _open_setup_page(page)

    _start_restore(page)

    expect(page.locator("#errorMessage")).to_contain_text("may still be running")


def test_oversized_file_is_refused_before_uploading(page):
    restore_requests = []
    page.context.route(RESTORE_ENDPOINT, lambda route: restore_requests.append(route))
    _open_setup_page(page)
    page.evaluate(
        """() => {
            const input = document.getElementById('restoreFile');
            Object.defineProperty(input, 'files', {
                value: [{ name: 'huge.sql', size: 101 * 1024 * 1024 }],
            });
            input.dispatchEvent(new Event('change'));
        }"""
    )

    page.click("#restoreButton")

    expect(page.locator("#errorMessage")).to_contain_text("100MB")
    expect(page.locator("#setupForm")).to_be_visible()
    assert not restore_requests
