"""API tests for passkey (WebAuthn) registration, sign-in and management (issue #546).

Passkey ceremony tests need the server started with WEBAUTHN_RP_ID matching the
test host (for http://localhost: WEBAUTHN_RP_ID=localhost and
WEBAUTHN_ORIGINS=http://localhost). They are skipped when passkeys are off.
"""

import os
import uuid
from urllib.parse import urlparse

import pytest
import requests

from tests.soft_authenticator import SoftAuthenticator, b64url

API_BASE_URL = os.getenv("PYTEST_API_BASE_URL", "http://localhost")
ORIGIN = API_BASE_URL.rstrip("/")
RP_ID = urlparse(API_BASE_URL).hostname

pytestmark = pytest.mark.api


def _passkeys_enabled():
    try:
        response = requests.get(f"{API_BASE_URL}/api/auth/passkeys/status", timeout=5)
        return response.status_code == 200 and response.json().get("enabled") is True
    except requests.exceptions.RequestException:
        return False


requires_passkeys = pytest.mark.skipif(
    not _passkeys_enabled(),
    reason="Passkeys not enabled on the test server (set WEBAUTHN_RP_ID=localhost "
           "and WEBAUTHN_ORIGINS=http://localhost in .env)",
)


@pytest.fixture
def passkey_user(test_admin_session):
    """Create, approve and log in a fresh user. Returns a dict with session and details."""
    session = requests.Session()
    suffix = uuid.uuid4().hex[:8]
    password = f"Passkey-{uuid.uuid4().hex[:12]}-Aa1!"
    email = f"passkey-{suffix}@localhost"

    register = session.post(f"{API_BASE_URL}/api/auth/register", json={
        "email": email,
        "username": f"passkey-{suffix}",
        "password": password,
        "display_name": f"Passkey User {suffix}",
    })
    assert register.status_code == 201, register.text
    body = register.json()
    user_id = body.get("user", {}).get("id") or body.get("data", {}).get("user", {}).get("id")

    approve = test_admin_session.post(f"{API_BASE_URL}/api/users/{user_id}/approve")
    assert approve.status_code == 200, approve.text

    login = session.post(f"{API_BASE_URL}/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text

    return {"session": session, "id": user_id, "email": email, "password": password}


def _register_passkey(user, authenticator=None, name="Test passkey"):
    """Register a passkey for the user and return (authenticator, passkey JSON)."""
    authenticator = authenticator or SoftAuthenticator(RP_ID, ORIGIN)
    session = user["session"]
    options = session.post(
        f"{API_BASE_URL}/api/auth/passkeys/register/options", json={"password": user["password"]}
    )
    assert options.status_code == 200, options.text
    credential = authenticator.create(options.json()["options"])
    verify = session.post(
        f"{API_BASE_URL}/api/auth/passkeys/register/verify",
        json={"credential": credential, "name": name},
    )
    assert verify.status_code == 201, verify.text
    return authenticator, verify.json()["passkey"]


def _login_options(session):
    response = session.post(f"{API_BASE_URL}/api/auth/passkeys/login/options")
    assert response.status_code == 200, response.text
    return response.json()["options"]


def _passkey_login(authenticator, **get_kwargs):
    """Sign in with a passkey in a new session. Returns (session, verify response)."""
    session = requests.Session()
    options = _login_options(session)
    credential = authenticator.get(options, **get_kwargs)
    response = session.post(
        f"{API_BASE_URL}/api/auth/passkeys/login/verify", json={"credential": credential}
    )
    return session, response


def _is_logged_in(session):
    return session.get(f"{API_BASE_URL}/api/auth/check").status_code == 200


class TestPasskeyStatus:
    """GET /api/auth/passkeys/status"""

    def test_status_is_public(self):
        response = requests.get(f"{API_BASE_URL}/api/auth/passkeys/status")
        assert response.status_code == 200
        assert isinstance(response.json()["enabled"], bool)


@requires_passkeys
class TestPasskeyRegistration:
    """Adding a passkey to an account."""

    def test_options_require_login(self):
        response = requests.post(
            f"{API_BASE_URL}/api/auth/passkeys/register/options", json={"password": "x"}
        )
        assert response.status_code == 401

    def test_options_require_password(self, passkey_user):
        response = passkey_user["session"].post(
            f"{API_BASE_URL}/api/auth/passkeys/register/options", json={}
        )
        assert response.status_code == 400

    def test_options_reject_wrong_password(self, passkey_user):
        response = passkey_user["session"].post(
            f"{API_BASE_URL}/api/auth/passkeys/register/options",
            json={"password": f"wrong-{uuid.uuid4().hex}"},
        )
        assert response.status_code == 401

    def test_options_require_resident_key_and_user_verification(self, passkey_user):
        response = passkey_user["session"].post(
            f"{API_BASE_URL}/api/auth/passkeys/register/options",
            json={"password": passkey_user["password"]},
        )
        options = response.json()["options"]
        assert options["rp"]["id"] == RP_ID
        assert options["authenticatorSelection"]["residentKey"] == "required"
        assert options["authenticatorSelection"]["userVerification"] == "required"
        assert options["user"]["id"], "user handle must be set"
        assert options["user"]["id"] != str(passkey_user["id"])

    def test_register_and_list(self, passkey_user):
        _, passkey = _register_passkey(passkey_user, name="  Work laptop  ")
        assert passkey["name"] == "Work laptop"
        assert passkey["synced"] is False
        assert passkey["last_used_at"] is None

        listing = passkey_user["session"].get(f"{API_BASE_URL}/api/auth/passkeys")
        assert listing.status_code == 200
        assert [p["id"] for p in listing.json()["passkeys"]] == [passkey["id"]]

    def test_default_name_and_synced_flag(self, passkey_user):
        _, passkey = _register_passkey(
            passkey_user, SoftAuthenticator(RP_ID, ORIGIN, synced=True), name=None
        )
        assert passkey["name"] == "Passkey"
        assert passkey["synced"] is True

    def test_user_handle_is_stable(self, passkey_user):
        first, _ = _register_passkey(passkey_user)
        second, _ = _register_passkey(passkey_user)
        assert first.user_handle == second.user_handle

    def test_existing_passkeys_are_excluded(self, passkey_user):
        authenticator, _ = _register_passkey(passkey_user)
        options = passkey_user["session"].post(
            f"{API_BASE_URL}/api/auth/passkeys/register/options",
            json={"password": passkey_user["password"]},
        ).json()["options"]
        excluded = [c["id"] for c in options["excludeCredentials"]]
        assert excluded == [b64url(authenticator.credential_id)]

    def test_duplicate_credential_rejected(self, passkey_user):
        authenticator, _ = _register_passkey(passkey_user)
        session = passkey_user["session"]
        options = session.post(
            f"{API_BASE_URL}/api/auth/passkeys/register/options",
            json={"password": passkey_user["password"]},
        ).json()["options"]
        response = session.post(
            f"{API_BASE_URL}/api/auth/passkeys/register/verify",
            json={"credential": authenticator.create(options)},
        )
        assert response.status_code == 409

    def test_verify_without_options_rejected(self, passkey_user):
        authenticator = SoftAuthenticator(RP_ID, ORIGIN)
        credential = authenticator.create({"challenge": "AAAA", "user": {"id": "AAAA"}})
        response = passkey_user["session"].post(
            f"{API_BASE_URL}/api/auth/passkeys/register/verify", json={"credential": credential}
        )
        assert response.status_code == 400

    def test_options_are_single_use(self, passkey_user):
        session = passkey_user["session"]
        options = session.post(
            f"{API_BASE_URL}/api/auth/passkeys/register/options",
            json={"password": passkey_user["password"]},
        ).json()["options"]
        credential = SoftAuthenticator(RP_ID, ORIGIN).create(options)
        first = session.post(
            f"{API_BASE_URL}/api/auth/passkeys/register/verify", json={"credential": credential}
        )
        assert first.status_code == 201
        replay = session.post(
            f"{API_BASE_URL}/api/auth/passkeys/register/verify", json={"credential": credential}
        )
        assert replay.status_code == 400

    @pytest.mark.parametrize("tamper", [
        {"user_verified": False},
        {"origin": "https://evil.example"},
        {"rp_id": "evil.example"},
    ])
    def test_invalid_registration_rejected(self, passkey_user, tamper):
        session = passkey_user["session"]
        options = session.post(
            f"{API_BASE_URL}/api/auth/passkeys/register/options",
            json={"password": passkey_user["password"]},
        ).json()["options"]
        credential = SoftAuthenticator(RP_ID, ORIGIN).create(options, **tamper)
        response = session.post(
            f"{API_BASE_URL}/api/auth/passkeys/register/verify", json={"credential": credential}
        )
        assert response.status_code == 400
        assert response.json()["message"] == "Passkey could not be verified"
        assert session.get(f"{API_BASE_URL}/api/auth/passkeys").json()["passkeys"] == []

    @pytest.mark.parametrize("name", ["", "   ", "x" * 101, 123, "bad\x00name"])
    def test_invalid_name_rejected(self, passkey_user, name):
        response = passkey_user["session"].post(
            f"{API_BASE_URL}/api/auth/passkeys/register/verify",
            json={"credential": {}, "name": name},
        )
        assert response.status_code == 400

    @pytest.mark.parametrize("body", [{}, {"credential": "text"}, {"credential": []}])
    def test_missing_credential_rejected(self, passkey_user, body):
        response = passkey_user["session"].post(
            f"{API_BASE_URL}/api/auth/passkeys/register/verify", json=body
        )
        assert response.status_code == 400

    def test_oversized_body_rejected(self, passkey_user):
        response = passkey_user["session"].post(
            f"{API_BASE_URL}/api/auth/passkeys/register/verify",
            json={"credential": {"id": "x" * (70 * 1024)}},
        )
        assert response.status_code == 413


@requires_passkeys
class TestPasskeyLogin:
    """Signing in with a passkey."""

    def test_login_with_passkey(self, passkey_user):
        authenticator, _ = _register_passkey(passkey_user)
        session, response = _passkey_login(authenticator)
        assert response.status_code == 200, response.text
        user = response.json()["user"]
        assert user["id"] == passkey_user["id"]
        assert "permissions" in user and "roles" in user
        assert _is_logged_in(session)

        listing = session.get(f"{API_BASE_URL}/api/auth/passkeys").json()["passkeys"]
        assert listing[0]["last_used_at"] is not None

    def test_login_options_are_usernameless(self):
        options = _login_options(requests.Session())
        assert options["rpId"] == RP_ID
        assert options["userVerification"] == "required"
        assert options.get("allowCredentials", []) == []

    def test_synced_passkey_with_zero_sign_count(self, passkey_user):
        authenticator, _ = _register_passkey(
            passkey_user, SoftAuthenticator(RP_ID, ORIGIN, synced=True)
        )
        for _ in range(2):
            _, response = _passkey_login(authenticator)
            assert response.status_code == 200, response.text

    def test_sign_count_regression_rejected(self, passkey_user):
        authenticator, _ = _register_passkey(passkey_user)
        _, ok = _passkey_login(authenticator, sign_count=5)
        assert ok.status_code == 200
        session, cloned = _passkey_login(authenticator, sign_count=3)
        assert cloned.status_code == 401
        assert not _is_logged_in(session)

    def test_challenge_is_single_use(self, passkey_user):
        authenticator, _ = _register_passkey(passkey_user)
        session = requests.Session()
        credential = authenticator.get(_login_options(session))
        url = f"{API_BASE_URL}/api/auth/passkeys/login/verify"
        assert session.post(url, json={"credential": credential}).status_code == 200
        session.post(f"{API_BASE_URL}/api/auth/logout")
        assert session.post(url, json={"credential": credential}).status_code == 400

    def test_challenge_bound_to_session(self, passkey_user):
        authenticator, _ = _register_passkey(passkey_user)
        credential = authenticator.get(_login_options(requests.Session()))
        response = requests.Session().post(
            f"{API_BASE_URL}/api/auth/passkeys/login/verify", json={"credential": credential}
        )
        assert response.status_code == 400

    @pytest.mark.parametrize("tamper", [
        {"user_verified": False},
        {"origin": "https://evil.example"},
        {"user_handle": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"},
        {"user_handle": ""},
    ])
    def test_invalid_assertion_rejected(self, passkey_user, tamper):
        authenticator, _ = _register_passkey(passkey_user)
        session, response = _passkey_login(authenticator, **tamper)
        assert response.status_code == 401
        assert response.json()["message"] == "Passkey sign-in failed"
        assert not _is_logged_in(session)

    def test_bad_signature_rejected(self, passkey_user):
        authenticator, _ = _register_passkey(passkey_user)
        session = requests.Session()
        credential = authenticator.get(_login_options(session))
        other = SoftAuthenticator(RP_ID, ORIGIN)
        credential["response"]["signature"] = other.get(
            {"challenge": "AAAA"}
        )["response"]["signature"]
        response = session.post(
            f"{API_BASE_URL}/api/auth/passkeys/login/verify", json={"credential": credential}
        )
        assert response.status_code == 401
        assert not _is_logged_in(session)

    def test_unknown_passkey_rejected(self):
        unknown = SoftAuthenticator(RP_ID, ORIGIN)
        unknown.user_handle = "AAAA"
        session, response = _passkey_login(unknown)
        assert response.status_code == 401
        assert not _is_logged_in(session)

    def test_verify_without_options_rejected(self, passkey_user):
        authenticator, _ = _register_passkey(passkey_user)
        credential = authenticator.get({"challenge": "AAAA"})
        response = requests.post(
            f"{API_BASE_URL}/api/auth/passkeys/login/verify", json={"credential": credential}
        )
        assert response.status_code == 400

    def test_malformed_credential_rejected(self):
        session = requests.Session()
        _login_options(session)
        response = session.post(
            f"{API_BASE_URL}/api/auth/passkeys/login/verify",
            json={"credential": {"id": "x", "rawId": 5}},
        )
        assert response.status_code == 401

    def test_deactivated_user_cannot_login(self, passkey_user, test_admin_session):
        authenticator, _ = _register_passkey(passkey_user)
        deactivate = test_admin_session.post(
            f"{API_BASE_URL}/api/users/{passkey_user['id']}/deactivate"
        )
        assert deactivate.status_code == 200
        session, response = _passkey_login(authenticator)
        assert response.status_code == 403
        assert not _is_logged_in(session)

    def test_password_login_still_works(self, passkey_user):
        _register_passkey(passkey_user)
        response = requests.post(f"{API_BASE_URL}/api/auth/login", json={
            "email": passkey_user["email"], "password": passkey_user["password"],
        })
        assert response.status_code == 200


@requires_passkeys
class TestPasskeyManagement:
    """Renaming and removing passkeys."""

    def test_rename(self, passkey_user):
        _, passkey = _register_passkey(passkey_user)
        response = passkey_user["session"].patch(
            f"{API_BASE_URL}/api/auth/passkeys/{passkey['id']}", json={"name": "Phone"}
        )
        assert response.status_code == 200
        assert response.json()["passkey"]["name"] == "Phone"

    @pytest.mark.parametrize("body", [{}, {"name": ""}, {"name": "x" * 101}, {"name": None}])
    def test_rename_invalid(self, passkey_user, body):
        _, passkey = _register_passkey(passkey_user)
        response = passkey_user["session"].patch(
            f"{API_BASE_URL}/api/auth/passkeys/{passkey['id']}", json=body
        )
        assert response.status_code == 400

    def test_cannot_touch_another_users_passkey(self, passkey_user, test_admin_session):
        _, passkey = _register_passkey(passkey_user)
        url = f"{API_BASE_URL}/api/auth/passkeys/{passkey['id']}"
        assert test_admin_session.patch(url, json={"name": "Mine"}).status_code == 404
        assert test_admin_session.delete(url).status_code == 404
        listing = test_admin_session.get(f"{API_BASE_URL}/api/auth/passkeys").json()["passkeys"]
        assert passkey["id"] not in [p["id"] for p in listing]

    def test_management_requires_login(self):
        assert requests.get(f"{API_BASE_URL}/api/auth/passkeys").status_code == 401
        assert requests.delete(f"{API_BASE_URL}/api/auth/passkeys/1").status_code == 401

    def test_delete_ends_sessions_from_that_passkey(self, passkey_user):
        authenticator, passkey = _register_passkey(passkey_user)
        passkey_session, response = _passkey_login(authenticator)
        assert response.status_code == 200

        removed = passkey_user["session"].delete(
            f"{API_BASE_URL}/api/auth/passkeys/{passkey['id']}"
        )
        assert removed.status_code == 200
        assert removed.json()["signed_out"] is False
        assert _is_logged_in(passkey_user["session"]), "password session must survive"
        assert not _is_logged_in(passkey_session)

        _, again = _passkey_login(authenticator)
        assert again.status_code == 401

    def test_delete_current_passkey_signs_out(self, passkey_user):
        authenticator, passkey = _register_passkey(passkey_user)
        session, _ = _passkey_login(authenticator)
        removed = session.delete(f"{API_BASE_URL}/api/auth/passkeys/{passkey['id']}")
        assert removed.status_code == 200
        assert removed.json()["signed_out"] is True
        assert not _is_logged_in(session)


@requires_passkeys
class TestAdminPasskeyRevoke:
    """Admin listing and revoking a user's passkeys."""

    def test_admin_list_and_revoke(self, passkey_user, test_admin_session):
        authenticator, passkey = _register_passkey(passkey_user)
        _register_passkey(passkey_user)
        passkey_session, _ = _passkey_login(authenticator)
        url = f"{API_BASE_URL}/api/users/{passkey_user['id']}/passkeys"

        listing = test_admin_session.get(url)
        assert listing.status_code == 200
        assert passkey["id"] in [p["id"] for p in listing.json()["passkeys"]]

        revoke = test_admin_session.delete(url)
        assert revoke.status_code == 200
        assert revoke.json()["removed"] == 2
        assert test_admin_session.get(url).json()["passkeys"] == []
        assert not _is_logged_in(passkey_session)
        assert _is_logged_in(passkey_user["session"])

    def test_non_admin_forbidden(self, passkey_user):
        url = f"{API_BASE_URL}/api/users/{passkey_user['id']}/passkeys"
        assert passkey_user["session"].get(url).status_code == 403
        assert passkey_user["session"].delete(url).status_code == 403

    def test_unknown_user(self, test_admin_session):
        url = f"{API_BASE_URL}/api/users/99999999/passkeys"
        assert test_admin_session.get(url).status_code == 404
        assert test_admin_session.delete(url).status_code == 404
