"""API tests for API-only accounts (issue #715).

An API-only account can use HTTP Basic auth but can't sign in to the web app
or keep a session.
"""

import os
import uuid

import pytest
import requests

API_BASE_URL = os.getenv("PYTEST_API_BASE_URL", "http://localhost")

pytestmark = pytest.mark.api


@pytest.fixture
def service_user(test_admin_session):
    """Create, approve and log in a fresh user. Returns a dict with session and details."""
    session = requests.Session()
    suffix = uuid.uuid4().hex[:8]
    password = f"Service-{uuid.uuid4().hex[:12]}-Aa1!"
    email = f"service-{suffix}@localhost"

    register = session.post(f"{API_BASE_URL}/api/auth/register", json={
        "email": email,
        "username": f"service-{suffix}",
        "password": password,
        "display_name": f"Service User {suffix}",
    })
    assert register.status_code == 201, register.text
    body = register.json()
    user_id = body.get("user", {}).get("id") or body.get("data", {}).get("user", {}).get("id")

    approve = test_admin_session.post(f"{API_BASE_URL}/api/users/{user_id}/approve")
    assert approve.status_code == 200, approve.text

    login = session.post(f"{API_BASE_URL}/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text

    return {"session": session, "id": user_id, "email": email, "password": password}


def _set_api_only(admin_session, user_id, value):
    return admin_session.put(f"{API_BASE_URL}/api/users/{user_id}/api-only", json={"api_only": value})


def _login(user):
    return requests.post(f"{API_BASE_URL}/api/auth/login", json={
        "email": user["email"], "password": user["password"],
    })


def _listed_user(admin_session, user_id):
    response = admin_session.get(f"{API_BASE_URL}/api/users")
    assert response.status_code == 200, response.text
    return next(u for u in response.json()["users"] if u["id"] == user_id)


class TestApiOnlyFlag:
    """Setting and listing the flag."""

    def test_new_user_is_not_api_only(self, service_user, test_admin_session):
        assert _listed_user(test_admin_session, service_user["id"])["api_only"] is False

    def test_set_and_clear(self, service_user, test_admin_session):
        response = _set_api_only(test_admin_session, service_user["id"], True)
        assert response.status_code == 200, response.text
        assert response.json()["user"] == {"id": service_user["id"], "api_only": True}
        assert _listed_user(test_admin_session, service_user["id"])["api_only"] is True

        response = _set_api_only(test_admin_session, service_user["id"], False)
        assert response.status_code == 200, response.text
        assert _listed_user(test_admin_session, service_user["id"])["api_only"] is False

    @pytest.mark.parametrize("body", [{}, {"api_only": "true"}, {"api_only": 1}, {"api_only": None}, []])
    def test_invalid_body_rejected(self, service_user, test_admin_session, body):
        response = test_admin_session.put(
            f"{API_BASE_URL}/api/users/{service_user['id']}/api-only", json=body
        )
        assert response.status_code == 400

    def test_unknown_user(self, test_admin_session):
        assert _set_api_only(test_admin_session, 999999, True).status_code == 404

    def test_cannot_flag_own_account(self, test_admin_session):
        me = test_admin_session.get(f"{API_BASE_URL}/api/auth/me").json()
        user_id = me.get("user", {}).get("id") or me.get("id")
        assert _set_api_only(test_admin_session, user_id, True).status_code == 400

    def test_non_admin_forbidden(self, service_user):
        response = _set_api_only(service_user["session"], service_user["id"], True)
        assert response.status_code == 403

    def test_requires_login(self, service_user):
        response = requests.put(
            f"{API_BASE_URL}/api/users/{service_user['id']}/api-only", json={"api_only": True}
        )
        assert response.status_code == 401


class TestApiOnlySignIn:
    """What an API-only account can and can't do."""

    def test_password_login_refused(self, service_user, test_admin_session):
        assert _set_api_only(test_admin_session, service_user["id"], True).status_code == 200
        response = _login(service_user)
        assert response.status_code == 403
        assert "API" in response.json()["message"]

    def test_wrong_password_still_401(self, service_user, test_admin_session):
        """The API-only answer is only given for the right password."""
        assert _set_api_only(test_admin_session, service_user["id"], True).status_code == 200
        response = requests.post(f"{API_BASE_URL}/api/auth/login", json={
            "email": service_user["email"], "password": "wrong-Password-1!",
        })
        assert response.status_code == 401

    def test_existing_session_ends(self, service_user, test_admin_session):
        session = service_user["session"]
        assert session.get(f"{API_BASE_URL}/api/auth/check").status_code == 200
        assert _set_api_only(test_admin_session, service_user["id"], True).status_code == 200
        assert session.get(f"{API_BASE_URL}/api/auth/check").status_code == 401

    def test_basic_auth_still_works(self, service_user, test_admin_session):
        assert _set_api_only(test_admin_session, service_user["id"], True).status_code == 200
        response = requests.get(
            f"{API_BASE_URL}/api/boards", auth=(service_user["email"], service_user["password"])
        )
        assert response.status_code == 200, response.text

    def test_basic_auth_sets_no_session(self, service_user, test_admin_session):
        assert _set_api_only(test_admin_session, service_user["id"], True).status_code == 200
        session = requests.Session()
        auth = (service_user["email"], service_user["password"])
        assert session.get(f"{API_BASE_URL}/api/boards", auth=auth).status_code == 200
        assert session.get(f"{API_BASE_URL}/api/auth/check").status_code == 401

    def test_cleared_flag_allows_login(self, service_user, test_admin_session):
        assert _set_api_only(test_admin_session, service_user["id"], True).status_code == 200
        assert _set_api_only(test_admin_session, service_user["id"], False).status_code == 200
        assert _login(service_user).status_code == 200
