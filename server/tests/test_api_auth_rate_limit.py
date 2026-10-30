"""API tests for password guessing limits (issue #597).

These rely on the default per-account limit. The per-IP limits are raised in
compose.yml because the suites share one IP, so they are covered by the unit
tests in test_auth_rate_limit.py.
"""
import uuid

import pytest
import requests

API_BASE_URL = "http://localhost"
ACCOUNT_FAILURE_LIMIT = 10
WRONG_PASSWORD = f"wrong-{uuid.uuid4().hex}"
NEW_PASSWORD = f"new-{uuid.uuid4().hex}"

pytestmark = pytest.mark.api


@pytest.fixture
def approved_user(test_admin_session):
    """Create, approve and log in a fresh user."""
    session = requests.Session()
    suffix = uuid.uuid4().hex[:8]
    password = f"RateLimit-{uuid.uuid4().hex[:12]}-Aa1!"
    email = f"rate-limit-{suffix}@localhost"
    username = f"rate-limit-{suffix}"

    register = session.post(f"{API_BASE_URL}/api/auth/register", json={
        "email": email,
        "username": username,
        "password": password,
    })
    assert register.status_code == 201, register.text
    body = register.json()
    user_id = body.get("user", {}).get("id") or body.get("data", {}).get("user", {}).get("id")

    approve = test_admin_session.post(f"{API_BASE_URL}/api/users/{user_id}/approve")
    assert approve.status_code == 200, approve.text

    login = session.post(f"{API_BASE_URL}/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text

    return {"session": session, "email": email, "username": username, "password": password}


def _login(identifier, password):
    return requests.post(f"{API_BASE_URL}/api/auth/login", json={
        "email": identifier,
        "password": password,
    })


def _fail_logins(identifier, count):
    for _ in range(count):
        response = _login(identifier, WRONG_PASSWORD)
        assert response.status_code == 401, response.text


def _assert_limited(response):
    assert response.status_code == 429, response.text
    assert int(response.headers["Retry-After"]) > 0
    assert "Too many attempts" in response.json()["message"]


class TestLoginLimit:
    """POST /api/auth/login"""

    def test_blocked_after_too_many_failures(self, approved_user):
        _fail_logins(approved_user["email"], ACCOUNT_FAILURE_LIMIT)
        _assert_limited(_login(approved_user["email"], WRONG_PASSWORD))

    def test_correct_password_is_blocked_too(self, approved_user):
        """A block must not reveal whether a guess was right."""
        _fail_logins(approved_user["email"], ACCOUNT_FAILURE_LIMIT)
        _assert_limited(_login(approved_user["email"], approved_user["password"]))

    def test_email_and_username_share_a_budget(self, approved_user):
        _fail_logins(approved_user["email"], ACCOUNT_FAILURE_LIMIT - 1)
        _fail_logins(approved_user["username"], 1)
        _assert_limited(_login(approved_user["email"], approved_user["password"]))

    def test_identifier_case_shares_a_budget(self, approved_user):
        _fail_logins(approved_user["email"].upper(), ACCOUNT_FAILURE_LIMIT)
        _assert_limited(_login(approved_user["email"], approved_user["password"]))

    def test_unknown_account_is_limited_the_same_way(self):
        """Being blocked must not reveal whether an account exists."""
        identifier = f"nobody-{uuid.uuid4().hex}@localhost"
        _fail_logins(identifier, ACCOUNT_FAILURE_LIMIT)
        _assert_limited(_login(identifier, WRONG_PASSWORD))

    def test_successful_login_resets_the_budget(self, approved_user):
        _fail_logins(approved_user["email"], ACCOUNT_FAILURE_LIMIT - 1)
        assert _login(approved_user["email"], approved_user["password"]).status_code == 200
        _fail_logins(approved_user["email"], ACCOUNT_FAILURE_LIMIT)
        _assert_limited(_login(approved_user["email"], approved_user["password"]))

    def test_successful_logins_do_not_use_the_budget(self, approved_user):
        for _ in range(ACCOUNT_FAILURE_LIMIT + 1):
            assert _login(approved_user["email"], approved_user["password"]).status_code == 200

    def test_other_accounts_are_unaffected(self, approved_user):
        _fail_logins(f"nobody-{uuid.uuid4().hex}@localhost", ACCOUNT_FAILURE_LIMIT)
        assert _login(approved_user["email"], approved_user["password"]).status_code == 200

    def test_forwarded_header_does_not_escape_the_limit(self, approved_user):
        _fail_logins(approved_user["email"], ACCOUNT_FAILURE_LIMIT)
        response = requests.post(
            f"{API_BASE_URL}/api/auth/login",
            json={"email": approved_user["email"], "password": approved_user["password"]},
            headers={"X-Forwarded-For": "203.0.113.9", "X-Real-IP": "203.0.113.9"},
        )
        _assert_limited(response)

    def test_existing_session_keeps_working_while_blocked(self, approved_user):
        _fail_logins(approved_user["email"], ACCOUNT_FAILURE_LIMIT)
        assert approved_user["session"].get(f"{API_BASE_URL}/api/auth/check").status_code == 200


class TestOtherPasswordChecks:
    """Every password check shares the account's budget."""

    def test_validate_is_limited(self, approved_user):
        url = f"{API_BASE_URL}/api/auth/validate"
        for _ in range(ACCOUNT_FAILURE_LIMIT):
            response = requests.post(url, json={
                "email": approved_user["email"], "password": WRONG_PASSWORD,
            })
            assert response.status_code == 401
        _assert_limited(requests.post(url, json={
            "email": approved_user["email"], "password": approved_user["password"],
        }))

    def test_basic_auth_failures_are_counted(self, approved_user):
        url = f"{API_BASE_URL}/api/auth/check"
        for _ in range(ACCOUNT_FAILURE_LIMIT):
            response = requests.get(url, auth=(approved_user["email"], WRONG_PASSWORD))
            assert response.status_code == 401
        _assert_limited(_login(approved_user["email"], approved_user["password"]))

    def test_basic_auth_is_rejected_while_blocked(self, approved_user):
        _fail_logins(approved_user["email"], ACCOUNT_FAILURE_LIMIT)
        response = requests.get(
            f"{API_BASE_URL}/api/auth/check",
            auth=(approved_user["email"], approved_user["password"]),
        )
        assert response.status_code == 401

    def test_change_password_is_limited(self, approved_user):
        session = approved_user["session"]
        url = f"{API_BASE_URL}/api/auth/change-password"
        for _ in range(ACCOUNT_FAILURE_LIMIT):
            response = session.post(url, json={
                "current_password": WRONG_PASSWORD, "new_password": NEW_PASSWORD,
            })
            assert response.status_code == 400
        _assert_limited(session.post(url, json={
            "current_password": approved_user["password"], "new_password": NEW_PASSWORD,
        }))
        # A 429, unlike a 401, leaves the user signed in.
        assert session.get(f"{API_BASE_URL}/api/auth/check").status_code == 200
