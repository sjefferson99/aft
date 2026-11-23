"""API tests for the instance Basic auth setting (issue #716).

`GET/PUT /api/settings/basic-auth` chooses whether every account, only
API-only accounts, or no account can use HTTP Basic auth. Every test puts the
setting back to `all`, because other suites rely on Basic auth.
"""

import os
import uuid

import pytest
import requests

API_BASE_URL = os.getenv("PYTEST_API_BASE_URL", "http://localhost")
SETTING_URL = f"{API_BASE_URL}/api/settings/basic-auth"

pytestmark = pytest.mark.api


def _set_mode(admin_session, mode):
    return admin_session.put(SETTING_URL, json={"mode": mode})


@pytest.fixture
def restore_mode(test_admin_session):
    """Put Basic auth back to `all` after the test, whatever happened."""
    yield
    response = _set_mode(test_admin_session, "all")
    assert response.status_code == 200, response.text


def _create_user(admin_session, api_only=False):
    """Register and approve a fresh user, optionally marking it API only."""
    suffix = uuid.uuid4().hex[:8]
    password = f"Basic-{uuid.uuid4().hex[:12]}-Aa1!"
    email = f"basic-{suffix}@localhost"
    register = requests.post(f"{API_BASE_URL}/api/auth/register", json={
        "email": email,
        "username": f"basic-{suffix}",
        "password": password,
        "display_name": f"Basic User {suffix}",
    })
    assert register.status_code == 201, register.text
    body = register.json()
    user_id = body.get("user", {}).get("id") or body.get("data", {}).get("user", {}).get("id")

    approve = admin_session.post(f"{API_BASE_URL}/api/users/{user_id}/approve")
    assert approve.status_code == 200, approve.text
    if api_only:
        flag = admin_session.put(f"{API_BASE_URL}/api/users/{user_id}/api-only", json={"api_only": True})
        assert flag.status_code == 200, flag.text
    return {"id": user_id, "email": email, "password": password}


@pytest.fixture
def person(test_admin_session):
    return _create_user(test_admin_session)


@pytest.fixture
def service_account(test_admin_session):
    return _create_user(test_admin_session, api_only=True)


def _basic_get(user):
    return requests.get(f"{API_BASE_URL}/api/boards", auth=(user["email"], user["password"]))


def _validate(user):
    return requests.post(f"{API_BASE_URL}/api/auth/validate", json={
        "email": user["email"], "password": user["password"],
    })


class TestBasicAuthSettingRoute:

    def test_default_is_all(self, test_admin_session):
        response = test_admin_session.get(SETTING_URL)
        assert response.status_code == 200, response.text
        assert response.json() == {"success": True, "mode": "all"}

    @pytest.mark.parametrize("mode", ["api_only_users", "off", "all"])
    def test_set_and_read_back(self, test_admin_session, restore_mode, mode):
        response = _set_mode(test_admin_session, mode)
        assert response.status_code == 200, response.text
        assert response.json() == {"success": True, "mode": mode}
        assert test_admin_session.get(SETTING_URL).json()["mode"] == mode

    @pytest.mark.parametrize("body", [{}, {"mode": "none"}, {"mode": "ALL"}, {"mode": 1}, {"mode": None}, []])
    def test_invalid_mode_rejected(self, test_admin_session, body):
        response = test_admin_session.put(SETTING_URL, json=body)
        assert response.status_code == 400
        assert test_admin_session.get(SETTING_URL).json()["mode"] == "all"

    def test_requires_login(self):
        assert requests.get(SETTING_URL).status_code == 401
        assert requests.put(SETTING_URL, json={"mode": "off"}).status_code == 401

    def test_non_admin_forbidden(self, person):
        session = requests.Session()
        login = session.post(f"{API_BASE_URL}/api/auth/login", json={
            "email": person["email"], "password": person["password"],
        })
        assert login.status_code == 200, login.text
        assert session.get(SETTING_URL).status_code == 403
        assert session.put(SETTING_URL, json={"mode": "off"}).status_code == 403


class TestBasicAuthModes:

    def test_all_allows_everyone(self, person, service_account):
        assert _basic_get(person).status_code == 200
        assert _basic_get(service_account).status_code == 200

    def test_api_only_users_mode(self, test_admin_session, restore_mode, person, service_account):
        assert _set_mode(test_admin_session, "api_only_users").status_code == 200
        assert _basic_get(person).status_code == 401
        assert _basic_get(service_account).status_code == 200

    def test_off_refuses_everyone(self, test_admin_session, restore_mode, person, service_account):
        assert _set_mode(test_admin_session, "off").status_code == 200
        assert _basic_get(person).status_code == 401
        assert _basic_get(service_account).status_code == 401

    def test_session_sign_in_unaffected(self, test_admin_session, restore_mode, person):
        assert _set_mode(test_admin_session, "off").status_code == 200
        session = requests.Session()
        login = session.post(f"{API_BASE_URL}/api/auth/login", json={
            "email": person["email"], "password": person["password"],
        })
        assert login.status_code == 200, login.text
        assert session.get(f"{API_BASE_URL}/api/boards").status_code == 200

    def test_api_token_unaffected(self, test_admin_session, restore_mode, person):
        session = requests.Session()
        login = session.post(f"{API_BASE_URL}/api/auth/login", json={
            "email": person["email"], "password": person["password"],
        })
        assert login.status_code == 200, login.text
        created = session.post(f"{API_BASE_URL}/api/auth/tokens", json={
            "name": "Script", "password": person["password"],
        })
        assert created.status_code == 201, created.text
        token = created.json()["token"]
        assert _set_mode(test_admin_session, "off").status_code == 200
        response = requests.get(
            f"{API_BASE_URL}/api/boards", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200, response.text

    def test_refused_basic_auth_records_no_failures(self, test_admin_session, restore_mode, person):
        """Refused attempts never check the password, so they can't lock the account out."""
        assert _set_mode(test_admin_session, "off").status_code == 200
        wrong_password = f"Wrong-{uuid.uuid4().hex[:12]}-Aa1!"
        for _ in range(12):
            response = requests.get(f"{API_BASE_URL}/api/boards", auth=(person["email"], wrong_password))
            assert response.status_code == 401
        assert _set_mode(test_admin_session, "all").status_code == 200
        assert _basic_get(person).status_code == 200


class TestValidateFollowsSetting:

    def test_api_only_users_mode(self, test_admin_session, restore_mode, person, service_account):
        assert _validate(person).status_code == 200
        assert _set_mode(test_admin_session, "api_only_users").status_code == 200
        assert _validate(person).status_code == 401
        assert _validate(service_account).status_code == 200

    def test_off(self, test_admin_session, restore_mode, service_account):
        assert _set_mode(test_admin_session, "off").status_code == 200
        assert _validate(service_account).status_code == 401
