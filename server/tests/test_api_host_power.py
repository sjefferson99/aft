"""API tests for restarting or shutting down the host (issue #726).

The routes answer 404 unless the stack has HOST_POWER_CONTROL=true and the
host-control folder mounted, so the enabled and disabled tests each skip on a
stack set up the other way. Nothing acts on the request file in development,
and every test cancels what it asked for, so no real host action happens.
Holding a request while a backup runs is covered by test_host_power.py.
"""

import os
import uuid

import pytest
import requests

API_BASE_URL = os.getenv("PYTEST_API_BASE_URL", "http://localhost")
HOST_URL = f"{API_BASE_URL}/api/system/host"

pytestmark = pytest.mark.api


def _new_user(admin_session, administrator=False):
    session = requests.Session()
    suffix = uuid.uuid4().hex[:8]
    password = f"Host-{uuid.uuid4().hex[:12]}-Aa1!"
    email = f"host-{suffix}@localhost"
    register = session.post(f"{API_BASE_URL}/api/auth/register", json={
        "email": email,
        "username": f"host-{suffix}",
        "password": password,
        "display_name": f"Host User {suffix}",
    })
    assert register.status_code == 201, register.text
    body = register.json()
    user_id = body.get("user", {}).get("id") or body.get("data", {}).get("user", {}).get("id")

    approve = admin_session.post(f"{API_BASE_URL}/api/users/{user_id}/approve")
    assert approve.status_code == 200, approve.text
    if administrator:
        assign = admin_session.post(
            f"{API_BASE_URL}/api/users/{user_id}/roles", json={"role_name": "administrator"}
        )
        assert assign.status_code == 200, assign.text

    login = session.post(f"{API_BASE_URL}/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {"session": session, "id": user_id, "email": email, "password": password}


@pytest.fixture
def admin(test_admin_session):
    """A fresh administrator, so failed passwords don't count against test-admin."""
    user = _new_user(test_admin_session, administrator=True)
    yield user
    user["session"].delete(f"{HOST_URL}/pending")
    # Don't leave an extra administrator for tests that notify all admins.
    test_admin_session.post(f"{API_BASE_URL}/api/users/{user['id']}/deactivate")


@pytest.fixture
def enabled(admin):
    response = admin["session"].get(HOST_URL)
    if response.status_code == 404:
        pytest.skip("Host power control is off on this stack (set HOST_POWER_CONTROL=true)")
    assert response.status_code == 200, response.text
    return admin


def _ask(user, action, password=None):
    body = {"password": user["password"] if password is None else password}
    return user["session"].post(f"{HOST_URL}/{action}", json=body)


class TestAccess:
    def test_unauthenticated_refused(self):
        assert requests.get(HOST_URL).status_code == 401
        assert requests.post(f"{HOST_URL}/reboot", json={}).status_code == 401
        assert requests.delete(f"{HOST_URL}/pending").status_code == 401

    def test_non_admin_refused_whether_enabled_or_not(self, test_admin_session):
        user = _new_user(test_admin_session)
        assert user["session"].get(HOST_URL).status_code == 403
        assert _ask(user, "reboot").status_code == 403
        assert _ask(user, "poweroff").status_code == 403
        assert user["session"].delete(f"{HOST_URL}/pending").status_code == 403

    def test_disabled_is_404(self, admin):
        response = admin["session"].get(HOST_URL)
        if response.status_code == 200:
            pytest.skip("Host power control is on on this stack")
        assert response.status_code == 404
        assert _ask(admin, "reboot").status_code == 404
        assert _ask(admin, "poweroff").status_code == 404
        assert admin["session"].delete(f"{HOST_URL}/pending").status_code == 404

    def test_unknown_action_is_404(self, admin):
        assert _ask(admin, "halt").status_code in (404, 405)


class TestPassword:
    def test_password_required(self, enabled):
        response = enabled["session"].post(f"{HOST_URL}/reboot", json={})
        assert response.status_code == 400
        assert "password" in response.json()["message"].lower()

    def test_wrong_password_is_400_not_401(self, enabled):
        response = _ask(enabled, "reboot", password="not-the-password")
        assert response.status_code == 400
        assert response.json()["message"] == "Current password is incorrect"
        assert enabled["session"].get(HOST_URL).json()["requested"] is None
        # Still signed in.
        assert enabled["session"].get(f"{API_BASE_URL}/api/auth/me").status_code == 200

    def test_wrong_passwords_count_toward_sign_in_limit(self, enabled):
        for _ in range(10):
            assert _ask(enabled, "reboot", password="not-the-password").status_code == 400

        blocked = _ask(enabled, "reboot")
        assert blocked.status_code == 429
        assert "Retry-After" in blocked.headers
        assert enabled["session"].get(HOST_URL).json()["requested"] is None

        # The same budget as signing in.
        login = requests.post(f"{API_BASE_URL}/api/auth/login", json={
            "email": enabled["email"], "password": enabled["password"],
        })
        assert login.status_code == 429


class TestRequest:
    @pytest.mark.parametrize("action", ["reboot", "poweroff"])
    def test_hands_request_to_host(self, enabled, action):
        response = _ask(enabled, action)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["held"] is False
        assert body["requested"] == action
        assert body["pending"] is None

        status = enabled["session"].get(HOST_URL).json()
        assert status["requested"] == action
        assert status["actions"] == ["reboot", "poweroff"]

    def test_second_request_refused_until_cancelled(self, enabled):
        assert _ask(enabled, "reboot").status_code == 200
        assert _ask(enabled, "poweroff").status_code == 409

        cancelled = enabled["session"].delete(f"{HOST_URL}/pending")
        assert cancelled.status_code == 200
        assert cancelled.json()["cancelled"] == "reboot"
        assert cancelled.json()["requested"] is None

        assert _ask(enabled, "poweroff").status_code == 200

    def test_cancel_with_nothing_waiting(self, enabled):
        response = enabled["session"].delete(f"{HOST_URL}/pending")
        assert response.status_code == 200
        assert response.json()["cancelled"] is None

    def test_admins_notified(self, enabled, test_admin_session):
        assert _ask(enabled, "reboot").status_code == 200

        response = test_admin_session.get(f"{API_BASE_URL}/api/notifications")
        assert response.status_code == 200
        subjects = [n["subject"] for n in response.json()["notifications"]]
        assert "Host restart requested" in subjects

    def test_basic_auth_needs_no_extra_password(self, enabled):
        response = requests.post(
            f"{HOST_URL}/reboot", json={}, auth=(enabled["email"], enabled["password"])
        )
        assert response.status_code == 200, response.text
