"""
Tests for user management API endpoints (admin only).

Tests the following endpoints:
- GET /api/users - List all users
- GET /api/users/pending - List pending approval users
- POST /api/users/:id/approve - Approve a user
- POST /api/users/:id/reject - Reject a user
- POST /api/users/:id/activate - Activate a user
- POST /api/users/:id/deactivate - Deactivate a user
- POST /api/users/:id/roles/:role_id - Assign role to user
- DELETE /api/users/:id/roles/:role_id - Remove role from user
"""
import os

import pytest
import requests
import time
import uuid

# API base URL - matching conftest.py
API_BASE_URL = os.getenv("PYTEST_API_BASE_URL", "http://localhost")
ADMIN_EMAIL = "test-admin@localhost"
ADMIN_PASSWORD = "TestAdmin123!"


def wait_for_setup_status(timeout_seconds=10):
    """Wait until the setup status endpoint responds successfully."""
    deadline = time.time() + timeout_seconds
    last_response = None

    while time.time() < deadline:
        try:
            response = requests.get(f"{API_BASE_URL}/api/auth/setup/status", timeout=5)
            last_response = response
            if response.status_code == 200:
                return response
        except requests.exceptions.RequestException:
            last_response = None

        time.sleep(0.2)

    if last_response is not None:
        return last_response

    raise AssertionError("Setup status endpoint did not become ready in time")


def ensure_test_admin_session(admin_session, timeout_seconds=10):
    """Create or log in the known test admin after a database reset."""
    deadline = time.time() + timeout_seconds
    last_response = None

    while time.time() < deadline:
        status_response = wait_for_setup_status(timeout_seconds=5)
        assert status_response.status_code == 200, status_response.text

        if not status_response.json().get("setup_complete", False):
            last_response = admin_session.post(
                f"{API_BASE_URL}/api/auth/setup/admin",
                json={
                    "email": ADMIN_EMAIL,
                    "username": "test-admin",
                    "password": ADMIN_PASSWORD,
                    "display_name": "Test Admin"
                },
                timeout=5,
            )
            if last_response.status_code in (200, 201):
                return admin_session
        else:
            last_response = admin_session.post(
                f"{API_BASE_URL}/api/auth/login",
                json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                timeout=5,
            )
            if last_response.status_code == 200:
                return admin_session

        time.sleep(0.2)

    response_text = last_response.text if last_response is not None else "No response"
    response_code = last_response.status_code if last_response is not None else "n/a"
    raise AssertionError(
        f"Failed to initialize test admin session: HTTP {response_code} - {response_text}"
    )


def register_pending_test_users(expected_count=3, timeout_seconds=10):
    """Register the default pending users used by this test module."""
    for i in range(expected_count):
        response = requests.post(
            f"{API_BASE_URL}/api/auth/register",
            json={
                "email": f"user{i}@test.com",
                "username": f"user{i}",
                "password": f"UserPass{i}123!"
            },
            timeout=5,
        )
        assert response.status_code == 201, f"Failed to register user{i}: {response.status_code} - {response.text}"

    # Wait for users to appear in pending list
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        admin_session = requests.Session()
        ensure_test_admin_session(admin_session, timeout_seconds=5)
        pending_response = admin_session.get(f"{API_BASE_URL}/api/users/pending", timeout=5)
        if pending_response.status_code == 200:
            pending_users = pending_response.json().get('users', [])
            default_users = [user for user in pending_users if user['email'].startswith('user')]
            if len(default_users) >= expected_count:
                return
        time.sleep(0.2)

    raise AssertionError("Pending test users did not become available in time")


@pytest.fixture
def empty_database(authenticated_session, test_admin_session):
    """Reset to an empty DB for tests that delete the known admin user.

    Skips the conftest autouse cleanup (conftest checks for this fixture name).
    Recreates the test admin and refreshes the session-level cookies on teardown.
    """
    response = authenticated_session.delete(f"{API_BASE_URL}/api/database")
    if response.status_code != 200:
        raise AssertionError(
            f"Failed to reset database before test: {response.status_code} - {response.text}"
        )
    wait_for_setup_status()

    yield

    # Teardown: ensure test admin exists so subsequent conftest usage works.
    max_retries = 3
    for attempt in range(max_retries):
        try:
            status = requests.get(f"{API_BASE_URL}/api/auth/setup/status", timeout=5)
            if status.status_code == 200 and not status.json().get("setup_complete", False):
                resp = requests.post(
                    f"{API_BASE_URL}/api/auth/setup/admin",
                    json={
                        "email": "test-admin@localhost",
                        "username": "test-admin",
                        "password": "TestAdmin123!",
                        "display_name": "Test Admin",
                    },
                    timeout=5,
                )
                if resp.status_code == 201:
                    test_admin_session.cookies.clear()
                    login_resp = test_admin_session.post(
                        f"{API_BASE_URL}/api/auth/login",
                        json={"email": "test-admin@localhost", "password": "TestAdmin123!"},
                        timeout=5,
                    )
                    if login_resp.status_code == 200:
                        test_admin_session.cookies.clear()
                        test_admin_session.cookies.update(login_resp.cookies)
                        time.sleep(0.3)
                        verify = test_admin_session.get(
                            f"{API_BASE_URL}/api/auth/check", timeout=5
                        )
                        if verify.status_code == 200 and verify.json().get("authenticated"):
                            break
            elif status.status_code == 200 and status.json().get("setup_complete", False):
                login_resp = test_admin_session.post(
                    f"{API_BASE_URL}/api/auth/login",
                    json={"email": "test-admin@localhost", "password": "TestAdmin123!"},
                    timeout=5,
                )
                if login_resp.status_code == 200:
                    test_admin_session.cookies.clear()
                    test_admin_session.cookies.update(login_resp.cookies)
                    break
        except Exception:
            if attempt == max_retries - 1:
                raise
        time.sleep(0.3)


@pytest.fixture
def setup_test_environment(authenticated_session):
    """Setup test environment with admin and test users."""
    reset_response = authenticated_session.delete(f"{API_BASE_URL}/api/database")
    assert reset_response.status_code == 200, reset_response.text

    admin_session = requests.Session()
    ensure_test_admin_session(admin_session)

    register_pending_test_users()
    return admin_session


@pytest.fixture
def admin_session(setup_test_environment):
    """Create an authenticated admin session."""
    return setup_test_environment


@pytest.fixture
def regular_session(setup_test_environment):
    """Create a session for a non-admin user (will need approval first)."""
    # This fixture creates the session but user won't be able to access admin endpoints
    session = requests.Session()
    return session


class TestUserListing:
    """Test user listing endpoints."""
    
    def test_list_users_unauthenticated(self, setup_test_environment):
        """List users should require authentication."""
        response = requests.get(f"{API_BASE_URL}/api/users")
        assert response.status_code == 401
    
    def test_list_users_as_admin(self, admin_session, setup_test_environment):
        """Admin should be able to list all users."""
        response = admin_session.get(f"{API_BASE_URL}/api/users")
        assert response.status_code == 200
        
        data = response.json()
        assert data['success'] is True
        assert 'users' in data
        assert len(data['users']) >= 4  # Admin + 3 registered users
        
        # Check user data structure
        user = data['users'][0]
        assert 'id' in user
        assert 'email' in user
        assert 'username' in user
        assert 'is_active' in user
        assert 'is_approved' in user
        assert 'roles' in user
    
    def test_list_pending_users(self, admin_session, setup_test_environment):
        """Admin should be able to list pending users."""
        response = admin_session.get(f"{API_BASE_URL}/api/users/pending")
        assert response.status_code == 200
        
        data = response.json()
        assert data['success'] is True
        assert 'users' in data
        assert len(data['users']) == 3  # 3 pending users
        
        # All should be unapproved
        for user in data['users']:
            assert user['is_approved'] is False


class TestUserApproval:
    """Test user approval/rejection."""
    
    def test_approve_user_unauthenticated(self, setup_test_environment):
        """Approval should require authentication."""
        response = requests.post(f"{API_BASE_URL}/api/users/999/approve")
        assert response.status_code == 401
    
    def test_approve_nonexistent_user(self, admin_session):
        """Approving nonexistent user should fail."""
        response = admin_session.post(f"{API_BASE_URL}/api/users/99999/approve")
        assert response.status_code == 404
    
    def test_approve_user_success(self, admin_session, setup_test_environment):
        """Admin should be able to approve pending users."""
        # Get pending users
        response = admin_session.get(f"{API_BASE_URL}/api/users/pending")
        pending_users = response.json()['users']
        assert len(pending_users) > 0
        
        user_id = pending_users[0]['id']
        user_email = pending_users[0]['email']
        
        # Approve user
        response = admin_session.post(f"{API_BASE_URL}/api/users/{user_id}/approve")
        assert response.status_code == 200
        
        data = response.json()
        assert data['success'] is True
        assert data['user']['is_approved'] is True
        
        # Verify user can now login
        user_session = requests.Session()
        # Extract password from user email (user0@test.com -> UserPass0123!)
        user_num = user_email.split('@')[0].replace('user', '')
        response = user_session.post(f"{API_BASE_URL}/api/auth/login", json={
            "email": user_email,
            "password": f"UserPass{user_num}123!"
        })
        assert response.status_code == 200

        me_response = user_session.get(f"{API_BASE_URL}/api/auth/me")
        assert me_response.status_code == 200
        role_names = [role["name"] for role in me_response.json()["user"]["roles"]]
        assert 'board_creator' in role_names
    
    def test_reject_user_success(self, admin_session, setup_test_environment):
        """Admin should be able to reject pending users."""
        # Get pending users
        response = admin_session.get(f"{API_BASE_URL}/api/users/pending")
        pending_users = response.json()['users']
        
        if len(pending_users) > 0:
            user_id = pending_users[0]['id']
            
            # Reject user
            response = admin_session.post(f"{API_BASE_URL}/api/users/{user_id}/reject")
            assert response.status_code == 200
            assert response.json()['success'] is True
            
            # Verify user no longer in pending list
            response = admin_session.get(f"{API_BASE_URL}/api/users/pending")
            remaining = response.json()['users']
            assert user_id not in [u['id'] for u in remaining]


class TestUserActivation:
    """Test user activation/deactivation."""
    
    def test_deactivate_user(self, admin_session, setup_test_environment):
        """Admin should be able to deactivate users."""
        # Get an approved user
        response = admin_session.get(f"{API_BASE_URL}/api/users/pending")
        pending = response.json()['users']
        
        if len(pending) > 0:
            # Approve one first
            user_id = pending[0]['id']
            admin_session.post(f"{API_BASE_URL}/api/users/{user_id}/approve")
            
            # Deactivate
            response = admin_session.post(f"{API_BASE_URL}/api/users/{user_id}/deactivate")
            assert response.status_code == 200
            
            data = response.json()
            assert data['success'] is True
            assert data['user']['is_active'] is False
    
    def test_activate_user(self, admin_session, setup_test_environment):
        """Admin should be able to reactivate users."""
        # Get users and find a deactivated one
        response = admin_session.get(f"{API_BASE_URL}/api/users")
        users = response.json()['users']
        
        deactivated = [u for u in users if not u['is_active']]
        if len(deactivated) > 0:
            user_id = deactivated[0]['id']
            
            # Activate
            response = admin_session.post(f"{API_BASE_URL}/api/users/{user_id}/activate")
            assert response.status_code == 200
            
            data = response.json()
            assert data['success'] is True
            assert data['user']['is_active'] is True
    
    def test_login_deactivated_user(self, admin_session, setup_test_environment):
        """Deactivated users should not be able to login."""
        # Approve a user
        response = admin_session.get(f"{API_BASE_URL}/api/users/pending")
        pending = response.json()['users']
        
        if len(pending) > 0:
            user_id = pending[0]['id']
            user_email = pending[0]['email']
            user_num = user_email.split('@')[0].replace('user', '')
            password = f"UserPass{user_num}123!"
            
            # Approve user
            admin_session.post(f"{API_BASE_URL}/api/users/{user_id}/approve")
            
            # Verify can login
            user_session = requests.Session()
            response = user_session.post(f"{API_BASE_URL}/api/auth/login", json={
                "email": user_email,
                "password": password
            })
            assert response.status_code == 200
            
            # Deactivate user
            admin_session.post(f"{API_BASE_URL}/api/users/{user_id}/deactivate")
            
            # Try to login again (should fail)
            user_session2 = requests.Session()
            response = user_session2.post(f"{API_BASE_URL}/api/auth/login", json={
                "email": user_email,
                "password": password
            })
            assert response.status_code == 403


class TestRoleManagement:
    """Test role assignment and removal."""
    
    def test_assign_role_to_user(self, admin_session, setup_test_environment):
        """Admin should be able to assign roles to users."""
        # Get a user
        response = admin_session.get(f"{API_BASE_URL}/api/users")
        users = response.json()['users']
        
        # Find non-admin user
        regular_user = [u for u in users if 'administrator' not in [r['name'] for r in u['roles']]]
        if len(regular_user) > 0:
            user_id = regular_user[0]['id']

            response = admin_session.post(
                f"{API_BASE_URL}/api/users/{user_id}/roles",
                json={"role_name": "board_creator"}
            )
            assert response.status_code == 200

            response = admin_session.get(f"{API_BASE_URL}/api/users")
            assert response.status_code == 200
            updated_user = next(u for u in response.json()['users'] if u['id'] == user_id)
            assert 'board_creator' in [r['name'] for r in updated_user['roles']]
    
    def test_remove_role_from_user(self, admin_session, setup_test_environment):
        """Admin should be able to remove roles from users."""
        roles_response = admin_session.get(f"{API_BASE_URL}/api/roles")
        assert roles_response.status_code == 200
        board_creator_role = next(r for r in roles_response.json()['roles'] if r['name'] == 'board_creator')

        # Get a user and assign a removable role first
        response = admin_session.get(f"{API_BASE_URL}/api/users")
        users = response.json()['users']
        
        # Find non-admin user
        for user in users:
            if 'administrator' not in [r['name'] for r in user['roles']]:
                user_id = user['id']
                admin_session.post(
                    f"{API_BASE_URL}/api/users/{user_id}/roles",
                    json={"role_name": "board_creator"}
                )

                response = admin_session.delete(
                    f"{API_BASE_URL}/api/users/{user_id}/roles/{board_creator_role['id']}"
                )
                assert response.status_code == 200

                response = admin_session.get(f"{API_BASE_URL}/api/users")
                assert response.status_code == 200
                updated_user = next(u for u in response.json()['users'] if u['id'] == user_id)
                assert 'board_creator' not in [r['name'] for r in updated_user['roles']]
                break
    
    def test_assign_role_invalid_user(self, admin_session):
        """Assigning role to nonexistent user should fail."""
        response = admin_session.post(
            f"{API_BASE_URL}/api/users/99999/roles",
            json={"role_name": "board_creator"}
        )
        assert response.status_code == 404
    
    def test_assign_invalid_role(self, admin_session, setup_test_environment):
        """Assigning nonexistent role should fail."""
        response = admin_session.get(f"{API_BASE_URL}/api/users")
        users = response.json()['users']
        
        if len(users) > 0:
            user_id = users[0]['id']
            response = admin_session.post(
                f"{API_BASE_URL}/api/users/{user_id}/roles",
                json={"role_name": "not_a_real_role"}
            )
            assert response.status_code == 404

    def test_create_custom_role(self, admin_session):
        """Admin should be able to create a custom role."""
        response = admin_session.post(
            f"{API_BASE_URL}/api/roles",
            json={
                "name": "test_custom_role",
                "description": "A test custom role",
                "permissions": ["board.view", "board.create"]
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data['success'] is True
        assert data['role']['name'] == 'test_custom_role'
        assert len(data['role']['permissions']) == 2

    def test_create_role_duplicate_name(self, admin_session):
        """Creating a role with duplicate name should fail."""
        # Try to create a role with the same name as a system role
        response = admin_session.post(
            f"{API_BASE_URL}/api/roles",
            json={
                "name": "administrator",
                "description": "Duplicate role",
                "permissions": ["board.view"]
            }
        )
        assert response.status_code == 409

    def test_copy_role(self, admin_session):
        """Admin should be able to copy a role."""
        # First get list of roles
        response = admin_session.get(f"{API_BASE_URL}/api/roles")
        roles = response.json()['roles']
        
        if len(roles) > 0:
            source_role_id = roles[0]['id']
            
            response = admin_session.post(
                f"{API_BASE_URL}/api/roles/{source_role_id}/copy",
                json={"name": "copied_test_role"}
            )
            assert response.status_code == 201
            data = response.json()
            assert data['success'] is True
            assert data['role']['name'] == 'copied_test_role'

    def test_update_role_permissions(self, admin_session):
        """Admin should be able to update a custom role's permissions."""
        # First create a role
        response = admin_session.post(
            f"{API_BASE_URL}/api/roles",
            json={
                "name": "test_update_role",
                "description": "Test role for updating",
                "permissions": ["board.view"]
            }
        )
        assert response.status_code == 201
        role_id = response.json()['role']['id']
        
        # Now update it
        response = admin_session.patch(
            f"{API_BASE_URL}/api/roles/{role_id}",
            json={
                "name": "test_update_role_renamed",
                "permissions": ["board.view", "board.create", "board.edit"]
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['role']['name'] == 'test_update_role_renamed'
        assert len(data['role']['permissions']) == 3

    def test_update_system_role_fails(self, admin_session):
        """Updating a system role should fail."""
        # Get list of roles and find a system role
        response = admin_session.get(f"{API_BASE_URL}/api/roles")
        roles = response.json()['roles']
        
        system_role = next((r for r in roles if r['is_system_role']), None)
        if system_role:
            response = admin_session.patch(
                f"{API_BASE_URL}/api/roles/{system_role['id']}",
                json={"permissions": ["board.view"]}
            )
            assert response.status_code == 400

    def test_delete_custom_role(self, admin_session):
        """Admin should be able to delete a custom role."""
        # First create a role
        response = admin_session.post(
            f"{API_BASE_URL}/api/roles",
            json={
                "name": "test_delete_role",
                "description": "Test role for deletion",
                "permissions": ["board.view"]
            }
        )
        assert response.status_code == 201
        role_id = response.json()['role']['id']
        
        # Now delete it
        response = admin_session.delete(f"{API_BASE_URL}/api/roles/{role_id}")
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True

    def test_delete_system_role_fails(self, admin_session):
        """Deleting a system role should fail."""
        # Get list of roles and find a system role
        response = admin_session.get(f"{API_BASE_URL}/api/roles")
        roles = response.json()['roles']
        
        system_role = next((r for r in roles if r['is_system_role']), None)
        if system_role:
            response = admin_session.delete(f"{API_BASE_URL}/api/roles/{system_role['id']}")
            assert response.status_code == 400


class TestAdminPermissions:
    """Test that only admins can access user management."""
    
    def test_non_admin_cannot_list_users(self, setup_test_environment):
        """Non-admin users should not be able to list users."""
        # First approve a user
        admin_session = requests.Session()
        admin_session.post(f"{API_BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        
        response = admin_session.get(f"{API_BASE_URL}/api/users/pending")
        pending = response.json()['users']
        
        if len(pending) > 0:
            user_id = pending[0]['id']
            user_email = pending[0]['email']
            user_num = user_email.split('@')[0].replace('user', '')
            password = f"UserPass{user_num}123!"
            
            # Approve and assign a non-admin global role
            admin_session.post(f"{API_BASE_URL}/api/users/{user_id}/approve")
            admin_session.post(
                f"{API_BASE_URL}/api/users/{user_id}/roles",
                json={"role_name": "board_creator"}
            )
            
            # Login as regular user
            user_session = requests.Session()
            user_session.post(f"{API_BASE_URL}/api/auth/login", json={
                "email": user_email,
                "password": password
            })
            
            # Try to list users (should fail)
            response = user_session.get(f"{API_BASE_URL}/api/users")
            assert response.status_code == 403  # Forbidden
    
    def test_non_admin_cannot_approve_users(self, setup_test_environment):  # noqa: F811
        """Non-admin users should not be able to approve other users."""
        # Setup admin and regular user (reuse previous test pattern)
        admin_session = requests.Session()
        admin_session.post(f"{API_BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        
        response = admin_session.get(f"{API_BASE_URL}/api/users/pending")
        pending = response.json()['users']
        
        if len(pending) >= 2:
            # Approve first user as non-admin
            user1_id = pending[0]['id']
            user1_email = pending[0]['email']
            user1_num = user1_email.split('@')[0].replace('user', '')
            
            admin_session.post(f"{API_BASE_URL}/api/users/{user1_id}/approve")
            
            # Login as that user
            user_session = requests.Session()
            user_session.post(f"{API_BASE_URL}/api/auth/login", json={
                "email": user1_email,
                "password": f"UserPass{user1_num}123!"
            })
            
            # Try to approve another user (should fail)
            user2_id = pending[1]['id']
            response = user_session.post(f"{API_BASE_URL}/api/users/{user2_id}/approve")
            assert response.status_code == 403


class TestKnownTestUserEndpoints:
    """Test status and cleanup behavior for the known test user guidance endpoints."""

    def test_known_test_user_status_requires_authentication(self, authenticated_session):
        """GET /api/admin/test-user must reject unauthenticated callers."""
        response = requests.get(f"{API_BASE_URL}/api/admin/test-user")
        assert response.status_code == 401

    def test_user_role_can_view_known_test_user_status(self, authenticated_session):
        """Users that hold only user.role can read status but cannot remove."""
        role_name = f"test_viewer_{uuid.uuid4().hex[:8]}"
        role_response = authenticated_session.post(
            f"{API_BASE_URL}/api/roles",
            json={
                "name": role_name,
                "description": "Role for known test user status checks",
                "permissions": ["user.role"]
            }
        )
        assert role_response.status_code == 201, role_response.text

        # Register a unique user so we are never blocked by existing pending state.
        suffix = uuid.uuid4().hex[:8]
        user_email = f"viewer_{suffix}@test.com"
        user_password = "ViewerPass123!"
        requests.post(f"{API_BASE_URL}/api/auth/register", json={
            "email": user_email,
            "username": f"viewer_{suffix}",
            "password": user_password
        })

        pending_response = authenticated_session.get(f"{API_BASE_URL}/api/users/pending")
        assert pending_response.status_code == 200
        pending_users = pending_response.json()['users']
        target_user = next((u for u in pending_users if u['email'] == user_email), None)
        assert target_user is not None, "Registered user not found in pending list"
        user_id = target_user['id']

        assert authenticated_session.post(f"{API_BASE_URL}/api/users/{user_id}/approve").status_code == 200
        assert authenticated_session.post(
            f"{API_BASE_URL}/api/users/{user_id}/roles",
            json={"role_name": role_name}
        ).status_code == 200

        user_session = requests.Session()
        login_response = user_session.post(
            f"{API_BASE_URL}/api/auth/login",
            json={"email": user_email, "password": user_password}
        )
        assert login_response.status_code == 200, login_response.text

        status_response = user_session.get(f"{API_BASE_URL}/api/admin/test-user")
        assert status_response.status_code == 200, status_response.text

        data = status_response.json()
        assert data['success'] is True
        assert data['test_user_present'] is True   # conftest admin is test-admin@localhost
        assert data['test_user_compatible'] is True
        assert data['clean_database_compatible'] is True
        assert data['expected_user']['email'] == ADMIN_EMAIL
        assert data['expected_user']['username'] == 'test-admin'
        assert data['permissions']['can_remove'] is False

    def test_user_role_cannot_remove_known_test_user(self, authenticated_session):
        """DELETE /api/admin/test-user must be forbidden for user.role-only users."""
        role_name = f"test_roleonly_{uuid.uuid4().hex[:8]}"
        role_response = authenticated_session.post(
            f"{API_BASE_URL}/api/roles",
            json={
                "name": role_name,
                "description": "Role for delete-denied check",
                "permissions": ["user.role"]
            }
        )
        assert role_response.status_code == 201, role_response.text

        suffix = uuid.uuid4().hex[:8]
        user_email = f"deldenied_{suffix}@test.com"
        user_password = "DeniedPass123!"
        requests.post(f"{API_BASE_URL}/api/auth/register", json={
            "email": user_email,
            "username": f"deldenied_{suffix}",
            "password": user_password
        })

        pending_response = authenticated_session.get(f"{API_BASE_URL}/api/users/pending")
        pending_users = pending_response.json()['users']
        target_user = next((u for u in pending_users if u['email'] == user_email), None)
        assert target_user is not None
        user_id = target_user['id']

        assert authenticated_session.post(f"{API_BASE_URL}/api/users/{user_id}/approve").status_code == 200
        assert authenticated_session.post(
            f"{API_BASE_URL}/api/users/{user_id}/roles",
            json={"role_name": role_name}
        ).status_code == 200

        user_session = requests.Session()
        login_response = user_session.post(
            f"{API_BASE_URL}/api/auth/login",
            json={"email": user_email, "password": user_password}
        )
        assert login_response.status_code == 200, login_response.text

        delete_response = user_session.delete(f"{API_BASE_URL}/api/admin/test-user")
        assert delete_response.status_code == 403, delete_response.text

    def test_admin_can_remove_known_test_user(self, empty_database):
        """An admin with user.manage can delete the known test user (self-delete path)."""
        # empty_database gives a clean DB with no users and handles teardown.
        setup_session = requests.Session()
        ensure_test_admin_session(setup_session)

        delete_response = setup_session.delete(f"{API_BASE_URL}/api/admin/test-user")
        assert delete_response.status_code == 200, delete_response.text

        data = delete_response.json()
        assert data['success'] is True
        assert data['action'] == 'deleted'
        assert data['deleted_current_user'] is True

        login_response = requests.Session().post(
            f"{API_BASE_URL}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
        )
        assert login_response.status_code != 200

class TestCompleteUserManagementFlow:
    """Test complete user management workflow."""
    
    def test_full_user_management_cycle(self, setup_test_environment):
        """Test complete lifecycle of user management."""
        admin = setup_test_environment
        
        # 1. Check pending users
        response = admin.get(f"{API_BASE_URL}/api/users/pending")
        assert response.status_code == 200, response.text
        initial_pending = len(response.json()['users'])
        assert initial_pending >= 3
        
        # 2. Register new user
        new_user_email = "lifecycle@test.com"
        requests.post(f"{API_BASE_URL}/api/auth/register", json={
            "email": new_user_email,
            "username": "lifecycle",
            "password": "LifecyclePass123!"
        })
        
        # 3. Verify in pending list
        response = admin.get(f"{API_BASE_URL}/api/users/pending")
        assert len(response.json()['users']) == initial_pending + 1
        
        # 4. Get user ID
        new_user = [u for u in response.json()['users'] if u['email'] == new_user_email][0]
        user_id = new_user['id']
        
        # 5. Approve user
        response = admin.post(f"{API_BASE_URL}/api/users/{user_id}/approve")
        assert response.status_code == 200
        
        # 6. Verify board_creator role is auto-assigned on approval
        response = admin.get(f"{API_BASE_URL}/api/users")
        assert response.status_code == 200
        approved_user = next(u for u in response.json()['users'] if u['id'] == user_id)
        role_names = [r['name'] for r in approved_user['roles']]
        assert 'board_creator' in role_names
        
        # 7. Verify user can login
        user_session = requests.Session()
        response = user_session.post(f"{API_BASE_URL}/api/auth/login", json={
            "email": new_user_email,
            "password": "LifecyclePass123!"
        })
        assert response.status_code == 200
        
        # 8. Check user has the assigned board_creator role
        response = user_session.get(f"{API_BASE_URL}/api/auth/me")
        roles = [r['name'] for r in response.json()['user']['roles']]
        assert 'board_creator' in roles
        
        # 9. Deactivate user
        response = admin.post(f"{API_BASE_URL}/api/users/{user_id}/deactivate")
        assert response.status_code == 200
        
        # 10. Verify user cannot login
        new_session = requests.Session()
        response = new_session.post(f"{API_BASE_URL}/api/auth/login", json={
            "email": new_user_email,
            "password": "LifecyclePass123!"
        })
        assert response.status_code == 403
        
        # 11. Reactivate user
        response = admin.post(f"{API_BASE_URL}/api/users/{user_id}/activate")
        assert response.status_code == 200
        
        # 12. Verify user can login again
        final_session = requests.Session()
        response = final_session.post(f"{API_BASE_URL}/api/auth/login", json={
            "email": new_user_email,
            "password": "LifecyclePass123!"
        })
        assert response.status_code == 200


class TestSelfRoleModificationPrevention:
    """Test that users cannot modify their own roles."""
    
    def test_cannot_assign_role_to_self_via_roles_endpoint(self, admin_session):
        """Admin should not be able to assign roles to themselves via /api/roles/assign."""
        roles_response = admin_session.get(f"{API_BASE_URL}/api/roles")
        assert roles_response.status_code == 200
        board_creator_role = next(r for r in roles_response.json()['roles'] if r['name'] == 'board_creator')

        # Get current user info
        response = admin_session.get(f"{API_BASE_URL}/api/auth/me")
        assert response.status_code == 200
        current_user_id = response.json()['user']['id']
        
        # Try to assign a role to self - should fail
        response = admin_session.post(
            f"{API_BASE_URL}/api/roles/assign",
            json={
                "user_id": current_user_id,
                "role_id": board_creator_role['id']
            }
        )
        assert response.status_code == 403
        data = response.json()
        assert data['success'] is False
        assert "cannot modify your own roles" in data['message'].lower()
    
    def test_cannot_remove_role_from_self_via_roles_endpoint(self, admin_session):
        """Admin should not be able to remove roles from themselves via /api/roles/remove."""
        # Get current user info
        response = admin_session.get(f"{API_BASE_URL}/api/auth/me")
        assert response.status_code == 200
        current_user = response.json()['user']
        current_user_id = current_user['id']
        
        # Get one of the admin's roles
        if len(current_user['roles']) > 0:
            role_id = current_user['roles'][0]['id']
            
            # Try to remove role from self - should fail
            response = admin_session.post(
                f"{API_BASE_URL}/api/roles/remove",
                json={
                    "user_id": current_user_id,
                    "role_id": role_id
                }
            )
            assert response.status_code == 403
            data = response.json()
            assert data['success'] is False
            assert "cannot modify your own roles" in data['message'].lower()
    
    def test_cannot_assign_role_to_self_via_users_endpoint(self, admin_session):
        """Admin should not be able to assign roles to themselves via /api/users/:id/roles."""
        # Get current user info
        response = admin_session.get(f"{API_BASE_URL}/api/auth/me")
        assert response.status_code == 200
        current_user_id = response.json()['user']['id']
        
        # Try to assign a role to self - should fail
        response = admin_session.post(
            f"{API_BASE_URL}/api/users/{current_user_id}/roles",
            json={"role_name": "board_creator"}
        )
        assert response.status_code == 403
        data = response.json()
        assert data['success'] is False
        assert "cannot modify your own roles" in data['message'].lower()
    
    def test_cannot_remove_role_from_self_via_users_endpoint(self, admin_session):
        """Admin should not be able to remove roles from themselves via /api/users/:id/roles/:role_id."""
        # Get current user info
        response = admin_session.get(f"{API_BASE_URL}/api/auth/me")
        assert response.status_code == 200
        current_user = response.json()['user']
        current_user_id = current_user['id']
        
        # Get one of the admin's roles
        if len(current_user['roles']) > 0:
            role_id = current_user['roles'][0]['id']
            
            # Try to remove role from self - should fail
            response = admin_session.delete(
                f"{API_BASE_URL}/api/users/{current_user_id}/roles/{role_id}"
            )
            assert response.status_code == 403
            data = response.json()
            assert data['success'] is False
            assert "cannot modify your own roles" in data['message'].lower()
    
    def test_can_assign_role_to_other_user(self, admin_session, setup_test_environment):
        """Admin should still be able to assign roles to other users."""
        roles_response = admin_session.get(f"{API_BASE_URL}/api/roles")
        assert roles_response.status_code == 200
        board_creator_role = next(r for r in roles_response.json()['roles'] if r['name'] == 'board_creator')

        # Get a different user
        response = admin_session.get(f"{API_BASE_URL}/api/users")
        users = response.json()['users']
        
        # Get current user ID
        me_response = admin_session.get(f"{API_BASE_URL}/api/auth/me")
        current_user_id = me_response.json()['user']['id']
        
        # Find a different user
        other_user = next((u for u in users if u['id'] != current_user_id), None)
        
        if other_user:
            # Should succeed in assigning role to other user
            response = admin_session.post(
                f"{API_BASE_URL}/api/roles/assign",
                json={
                    "user_id": other_user['id'],
                    "role_id": board_creator_role['id']
                }
            )
            # Should either succeed (200) or indicate role already exists (409)
            assert response.status_code in [200, 409]

