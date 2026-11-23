"""API tests for personal API tokens (issue #714).

Tokens are sent as `Authorization: Bearer <token>` and act as their user.
"""

import os
import uuid

import pytest
import requests

API_BASE_URL = os.getenv("PYTEST_API_BASE_URL", "http://localhost")

pytestmark = pytest.mark.api


def _new_user(admin_session, prefix="token"):
    """Register, approve and log in a fresh user. Returns a dict with session and details."""
    session = requests.Session()
    suffix = uuid.uuid4().hex[:8]
    password = f"Token-{uuid.uuid4().hex[:12]}-Aa1!"
    email = f"{prefix}-{suffix}@localhost"

    register = session.post(f"{API_BASE_URL}/api/auth/register", json={
        "email": email,
        "username": f"{prefix}-{suffix}",
        "password": password,
        "display_name": f"Token User {suffix}",
    })
    assert register.status_code == 201, register.text
    body = register.json()
    user_id = body.get("user", {}).get("id") or body.get("data", {}).get("user", {}).get("id")

    approve = admin_session.post(f"{API_BASE_URL}/api/users/{user_id}/approve")
    assert approve.status_code == 200, approve.text

    login = session.post(f"{API_BASE_URL}/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text

    return {"session": session, "id": user_id, "email": email, "password": password}


@pytest.fixture
def token_user(test_admin_session):
    return _new_user(test_admin_session)


def _create(user, **body):
    """Create a token over the user's session, confirming the password."""
    body.setdefault("name", "Script")
    body.setdefault("password", user["password"])
    return user["session"].post(f"{API_BASE_URL}/api/auth/tokens", json=body)


def _create_token(user, **body):
    response = _create(user, **body)
    assert response.status_code == 201, response.text
    return response.json()


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _me(token):
    return requests.get(f"{API_BASE_URL}/api/auth/me", headers=_bearer(token))


def _list(user):
    response = user["session"].get(f"{API_BASE_URL}/api/auth/tokens")
    assert response.status_code == 200, response.text
    return response.json()["tokens"]


class TestCreateOwnToken:
    def test_create_returns_token_once(self, token_user):
        created = _create_token(token_user, name="CI job")
        token = created["token"]
        assert token.startswith("aft_")
        assert len(token) >= 40
        info = created["api_token"]
        assert info["name"] == "CI job"
        assert info["prefix"] == token[:12]
        assert info["read_only"] is False
        assert info["expires_at"] is None
        assert info["last_used_at"] is None
        assert info["expired"] is False

        listed = _list(token_user)
        assert [t["id"] for t in listed] == [info["id"]]
        assert token not in str(listed)
        assert "token_hash" not in listed[0]

    def test_session_needs_current_password(self, token_user):
        response = _create(token_user, password=None)
        assert response.status_code == 400
        assert "password" in response.json()["message"].lower()

        response = _create(token_user, password="wrong-password")
        assert response.status_code == 400
        assert response.json()["message"] == "Current password is incorrect"
        assert _list(token_user) == []

    def test_basic_auth_needs_no_extra_password(self, token_user):
        response = requests.post(
            f"{API_BASE_URL}/api/auth/tokens",
            json={"name": "From basic"},
            auth=(token_user["email"], token_user["password"]),
        )
        assert response.status_code == 201, response.text
        assert _me(response.json()["token"]).json()["user"]["id"] == token_user["id"]

    def test_unauthenticated_refused(self):
        response = requests.post(f"{API_BASE_URL}/api/auth/tokens", json={"name": "x"})
        assert response.status_code == 401

    @pytest.mark.parametrize("body", [
        {"name": ""},
        {"name": "   "},
        {"name": "x" * 101},
        {"name": "bad\nname"},
        {"name": 5},
        {"name": "ok", "read_only": "yes"},
        {"name": "ok", "expires_in_days": 0},
        {"name": "ok", "expires_in_days": 3651},
        {"name": "ok", "expires_in_days": "30"},
        {"name": "ok", "expires_in_days": 1.5},
        {"name": "ok", "expires_in_days": True},
    ])
    def test_invalid_fields_rejected(self, token_user, body):
        body["password"] = token_user["password"]
        response = token_user["session"].post(f"{API_BASE_URL}/api/auth/tokens", json=body)
        assert response.status_code == 400, response.text

    def test_missing_name_rejected(self, token_user):
        response = token_user["session"].post(
            f"{API_BASE_URL}/api/auth/tokens", json={"password": token_user["password"]}
        )
        assert response.status_code == 400

    def test_expiry_is_set(self, token_user):
        info = _create_token(token_user, expires_in_days=30)["api_token"]
        assert info["expires_at"] is not None
        assert info["expires_at"] > info["created_at"]

    def test_limit_per_user(self, token_user):
        auth = (token_user["email"], token_user["password"])
        for i in range(20):
            response = requests.post(
                f"{API_BASE_URL}/api/auth/tokens", json={"name": f"t{i}"}, auth=auth
            )
            assert response.status_code == 201, response.text
        response = requests.post(f"{API_BASE_URL}/api/auth/tokens", json={"name": "one more"}, auth=auth)
        assert response.status_code == 400
        assert "at most 20" in response.json()["message"]


class TestBearerAuth:
    def test_token_acts_as_its_user(self, token_user):
        token = _create_token(token_user)["token"]
        response = _me(token)
        assert response.status_code == 200, response.text
        assert response.json()["user"]["id"] == token_user["id"]

    def test_records_last_used(self, token_user):
        token = _create_token(token_user)["token"]
        assert _me(token).status_code == 200
        assert _list(token_user)[0]["last_used_at"] is not None

    @pytest.mark.parametrize("header", [
        "Bearer aft_notarealtoken",
        "Bearer ",
        "Bearer " + "a" * 200,
        "bearer aft_notarealtoken",
    ])
    def test_bad_token_refused(self, header):
        response = requests.get(f"{API_BASE_URL}/api/auth/me", headers={"Authorization": header})
        assert response.status_code == 401

    def test_bad_token_does_not_fall_back_to_session(self, token_user):
        response = token_user["session"].get(
            f"{API_BASE_URL}/api/auth/me", headers=_bearer("aft_notarealtoken")
        )
        assert response.status_code == 401
        # The session itself is untouched.
        assert token_user["session"].get(f"{API_BASE_URL}/api/auth/me").status_code == 200

    def test_read_write_token_can_change_things(self, token_user):
        token = _create_token(token_user)["token"]
        response = requests.post(
            f"{API_BASE_URL}/api/boards", json={"name": "Made with a token"}, headers=_bearer(token)
        )
        assert response.status_code in (200, 201), response.text
        board_id = response.json()["board"]["id"]
        deleted = requests.delete(f"{API_BASE_URL}/api/boards/{board_id}", headers=_bearer(token))
        assert deleted.status_code == 200, deleted.text

    def test_read_only_token_can_only_read(self, token_user):
        token = _create_token(token_user, read_only=True)["token"]
        assert requests.get(f"{API_BASE_URL}/api/boards", headers=_bearer(token)).status_code == 200
        for method in ("post", "put", "patch", "delete"):
            response = requests.request(
                method, f"{API_BASE_URL}/api/boards", json={"name": "nope"}, headers=_bearer(token)
            )
            assert response.status_code == 403, f"{method}: {response.text}"
            assert response.json()["message"] == "This API token is read-only"

    def test_read_only_token_not_widened_by_session(self, token_user):
        token = _create_token(token_user, read_only=True)["token"]
        response = token_user["session"].post(
            f"{API_BASE_URL}/api/boards", json={"name": "nope"}, headers=_bearer(token)
        )
        assert response.status_code == 403

    def test_token_cannot_create_tokens(self, token_user):
        token = _create_token(token_user)["token"]
        response = requests.post(
            f"{API_BASE_URL}/api/auth/tokens",
            json={"name": "child", "password": token_user["password"]},
            headers=_bearer(token),
        )
        assert response.status_code == 403
        assert len(_list(token_user)) == 1

    def test_token_stops_when_user_deactivated(self, token_user, test_admin_session):
        token = _create_token(token_user)["token"]
        response = test_admin_session.post(f"{API_BASE_URL}/api/users/{token_user['id']}/deactivate")
        assert response.status_code == 200, response.text
        try:
            assert _me(token).status_code == 401
        finally:
            test_admin_session.post(f"{API_BASE_URL}/api/users/{token_user['id']}/activate")
        assert _me(token).status_code == 200

    def test_token_survives_password_change(self, token_user):
        token = _create_token(token_user)["token"]
        new_password = f"Changed-{uuid.uuid4().hex[:12]}-Aa1!"
        response = token_user["session"].post(f"{API_BASE_URL}/api/auth/change-password", json={
            "current_password": token_user["password"],
            "new_password": new_password,
        })
        assert response.status_code == 200, response.text
        assert _me(token).status_code == 200


class TestRevokeOwnToken:
    def test_revoke(self, token_user):
        created = _create_token(token_user)
        token, token_id = created["token"], created["api_token"]["id"]
        response = token_user["session"].delete(f"{API_BASE_URL}/api/auth/tokens/{token_id}")
        assert response.status_code == 200, response.text
        assert _me(token).status_code == 401
        assert _list(token_user) == []

    def test_token_can_revoke_itself(self, token_user):
        created = _create_token(token_user)
        token, token_id = created["token"], created["api_token"]["id"]
        response = requests.delete(f"{API_BASE_URL}/api/auth/tokens/{token_id}", headers=_bearer(token))
        assert response.status_code == 200, response.text
        assert _me(token).status_code == 401

    def test_cannot_revoke_another_users_token(self, token_user, test_admin_session):
        other = _new_user(test_admin_session)
        created = _create_token(other)
        response = token_user["session"].delete(
            f"{API_BASE_URL}/api/auth/tokens/{created['api_token']['id']}"
        )
        assert response.status_code == 404
        assert _me(created["token"]).status_code == 200

    def test_revoke_missing(self, token_user):
        response = token_user["session"].delete(f"{API_BASE_URL}/api/auth/tokens/999999999")
        assert response.status_code == 404


class TestAdminTokens:
    def _set_api_only(self, admin_session, user_id, value=True):
        response = admin_session.put(
            f"{API_BASE_URL}/api/users/{user_id}/api-only", json={"api_only": value}
        )
        assert response.status_code == 200, response.text

    def test_admin_creates_token_for_api_only_account(self, token_user, test_admin_session):
        self._set_api_only(test_admin_session, token_user["id"])
        response = test_admin_session.post(
            f"{API_BASE_URL}/api/users/{token_user['id']}/tokens",
            json={"name": "aft-mcp", "read_only": True, "expires_in_days": 90},
        )
        assert response.status_code == 201, response.text
        created = response.json()
        assert created["api_token"]["read_only"] is True
        # API-only accounts can't hold a session, but their tokens work.
        me = _me(created["token"])
        assert me.status_code == 200, me.text
        assert me.json()["user"]["id"] == token_user["id"]

    def test_admin_cannot_create_for_normal_account(self, token_user, test_admin_session):
        response = test_admin_session.post(
            f"{API_BASE_URL}/api/users/{token_user['id']}/tokens", json={"name": "nope"}
        )
        assert response.status_code == 400
        assert _list(token_user) == []

    def test_admin_create_missing_user(self, test_admin_session):
        response = test_admin_session.post(
            f"{API_BASE_URL}/api/users/999999999/tokens", json={"name": "nope"}
        )
        assert response.status_code == 404

    def test_admin_list_and_revoke(self, token_user, test_admin_session):
        first = _create_token(token_user, name="one")
        second = _create_token(token_user, name="two")

        listed = test_admin_session.get(f"{API_BASE_URL}/api/users/{token_user['id']}/tokens")
        assert listed.status_code == 200, listed.text
        assert [t["name"] for t in listed.json()["tokens"]] == ["two", "one"]

        users = test_admin_session.get(f"{API_BASE_URL}/api/users").json()["users"]
        assert next(u for u in users if u["id"] == token_user["id"])["api_token_count"] == 2

        response = test_admin_session.delete(
            f"{API_BASE_URL}/api/users/{token_user['id']}/tokens/{first['api_token']['id']}"
        )
        assert response.status_code == 200, response.text
        assert _me(first["token"]).status_code == 401
        assert _me(second["token"]).status_code == 200

        response = test_admin_session.delete(f"{API_BASE_URL}/api/users/{token_user['id']}/tokens")
        assert response.status_code == 200, response.text
        assert response.json()["removed"] == 1
        assert _me(second["token"]).status_code == 401

    def test_admin_revoke_wrong_user_is_404(self, token_user, test_admin_session):
        created = _create_token(token_user)
        other = _new_user(test_admin_session)
        response = test_admin_session.delete(
            f"{API_BASE_URL}/api/users/{other['id']}/tokens/{created['api_token']['id']}"
        )
        assert response.status_code == 404
        assert _me(created["token"]).status_code == 200

    def test_admin_token_cannot_create_tokens(self, token_user, test_admin_session):
        """An admin's token can't mint tokens for API-only accounts either."""
        admin = _new_user(test_admin_session, prefix="token-admin")
        assign = test_admin_session.post(
            f"{API_BASE_URL}/api/users/{admin['id']}/roles", json={"role_name": "administrator"}
        )
        assert assign.status_code == 200, assign.text
        try:
            self._set_api_only(test_admin_session, token_user["id"])
            admin_token = _create_token(admin)["token"]
            response = requests.post(
                f"{API_BASE_URL}/api/users/{token_user['id']}/tokens",
                json={"name": "nope"},
                headers=_bearer(admin_token),
            )
            assert response.status_code == 403
            # The token does carry the admin's other permissions.
            listed = requests.get(
                f"{API_BASE_URL}/api/users/{token_user['id']}/tokens", headers=_bearer(admin_token)
            )
            assert listed.status_code == 200
        finally:
            # Don't leave an extra administrator for tests that notify all admins.
            test_admin_session.post(f"{API_BASE_URL}/api/users/{admin['id']}/deactivate")

    def test_user_manage_alone_cannot_create_tokens(self, token_user, test_admin_session):
        """user.manage can make any account API-only, so without the administrator
        role it could otherwise mint a token for an administrator and act as them."""
        manager = _new_user(test_admin_session, prefix="token-manager")
        role_name = f"token_user_manage_{uuid.uuid4().hex[:8]}"
        role = test_admin_session.post(f"{API_BASE_URL}/api/roles", json={
            "name": role_name, "description": "user.manage only", "permissions": ["user.manage"],
        })
        assert role.status_code == 201, role.text
        assign = test_admin_session.post(
            f"{API_BASE_URL}/api/users/{manager['id']}/roles", json={"role_name": role_name}
        )
        assert assign.status_code == 200, assign.text
        victim = _new_user(test_admin_session, prefix="token-victim")
        assign = test_admin_session.post(
            f"{API_BASE_URL}/api/users/{victim['id']}/roles", json={"role_name": "administrator"}
        )
        assert assign.status_code == 200, assign.text
        try:
            response = manager["session"].put(
                f"{API_BASE_URL}/api/users/{victim['id']}/api-only", json={"api_only": True}
            )
            assert response.status_code == 200, response.text
            response = manager["session"].post(
                f"{API_BASE_URL}/api/users/{victim['id']}/tokens", json={"name": "escalate"}
            )
            assert response.status_code == 403
            assert "token" not in response.json()
            # Listing and revoking only need user.manage.
            listed = manager["session"].get(f"{API_BASE_URL}/api/users/{victim['id']}/tokens")
            assert listed.status_code == 200
            assert listed.json()["tokens"] == []
        finally:
            test_admin_session.post(f"{API_BASE_URL}/api/users/{victim['id']}/deactivate")
            test_admin_session.post(f"{API_BASE_URL}/api/users/{manager['id']}/deactivate")

    def test_non_admin_refused(self, token_user, test_admin_session):
        other = _new_user(test_admin_session)
        base = f"{API_BASE_URL}/api/users/{other['id']}/tokens"
        assert token_user["session"].get(base).status_code == 403
        assert token_user["session"].post(base, json={"name": "x"}).status_code == 403
        assert token_user["session"].delete(base).status_code == 403
        assert token_user["session"].delete(f"{base}/1").status_code == 403
