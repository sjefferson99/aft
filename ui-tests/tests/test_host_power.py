"""UI tests for restarting or shutting down the host from Instance Settings (#726).

The host power routes are mocked, so these pass whether or not the stack has
HOST_POWER_CONTROL on, and nothing is ever asked of a real host.
"""
import json

import pytest

pytestmark = pytest.mark.ui

ENABLED = {
    "success": True,
    "enabled": True,
    "actions": ["reboot", "poweroff"],
    "pending": None,
    "requested": None,
}


def _mock_host_api(page, status=200, body=None, post_responses=None):
    """Mock the host power routes. Returns the list of requests made."""
    calls = []
    post_responses = list(post_responses or [])
    state = {"body": body if body is not None else ENABLED}

    def handle(route):
        request = route.request
        calls.append({"method": request.method, "url": request.url, "body": request.post_data})
        if request.method == "GET":
            if status != 200:
                route.fulfill(status=status, content_type="application/json",
                              body=json.dumps({"success": False, "message": "Not enabled"}))
            else:
                route.fulfill(status=200, content_type="application/json", body=json.dumps(state["body"]))
        elif request.method == "DELETE":
            state["body"] = ENABLED
            route.fulfill(status=200, content_type="application/json", body=json.dumps(
                dict(ENABLED, cancelled="reboot", message="The host restart was cancelled.")
            ))
        else:
            code, response = post_responses.pop(0)
            route.fulfill(status=code, content_type="application/json", body=json.dumps(response))

    page.context.route("**/api/system/host**", handle)
    return calls


def _open_settings(page):
    page.goto("/settings.html#instance")
    page.locator("#security-settings-panel").wait_for(state="visible", timeout=8000)


def test_host_section_hidden_when_not_enabled(logged_in_page):
    page = logged_in_page
    calls = _mock_host_api(page, status=404)
    _open_settings(page)

    page.wait_for_function("() => document.getElementById('basic-auth-mode').value !== ''")
    page.wait_for_timeout(500)
    assert any(call["method"] == "GET" for call in calls)
    assert page.locator("#host-power-panel").is_hidden()


def test_restart_confirmation_modal(logged_in_page):
    page = logged_in_page
    _mock_host_api(page)
    _open_settings(page)

    reboot = page.locator("#host-reboot-btn")
    reboot.wait_for(state="visible", timeout=8000)
    assert "btn-danger" in reboot.get_attribute("class")
    reboot.click()

    modal = page.locator("#host-power-modal")
    modal.wait_for(state="visible")
    assert page.locator("#host-power-modal-title").inner_text() == "Restart host"
    assert "disconnected" in page.locator("#host-power-modal-message").inner_text()
    assert page.evaluate("document.activeElement.id") == "host-power-password"

    page.keyboard.press("Escape")
    modal.wait_for(state="hidden")
    assert page.evaluate("document.activeElement.id") == "host-reboot-btn"

    reboot.click()
    modal.wait_for(state="visible")
    page.locator("#host-power-modal-cancel-btn").click()
    modal.wait_for(state="hidden")


def test_shut_down_warns_and_checks_password(logged_in_page):
    page = logged_in_page
    calls = _mock_host_api(page, post_responses=[
        (400, {"success": False, "message": "Current password is incorrect"}),
        (200, dict(ENABLED, requested="poweroff", held=False,
                   message="The host will shut down now. Everyone will be disconnected.")),
    ])
    _open_settings(page)

    page.locator("#host-poweroff-btn").click()
    modal = page.locator("#host-power-modal")
    modal.wait_for(state="visible")
    assert page.locator("#host-power-modal-title").inner_text() == "Shut down host"
    assert "by hand" in page.locator("#host-power-modal-message").inner_text()

    # An empty password is caught before asking the server.
    page.locator("#host-power-modal-ok-btn").click()
    assert "password" in page.locator("#host-power-modal-error").inner_text().lower()
    assert not any(call["method"] == "POST" for call in calls)

    page.fill("#host-power-password", "wrong")
    page.locator("#host-power-modal-ok-btn").click()
    page.locator("#host-power-modal-error", has_text="incorrect").wait_for()
    assert modal.is_visible()
    # Still on the page: a wrong password must not sign the page out.
    assert "settings.html" in page.url

    page.fill("#host-power-password", "right")
    page.locator("#host-power-modal-ok-btn").click()
    modal.wait_for(state="hidden")
    page.locator("#host-power-status", has_text="shut down now").wait_for()

    posts = [call for call in calls if call["method"] == "POST"]
    assert posts[-1]["url"].endswith("/api/system/host/poweroff")
    assert json.loads(posts[-1]["body"]) == {"password": "right"}
    # The host hasn't acted yet, so the buttons wait.
    assert page.locator("#host-power-pending").is_visible()
    assert page.locator("#host-reboot-btn").is_disabled()


def test_held_request_shown_and_cancelled(logged_in_page):
    page = logged_in_page
    pending = dict(ENABLED, pending={
        "action": "reboot",
        "user_id": 1,
        "username": "test-admin",
        "client_ip": "192.0.2.1",
        "requested_at": "2026-11-25T12:00:00+00:00",
        "expires_at": "2026-11-25T15:00:00+00:00",
        "waiting_for": ["backup"],
    })
    calls = _mock_host_api(page, body=pending)
    _open_settings(page)

    notice = page.locator("#host-power-pending")
    notice.wait_for(state="visible", timeout=8000)
    assert "when a backup finishes" in page.locator("#host-power-pending-text").inner_text()
    assert page.locator("#host-reboot-btn").is_disabled()
    assert page.locator("#host-poweroff-btn").is_disabled()

    page.locator("#host-power-cancel-btn").click()
    notice.wait_for(state="hidden")
    page.locator("#host-power-status", has_text="cancelled").wait_for()
    assert page.locator("#host-reboot-btn").is_enabled()
    assert any(call["method"] == "DELETE" for call in calls)


def test_section_stays_while_host_is_down(logged_in_page):
    """While the host restarts, status checks fail. The section must stay, and
    keep checking, rather than vanish until the page is reloaded."""
    page = logged_in_page
    page.clock.install()
    calls = []
    state = {"status": 200, "body": dict(ENABLED, requested="reboot")}

    def handle(route):
        calls.append(route.request.method)
        route.fulfill(status=state["status"], content_type="application/json",
                      body=json.dumps(state["body"]))

    page.context.route("**/api/system/host**", handle)
    _open_settings(page)
    page.locator("#host-power-pending").wait_for(state="visible", timeout=8000)

    state["status"] = 502
    state["body"] = {"success": False}
    before = len(calls)
    page.clock.run_for(11000)
    page.wait_for_timeout(300)
    assert len(calls) > before
    assert page.locator("#host-power-panel").is_visible()
    assert page.locator("#host-power-pending").is_visible()

    # Back up, and the host has acted on the request.
    state["status"] = 200
    state["body"] = ENABLED
    page.clock.run_for(11000)
    page.locator("#host-power-pending").wait_for(state="hidden")
    assert page.locator("#host-reboot-btn").is_enabled()
