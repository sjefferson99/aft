"""
Tests for authentication API endpoints.

Tests the following endpoints:
- POST /api/auth/setup/admin - First-time admin setup
- GET /api/auth/setup/status - Check if setup is complete
- POST /api/auth/register - User registration
- POST /api/auth/login - User login
- POST /api/auth/logout - User logout
- GET /api/auth/check - Check authentication status
- GET /api/auth/me - Get current user info
- POST /api/auth/change-password - Change password
"""
import pytest
import requests
import time
import os
import hashlib
import re
import threading
import uuid
from pathlib import Path
from flask import Flask
from flask.sessions import SecureCookieSessionInterface

# API base URL - matching conftest.py
API_BASE_URL = "http://localhost"


def _load_secret_key_for_cookie_signing():
    """Load SECRET_KEY from environment or repository .env for session-forgery regression tests."""
    env_secret = os.getenv("SECRET_KEY")
    if env_secret:
        return env_secret

    env_file = Path(__file__).resolve().parents[2] / ".env"
    if not env_file.exists():
        return None

    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip() == "SECRET_KEY":
            return value.strip().strip('"').strip("'")

    return None


def _forge_flask_session_cookie(secret_key, payload):
    """Generate a Flask-compatible signed session cookie value for test validation."""
    app = Flask(__name__)
    app.config["SECRET_KEY"] = secret_key
    serializer = SecureCookieSessionInterface().get_signing_serializer(app)
    return serializer.dumps(payload)


@pytest.fixture
def empty_database(authenticated_session, test_admin_session):
    """Delete all data including users for tests that need truly empty DB.
    
    Note: This fixture is ONLY for authentication tests. It deletes all users
    including the test-admin, then recreates test-admin after the test completes.
    We also need to refresh the session cookies since the old ones are invalid.
    """
    # Delete all data including users using the authenticated admin session.
    response = authenticated_session.delete(f"{API_BASE_URL}/api/database")
    if response.status_code != 200:
        raise AssertionError(
            f"Failed to reset database for auth test: {response.status_code} - {response.text}"
        )
    time.sleep(0.6)
    
    yield
    
    # CRITICAL: Recreate test admin after this test so other tests don't fail
    max_retries = 3
    for attempt in range(max_retries):
        try:
            reset_session = requests.Session()

            # Check if setup is needed
            status = requests.get(f"{API_BASE_URL}/api/auth/setup/status", timeout=5)
            if status.status_code == 200 and status.json().get('setup_complete', False):
                # A test may have created a different first admin (e.g. admin@localhost).
                # Reset back to an empty database so the shared test-admin can be recreated reliably.
                login_candidates = [
                    ("test-admin@localhost", "TestAdmin123!"),
                    ("admin@localhost", "AdminPass123!"),
                ]

                reset_ok = False
                for email, password in login_candidates:
                    login_resp = reset_session.post(
                        f"{API_BASE_URL}/api/auth/login",
                        json={"email": email, "password": password},
                        timeout=5
                    )
                    if login_resp.status_code == 200:
                        delete_resp = reset_session.delete(f"{API_BASE_URL}/api/database", timeout=30)
                        if delete_resp.status_code == 200:
                            time.sleep(0.6)
                            reset_ok = True
                            break

                if not reset_ok:
                    raise Exception("Failed to authenticate as an existing admin to restore empty auth state")

                status = requests.get(f"{API_BASE_URL}/api/auth/setup/status", timeout=5)

            if status.status_code == 200 and not status.json().get('setup_complete', False):
                # Recreate test admin
                resp = requests.post(f"{API_BASE_URL}/api/auth/setup/admin", json={
                    "email": "test-admin@localhost",
                    "username": "test-admin",
                    "password": "TestAdmin123!",
                    "display_name": "Test Admin"
                }, timeout=5)
                
                # Update the shared session with new cookies from the recreated admin
                # The setup endpoint auto-logs in, but we need to ensure cookies are fresh
                if resp.status_code == 201:
                    # Clear old cookies first
                    test_admin_session.cookies.clear()
                    test_admin_session.cookies.update(resp.cookies)
                    
                    # Do an explicit login to ensure session is fully established
                    login_resp = test_admin_session.post(f"{API_BASE_URL}/api/auth/login", json={
                        "email": "test-admin@localhost",
                        "password": "TestAdmin123!"
                    }, timeout=5)
                    
                    if login_resp.status_code == 200:
                        # Clear again and use login cookies
                        test_admin_session.cookies.clear()
                        test_admin_session.cookies.update(login_resp.cookies)
                        time.sleep(0.3)
                        
                        # Verify the session works
                        verify = test_admin_session.get(f"{API_BASE_URL}/api/auth/check")
                        if verify.status_code == 200 and verify.json().get('authenticated'):
                            print(f"[Test Cleanup] Session verified after admin recreation")
                            break  # Success!
                    else:
                        print(f"[Test Cleanup] Session verification failed after admin recreation")
            else:
                raise Exception("Setup remained complete when attempting to recreate test-admin")
        except Exception as e:
            print(f"[Test Cleanup] Attempt {attempt + 1} failed: {e}")
            if attempt == max_retries - 1:
                # Last attempt failed - this is CRITICAL, must fail loudly
                import traceback
                error_msg = f"\nCRITICAL: Failed to recreate test admin after empty_database cleanup!\n{traceback.format_exc()}\nSubsequent tests WILL fail with 401/503 errors."
                print(error_msg)
                # Raise to make this failure visible
                raise Exception(error_msg)
            time.sleep(0.3)  # Wait before retry


class TestSetupFlow:
    """Test first-time setup flow."""
    
    def test_setup_status_no_users(self, empty_database):
        """Setup status should indicate setup needed when no users exist."""
        response = requests.get(f"{API_BASE_URL}/api/auth/setup/status")
        assert response.status_code == 200
        
        data = response.json()
        assert data['setup_complete'] is False
        assert data['has_users'] is False
    
    def test_setup_admin_validation(self, empty_database):
        """Admin setup should validate input."""
        # Missing email
        response = requests.post(f"{API_BASE_URL}/api/auth/setup/admin", json={
            "username": "admin",
            "password": "password123"
        })
        assert response.status_code == 400
        assert 'email' in response.json()['message'].lower()
        
        # Missing username
        response = requests.post(f"{API_BASE_URL}/api/auth/setup/admin", json={
            "email": "admin@localhost",
            "password": "password123"
        })
        assert response.status_code == 400
        assert 'username' in response.json()['message'].lower()
        
        # Missing password
        response = requests.post(f"{API_BASE_URL}/api/auth/setup/admin", json={
            "email": "admin@localhost",
            "username": "admin"
        })
        assert response.status_code == 400
        assert 'password' in response.json()['message'].lower()
        
        # Password too short
        response = requests.post(f"{API_BASE_URL}/api/auth/setup/admin", json={
            "email": "admin@localhost",
            "username": "admin",
            "password": "123"
        })
        assert response.status_code == 400
        assert 'password' in response.json()['message'].lower()
    
    def test_setup_admin_success(self, empty_database):
        """Admin setup should create admin user."""
        response = requests.post(f"{API_BASE_URL}/api/auth/setup/admin", json={
            "email": "admin@localhost",
            "username": "admin",
            "password": "AdminPass123!"
        })
        assert response.status_code == 201
        
        data = response.json()
        assert data['success'] is True
        assert 'user' in data
        assert data['user']['email'] == "admin@localhost"
        assert data['user']['username'] == "admin"
    
    def test_setup_status_with_users(self):
        """Setup status should indicate complete when users exist."""
        response = requests.get(f"{API_BASE_URL}/api/auth/setup/status")
        assert response.status_code == 200
        
        data = response.json()
        assert data['setup_complete'] is True
        assert data['has_users'] is True
    
    def test_setup_admin_already_complete(self):
        """Admin setup should fail when already complete."""
        response = requests.post(f"{API_BASE_URL}/api/auth/setup/admin", json={
            "email": "another@localhost",
            "username": "another",
            "password": "password123"
        })
        assert response.status_code == 403
        assert 'already' in response.json()['message'].lower()


@pytest.fixture
def backup_sql(authenticated_session):
    """A real backup of the database, taken before empty_database clears it."""
    response = authenticated_session.get(f"{API_BASE_URL}/api/database/backup")
    assert response.status_code == 200
    return response.content


def _restore_during_setup(content, headers=None):
    return requests.post(
        f"{API_BASE_URL}/api/auth/setup/restore",
        files={"file": ("backup.sql", content, "application/sql")},
        headers=headers,
    )


class TestSetupRestore:
    """Test restoring a backup from the first-time setup page (issue #499)."""

    def test_refused_once_setup_is_complete(self):
        response = _restore_during_setup(b"-- Alembic Version: abc")

        assert response.status_code == 403
        assert 'already' in response.json()['message'].lower()

    def test_rejects_invalid_file(self, empty_database):
        response = _restore_during_setup(b"not a backup")

        assert response.status_code == 400
        assert requests.get(f"{API_BASE_URL}/api/auth/setup/status").json()['setup_complete'] is False

    def test_rejects_dangerous_sql(self, backup_sql, empty_database):
        response = _restore_during_setup(backup_sql + b"\nGRANT ALL ON *.* TO 'x'@'%';\n")

        assert response.status_code == 400
        assert 'dangerous' in response.json()['message'].lower()

    def test_restores_backup_and_accounts_can_sign_in(self, backup_sql, empty_database):
        progress_id = uuid.uuid4().hex

        response = _restore_during_setup(backup_sql, headers={"X-Restore-Progress-Id": progress_id})

        assert response.status_code == 200
        assert response.json()['success'] is True
        status = requests.get(f"{API_BASE_URL}/api/auth/setup/status").json()
        assert status['setup_complete'] is True
        login = requests.post(f"{API_BASE_URL}/api/auth/login", json={
            "email": "test-admin@localhost",
            "password": "TestAdmin123!",
        })
        assert login.status_code == 200
        progress = requests.get(f"{API_BASE_URL}/api/database/restore/progress/{progress_id}").json()
        assert progress['progress'] is not None

    def test_failed_import_returns_to_setup_without_leaking_errors(self, backup_sql, empty_database):
        """Bad SQL passes validation, then fails after the database was dropped."""
        response = _restore_during_setup(backup_sql + b"\nTHIS IS NOT VALID SQL;\n")

        assert response.status_code == 500
        message = response.json()['message']
        assert 'SQL' not in message and 'syntax' not in message
        status = requests.get(f"{API_BASE_URL}/api/auth/setup/status")
        assert status.status_code == 200
        assert status.json()['setup_complete'] is False

        admin = requests.post(f"{API_BASE_URL}/api/auth/setup/admin", json={
            "email": "admin@localhost",
            "username": "admin",
            "password": "AdminPass123!",
        })
        assert admin.status_code == 201

    def test_second_restore_and_admin_creation_wait_for_a_running_restore(self, backup_sql, empty_database):
        progress_id = uuid.uuid4().hex
        result = {}

        def run_restore():
            result['response'] = _restore_during_setup(
                backup_sql, headers={"X-Restore-Progress-Id": progress_id}
            )

        restore = threading.Thread(target=run_restore)
        restore.start()
        try:
            deadline = time.time() + 30
            while time.time() < deadline:
                progress = requests.get(
                    f"{API_BASE_URL}/api/database/restore/progress/{progress_id}"
                ).json()['progress']
                if progress:
                    break
                time.sleep(0.05)
            assert progress, "the restore never reported progress"

            second = _restore_during_setup(backup_sql)
            admin = requests.post(f"{API_BASE_URL}/api/auth/setup/admin", json={
                "email": "late@localhost",
                "username": "late",
                "password": "LatePass123!",
            })
        finally:
            restore.join()

        assert second.status_code == 409
        assert admin.status_code == 409
        assert result['response'].status_code == 200


class TestRegistration:
    """Test user registration."""
    
    def test_register_validation(self):
        """Registration should validate input."""
        # Missing email
        response = requests.post(f"{API_BASE_URL}/api/auth/register", json={
            "username": "user1",
            "password": "password123"
        })
        assert response.status_code == 400
        assert 'email' in response.json()['message'].lower()
        
        # Missing username
        response = requests.post(f"{API_BASE_URL}/api/auth/register", json={
            "email": "user1@test.com",
            "password": "password123"
        })
        assert response.status_code == 400
        assert 'username' in response.json()['message'].lower()
        
        # Missing password
        response = requests.post(f"{API_BASE_URL}/api/auth/register", json={
            "email": "user1@test.com",
            "username": "user1"
        })
        assert response.status_code == 400
        assert 'password' in response.json()['message'].lower()
    
    def test_register_success(self):
        """User registration should create pending user."""
        response = requests.post(f"{API_BASE_URL}/api/auth/register", json={
            "email": "user1@test.com",
            "username": "testuser",
            "password": "UserPass123!"
        })
        assert response.status_code == 201
        
        data = response.json()
        assert data['success'] is True
        assert 'user' in data
        assert data['user']['email'] == "user1@test.com"
        assert data['user']['username'] == "testuser"
        assert data['user']['requires_approval'] is True  # Pending approval
    
    def test_register_duplicate_email(self):
        """Registration should prevent duplicate emails."""
        response = requests.post(f"{API_BASE_URL}/api/auth/register", json={
            "email": "user1@test.com",  # Already registered
            "username": "different",
            "password": "password123"
        })
        assert response.status_code == 409
        assert 'email' in response.json()['message'].lower()
    
    def test_register_duplicate_username(self):
        """Registration should prevent duplicate usernames."""
        response = requests.post(f"{API_BASE_URL}/api/auth/register", json={
            "email": "different@test.com",
            "username": "testuser",  # Already taken
            "password": "password123"
        })
        assert response.status_code == 409
        assert 'username' in response.json()['message'].lower()


class TestLogin:
    """Test user login."""
    
    @pytest.fixture
    def session(self):
        """Create a session for maintaining cookies."""
        return requests.Session()
    
    def test_login_not_approved(self, session):
        """Login should fail for unapproved users."""
        response = session.post(f"{API_BASE_URL}/api/auth/login", json={
            "email": "user1@test.com",
            "password": "UserPass123!"
        })
        assert response.status_code == 403
        assert 'approved' in response.json()['message'].lower()

    @pytest.mark.security
    @pytest.mark.api
    def test_forged_session_cookie_for_pending_user_is_rejected(self):
        """Critical #1 regression: forged cookie for pending user must not authenticate."""
        secret_key = _load_secret_key_for_cookie_signing()
        if not secret_key:
            pytest.skip("SECRET_KEY not available to build signed regression cookie")

        register_response = None
        email = None

        # Retry with high-entropy identities to avoid rare collisions in parallel runs.
        for _ in range(3):
            unique = time.time_ns()
            email = f"pending-{unique}@test.local"
            username = f"pending-{unique}"

            register_response = requests.post(f"{API_BASE_URL}/api/auth/register", json={
                "email": email,
                "username": username,
                "password": "PendingPass123!"
            })

            if register_response.status_code == 201:
                break

        assert register_response is not None
        assert register_response.status_code == 201, register_response.text

        user_data = register_response.json()["user"]
        user_id = user_data["id"]
        email_hash = hashlib.sha256(email.encode()).hexdigest()[:16]

        forged_cookie = _forge_flask_session_cookie(secret_key, {
            "user_id": user_id,
            "user_email_hash": email_hash,
        })

        forged_session = requests.Session()
        forged_session.cookies.set("session", forged_cookie)

        check_response = forged_session.get(f"{API_BASE_URL}/api/auth/check")
        assert check_response.status_code == 401

        body = check_response.json()
        assert body.get("authenticated") is False
    
    def test_login_invalid_credentials(self, session):
        """Login should fail with wrong password."""
        response = session.post(f"{API_BASE_URL}/api/auth/login", json={
            "email": "test-admin@localhost",
            "password": "WrongPassword"
        })
        assert response.status_code == 401
        assert 'invalid' in response.json()['message'].lower()
    
    def test_login_success(self, session):
        """Login should succeed with correct credentials."""
        response = session.post(f"{API_BASE_URL}/api/auth/login", json={
            "email": "test-admin@localhost",
            "password": "TestAdmin123!"
        })
        assert response.status_code == 200
        
        data = response.json()
        assert data['success'] is True
        assert 'user' in data
        assert data['user']['email'] == "test-admin@localhost"
        
        # Check session cookie was set
        assert 'session' in session.cookies
    
    def test_check_authenticated(self, session):
        """Auth check should return True when logged in."""
        # Login first
        session.post(f"{API_BASE_URL}/api/auth/login", json={
            "email": "test-admin@localhost",
            "password": "TestAdmin123!"
        })
        
        # Check auth status
        response = session.get(f"{API_BASE_URL}/api/auth/check")
        assert response.status_code == 200
        
        data = response.json()
        assert data['authenticated'] is True
    
    def test_me_endpoint(self, session):
        """Me endpoint should return current user info."""
        # Login first
        session.post(f"{API_BASE_URL}/api/auth/login", json={
            "email": "test-admin@localhost",
            "password": "TestAdmin123!"
        })
        
        # Get user info
        response = session.get(f"{API_BASE_URL}/api/auth/me")
        assert response.status_code == 200
        
        data = response.json()
        assert data['success'] is True
        assert 'user' in data
        assert data['user']['email'] == "test-admin@localhost"
        assert 'roles' in data['user']
        assert 'profile_colour' in data['user']
        assert re.fullmatch(r'^#[0-9A-Fa-f]{6}$', data['user']['profile_colour'])
    
    def test_logout(self, session):
        """Logout should clear session."""
        # Login first
        session.post(f"{API_BASE_URL}/api/auth/login", json={
            "email": "test-admin@localhost",
            "password": "TestAdmin123!"
        })
        
        # Logout
        response = session.post(f"{API_BASE_URL}/api/auth/logout")
        assert response.status_code == 200
        assert response.json()['success'] is True
        
        # Check auth status after logout
        response = session.get(f"{API_BASE_URL}/api/auth/check")
        data = response.json()
        assert data['authenticated'] is False


class TestPasswordChange:
    """Test password change functionality."""
    
    @pytest.fixture
    def authenticated_session(self):
        """Create an authenticated session."""
        session = requests.Session()
        session.post(f"{API_BASE_URL}/api/auth/login", json={
            "email": "test-admin@localhost",
            "password": "TestAdmin123!"
        })
        return session
    
    def test_change_password_unauthenticated(self):
        """Password change should require authentication."""
        session = requests.Session()
        response = session.post(f"{API_BASE_URL}/api/auth/change-password", json={
            "current_password": "TestAdmin123!",
            "new_password": "NewPass456!"
        })
        assert response.status_code == 401
    
    def test_change_password_wrong_current(self, authenticated_session):
        """Password change should fail with wrong current password."""
        response = authenticated_session.post(f"{API_BASE_URL}/api/auth/change-password", json={
            "current_password": "WrongPassword",
            "new_password": "NewPass456!"
        })
        # 400, not 401: the session is still valid, and a 401 makes the UI redirect to login.
        assert response.status_code == 400
        assert 'current password' in response.json()['message'].lower()
    
    def test_change_password_validation(self, authenticated_session):
        """Password change should validate new password."""
        # Too short
        response = authenticated_session.post(f"{API_BASE_URL}/api/auth/change-password", json={
            "current_password": "TestAdmin123!",
            "new_password": "123"
        })
        assert response.status_code == 400
    
    def test_change_password_success(self, authenticated_session):
        """Password change should work with valid input."""
        response = authenticated_session.post(f"{API_BASE_URL}/api/auth/change-password", json={
            "current_password": "TestAdmin123!",
            "new_password": "NewAdminPass456!"
        })
        assert response.status_code == 200
        assert response.json()['success'] is True
        
        # Verify old password no longer works
        new_session = requests.Session()
        response = new_session.post(f"{API_BASE_URL}/api/auth/login", json={
            "email": "test-admin@localhost",
            "password": "TestAdmin123!"
        })
        assert response.status_code == 401
        
        # Verify new password works
        response = new_session.post(f"{API_BASE_URL}/api/auth/login", json={
            "email": "test-admin@localhost",
            "password": "NewAdminPass456!"
        })
        assert response.status_code == 200

        # Restore canonical test-admin password so tests remain independent.
        reset_response = new_session.post(f"{API_BASE_URL}/api/auth/change-password", json={
            "current_password": "NewAdminPass456!",
            "new_password": "TestAdmin123!"
        })
        assert reset_response.status_code == 200

    def test_admin_can_reset_another_users_password(self, authenticated_session):
        """Administrators can reset another user's password through the shared endpoint."""
        suffix = uuid.uuid4().hex[:8]
        target_email = f"pwdreset_{suffix}@test.com"
        target_username = f"pwdreset_{suffix}"
        original_password = "OriginalPass123!"
        reset_password = "ResetPass456!"

        register_response = requests.post(f"{API_BASE_URL}/api/auth/register", json={
            "email": target_email,
            "username": target_username,
            "password": original_password
        })
        assert register_response.status_code == 201

        pending_response = authenticated_session.get(f"{API_BASE_URL}/api/users/pending")
        assert pending_response.status_code == 200
        target_user = next(
            (u for u in pending_response.json()['users'] if u['email'] == target_email),
            None
        )
        assert target_user is not None

        approve_response = authenticated_session.post(f"{API_BASE_URL}/api/users/{target_user['id']}/approve")
        assert approve_response.status_code == 200

        target_session = requests.Session()
        target_login_response = target_session.post(f"{API_BASE_URL}/api/auth/login", json={
            "email": target_email,
            "password": original_password
        })
        assert target_login_response.status_code == 200

        target_check_before_reset = target_session.get(f"{API_BASE_URL}/api/auth/check")
        assert target_check_before_reset.status_code == 200
        assert target_check_before_reset.json().get('authenticated') is True

        reset_response = authenticated_session.post(f"{API_BASE_URL}/api/auth/change-password", json={
            "user_id": target_user['id'],
            "new_password": reset_password
        })
        assert reset_response.status_code == 200
        assert reset_response.json()['success'] is True

        target_check_after_reset = target_session.get(f"{API_BASE_URL}/api/auth/check")
        assert target_check_after_reset.status_code == 401
        assert target_check_after_reset.json().get('authenticated') is False

        old_login_session = requests.Session()
        old_login_response = old_login_session.post(f"{API_BASE_URL}/api/auth/login", json={
            "email": target_email,
            "password": original_password
        })
        assert old_login_response.status_code == 401

        new_login_session = requests.Session()
        new_login_response = new_login_session.post(f"{API_BASE_URL}/api/auth/login", json={
            "email": target_email,
            "password": reset_password
        })
        assert new_login_response.status_code == 200

    def test_non_admin_with_user_manage_cannot_reset_another_users_password(self, authenticated_session):
        """Users with user.manage but without administrator role cannot reset other users' passwords."""
        manager_suffix = uuid.uuid4().hex[:8]
        manager_email = f"manager_{manager_suffix}@test.com"
        manager_username = f"manager_{manager_suffix}"
        manager_password = "ManagerPass123!"

        target_suffix = uuid.uuid4().hex[:8]
        target_email = f"target_{target_suffix}@test.com"
        target_username = f"target_{target_suffix}"
        target_password = "TargetPass123!"

        create_manager_response = requests.post(f"{API_BASE_URL}/api/auth/register", json={
            "email": manager_email,
            "username": manager_username,
            "password": manager_password
        })
        assert create_manager_response.status_code == 201

        create_target_response = requests.post(f"{API_BASE_URL}/api/auth/register", json={
            "email": target_email,
            "username": target_username,
            "password": target_password
        })
        assert create_target_response.status_code == 201

        pending_response = authenticated_session.get(f"{API_BASE_URL}/api/users/pending")
        assert pending_response.status_code == 200
        pending_users = pending_response.json()['users']

        manager_user = next((u for u in pending_users if u['email'] == manager_email), None)
        target_user = next((u for u in pending_users if u['email'] == target_email), None)
        assert manager_user is not None
        assert target_user is not None

        assert authenticated_session.post(f"{API_BASE_URL}/api/users/{manager_user['id']}/approve").status_code == 200
        assert authenticated_session.post(f"{API_BASE_URL}/api/users/{target_user['id']}/approve").status_code == 200

        role_name = f"manage_only_{uuid.uuid4().hex[:8]}"
        create_role_response = authenticated_session.post(
            f"{API_BASE_URL}/api/roles",
            json={
                "name": role_name,
                "description": "Can manage users but is not an administrator",
                "permissions": ["user.manage"]
            }
        )
        assert create_role_response.status_code == 201

        role_response = authenticated_session.post(
            f"{API_BASE_URL}/api/users/{manager_user['id']}/roles",
            json={"role_name": role_name}
        )
        assert role_response.status_code == 200

        manager_session = requests.Session()
        manager_login = manager_session.post(f"{API_BASE_URL}/api/auth/login", json={
            "email": manager_email,
            "password": manager_password
        })
        assert manager_login.status_code == 200

        forbidden_reset = manager_session.post(f"{API_BASE_URL}/api/auth/change-password", json={
            "user_id": target_user['id'],
            "new_password": "ShouldNotWork123!"
        })
        assert forbidden_reset.status_code == 403


class TestAuthenticationFlow:
    """Test complete authentication flow."""
    
    def test_full_user_journey(self):
        """Test complete user lifecycle."""
        session = requests.Session()
        
        # 1. Check not authenticated
        response = session.get(f"{API_BASE_URL}/api/auth/check")
        assert response.json()['authenticated'] is False
        
        # 2. Register new user
        response = session.post(f"{API_BASE_URL}/api/auth/register", json={
            "email": "journey@test.com",
            "username": "journeyuser",
            "password": "JourneyPass123!"
        })
        assert response.status_code == 201
        
        # 3. Try to login (should fail - not approved)
        response = session.post(f"{API_BASE_URL}/api/auth/login", json={
            "email": "journey@test.com",
            "password": "JourneyPass123!"
        })
        assert response.status_code == 403
        
        # 4. Admin approves user (this will be tested in user_management tests)
        # For now, just verify the flow stops at approval requirement
        
        # 5. Login with admin to test their flow
        admin_session = requests.Session()
        response = admin_session.post(f"{API_BASE_URL}/api/auth/login", json={
            "email": "test-admin@localhost",
            "password": "TestAdmin123!"
        })
        assert response.status_code == 200
        
        # 6. Get admin info
        response = admin_session.get(f"{API_BASE_URL}/api/auth/me")
        assert response.status_code == 200
        assert 'administrator' in [r['name'] for r in response.json()['user']['roles']]
        
        # 7. Logout
        response = admin_session.post(f"{API_BASE_URL}/api/auth/logout")
        assert response.status_code == 200
        
        # 8. Verify logged out
        response = admin_session.get(f"{API_BASE_URL}/api/auth/check")
        assert response.json()['authenticated'] is False


class TestProfileColourAPI:
    """Test profile colour update endpoint."""

    def test_update_profile_colour_requires_authentication(self):
        """Profile colour update should require an authenticated user."""
        response = requests.put(
            f"{API_BASE_URL}/api/users/me/profile-colour",
            json={"profile_colour": "#112233"}
        )
        assert response.status_code == 401
        data = response.json()
        assert data['success'] is False

    def test_update_profile_colour_rejects_invalid_hex(self, authenticated_session):
        """Profile colour endpoint should reject non-hex colour values."""
        response = authenticated_session.put(
            f"{API_BASE_URL}/api/users/me/profile-colour",
            json={"profile_colour": "112233"}
        )
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False

    def test_update_profile_colour_success(self, authenticated_session):
        """Profile colour endpoint should update and persist valid RGB hex values."""
        response = authenticated_session.put(
            f"{API_BASE_URL}/api/users/me/profile-colour",
            json={"profile_colour": "#112233"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['profile_colour'] == '#112233'

        me_response = authenticated_session.get(f"{API_BASE_URL}/api/auth/me")
        assert me_response.status_code == 200
        me_data = me_response.json()
        assert me_data['success'] is True
        assert me_data['user']['profile_colour'] == '#112233'
