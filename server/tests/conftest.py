"""Pytest configuration and fixtures."""
import os
import pytest
import requests
import time
import uuid
from urllib.parse import urlparse


# API base URL - tests hit through nginx like external API clients would
# This mimics how external tools/UIs would access the API (via 80/443, not internal 5000)
# Override with PYTEST_API_BASE_URL for local debugging if needed.
API_BASE_URL = os.getenv("PYTEST_API_BASE_URL", "http://localhost")
TEST_API_HOST = urlparse(API_BASE_URL).hostname or "localhost"


def _env_float(name, default):
    """Parse float env vars safely with a fallback."""
    raw = os.getenv(name)
    if raw in (None, ""):
        return default

    try:
        value = float(raw)
    except ValueError:
        return default

    return value if value > 0 else default


API_WAIT_TIMEOUT_SECONDS = _env_float("PYTEST_API_WAIT_TIMEOUT_SECONDS", 8.0)
API_WAIT_INTERVAL_SECONDS = _env_float("PYTEST_API_WAIT_INTERVAL_SECONDS", 0.5)
API_REQUEST_TIMEOUT_SECONDS = _env_float("PYTEST_API_REQUEST_TIMEOUT_SECONDS", 1.0)
API_READY_ENDPOINT = os.getenv("PYTEST_API_READY_ENDPOINT", "/api/auth/setup/status")

# Authentication candidates for test-admin recovery across auth-flow tests.
# Some auth tests briefly rotate the canonical test-admin password.
TEST_ADMIN_LOGIN_CANDIDATES = [
    ("test-admin@localhost", "TestAdmin123!"),
    ("test-admin@localhost", "NewAdminPass456!"),
]

# Cleanup timing constants (in seconds)
# These delays ensure async operations complete before proceeding
CLEANUP_DELAY_SHORT = 0.1    # Standard delay after test cleanup
CLEANUP_DELAY_MEDIUM = 0.15  # Delay for explicit clean operations
CLEANUP_DELAY_LONG = 0.2     # Delay for session-level initialization


def _mirror_secure_session_cookies_for_http(session):
    """Mirror secure cookies to non-secure for local HTTP test runs.

    When SESSION_COOKIE_SECURE=true in the server, auth cookies are marked
    Secure and are not sent over HTTP by requests. The API tests intentionally
    run against HTTP localhost, so mirror secure auth cookies as non-secure
    inside the test client session only.
    """
    if not isinstance(session, requests.Session):
        return

    if not API_BASE_URL.startswith("http://"):
        return

    secure_cookies = [cookie for cookie in session.cookies if cookie.secure]
    for cookie in secure_cookies:
        cookie_path = cookie.path or "/"

        # Host-only variant for localhost/127 test requests.
        session.cookies.set(
            cookie.name,
            cookie.value,
            path=cookie_path,
            secure=False,
        )

        # Domain-scoped variant for clients that match by explicit host.
        session.cookies.set(
            cookie.name,
            cookie.value,
            domain=TEST_API_HOST,
            path=cookie_path,
            secure=False,
        )


_ORIGINAL_SESSION_REQUEST = requests.Session.request


def _patched_session_request(self, method, url, *args, **kwargs):
    """Patch requests.Session.request so HTTP test sessions keep auth cookies."""
    if isinstance(url, str) and url.startswith("http://"):
        _mirror_secure_session_cookies_for_http(self)

    response = _ORIGINAL_SESSION_REQUEST(self, method, url, *args, **kwargs)

    if isinstance(url, str) and url.startswith("http://"):
        _mirror_secure_session_cookies_for_http(self)

    return response


# Apply once for the full pytest process so all ad-hoc sessions in tests behave.
requests.Session.request = _patched_session_request


def _is_setup_already_complete_response(response):
    """Return True when setup/admin endpoint indicates setup already completed."""
    if response is None or response.status_code != 403:
        return False

    try:
        data = response.json()
    except ValueError:
        return False

    message = str(data.get("message", "")).lower()
    return "setup is already complete" in message


def _login_test_admin(session):
    """Attempt login as the canonical test-admin identity only."""
    for email, password in TEST_ADMIN_LOGIN_CANDIDATES:
        login_response = session.post(f"{API_BASE_URL}/api/auth/login", json={
            "email": email,
            "password": password,
        })

        if login_response.status_code == 200:
            try:
                me_response = session.get(f"{API_BASE_URL}/api/auth/me")
                if me_response.status_code == 200:
                    me_email = me_response.json().get("user", {}).get("email", "")
                    if me_email != "test-admin@localhost":
                        session.cookies.clear()
                        continue
            except requests.exceptions.RequestException:
                session.cookies.clear()
                continue

            _mirror_secure_session_cookies_for_http(session)
            return True

    return False


@pytest.fixture(scope='session')
def wait_for_api(request):
    """Wait for API to be ready before running tests (API tests only)."""
    # Only run for API tests
    if 'unit' in request.keywords:
        return

    deadline = time.time() + API_WAIT_TIMEOUT_SECONDS
    last_error = None

    while time.time() < deadline:
        try:
            response = requests.get(
                f"{API_BASE_URL}{API_READY_ENDPOINT}",
                timeout=API_REQUEST_TIMEOUT_SECONDS,
            )
            # Any non-5xx response indicates the API process is reachable.
            if response.status_code < 500:
                return
            last_error = f"unexpected status {response.status_code}"
        except requests.exceptions.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"

        time.sleep(API_WAIT_INTERVAL_SECONDS)

    raise Exception(
        "API not available for API tests. "
        f"Tried {API_BASE_URL}{API_READY_ENDPOINT} for {API_WAIT_TIMEOUT_SECONDS:.1f}s; "
        f"last error: {last_error}. "
        "Start the integration stack first (e.g. `docker compose up -d nginx`) "
        "or increase PYTEST_API_WAIT_TIMEOUT_SECONDS."
    )


@pytest.fixture(scope='session')
def test_admin_session(request, wait_for_api):
    """Create or login as test admin user and return authenticated session (API tests only).
    
    This fixture handles three scenarios:
    1. Fresh install (no users): Creates test admin via setup endpoint
    2. Test admin exists: Logs in with known credentials
    3. Other users exist but not test admin: Creates test admin via register endpoint
    
    The test admin credentials are:
    - Email: test-admin@localhost
    - Username: test-admin
    - Password: TestAdmin123!
    """
    # Only run for API tests
    if 'unit' in request.keywords:
        return None
    
    session = requests.Session()
    
    try:
        # Check if setup is needed
        setup_response = session.get(f"{API_BASE_URL}/api/auth/setup/status")
        if setup_response.status_code != 200:
            raise Exception(
                f"\n{'='*70}\n"
                f"AUTHENTICATION SETUP FAILED\n"
                f"{'='*70}\n"
                f"Could not check setup status (HTTP {setup_response.status_code})\n"
                f"The authentication system may not be running or configured correctly.\n"
                f"Make sure the API server is running: docker compose up -d\n"
                f"{'='*70}\n"
            )
        
        setup_data = setup_response.json()
        
        # If setup not complete (no users exist), create admin user via setup
        if not setup_data.get('setup_complete', False):
            print("\n[Test Setup] No users found - creating test admin user...")
            admin_response = session.post(f"{API_BASE_URL}/api/auth/setup/admin", json={
                "email": "test-admin@localhost",
                "username": "test-admin",
                "password": "TestAdmin123!",
                "display_name": "Test Admin"
            })
            if _is_setup_already_complete_response(admin_response):
                if _login_test_admin(session):
                    print("[Test Setup] Setup completed during init; logged in as test admin")
                else:
                    raise Exception(
                        f"\n{'='*70}\n"
                        f"AUTHENTICATION SETUP FAILED\n"
                        f"{'='*70}\n"
                        f"Setup completed during initialization, but test admin login failed.\n"
                        f"HTTP Status: {admin_response.status_code}\n"
                        f"Response: {admin_response.text}\n"
                        f"{'='*70}\n"
                    )
            elif admin_response.status_code not in (200, 201):
                raise Exception(
                    f"\n{'='*70}\n"
                    f"AUTHENTICATION SETUP FAILED\n"
                    f"{'='*70}\n"
                    f"Failed to create test admin user via setup endpoint.\n"
                    f"HTTP Status: {admin_response.status_code}\n"
                    f"Response: {admin_response.text}\n\n"
                    f"This usually means:\n"
                    f"  1. The authentication API is not properly configured\n"
                    f"  2. The database migrations have not been run\n"
                    f"  3. There's a permission or validation error\n\n"
                    f"Try resetting the database:\n"
                    f"  docker compose down\n"
                    f"  Remove-Item -Recurse -Force data\n"
                    f"  docker compose up -d\n"
                    f"{'='*70}\n"
                )
            else:
                print("[Test Setup] Test admin user created successfully")
        else:
            # Users exist - try to login as test admin
            print("\n[Test Setup] Users exist - logging in as test admin...")
            login_ok = _login_test_admin(session)
            
            # If login fails, test admin doesn't exist - can't proceed
            if not login_ok:
                # Cannot create test admin when other users exist - would require approval
                pytest.exit(
                    f"\n{'='*70}\n"
                    f"AUTHENTICATION SETUP FAILED - FRESH DATABASE REQUIRED\n"
                    f"{'='*70}\n\n"
                    f"Cannot create test admin user because other users already exist.\n"
                    f"When users exist, new registrations require admin approval.\n\n"
                    f"SOLUTION: Reset the database AND sessions to start fresh:\n\n"
                    f"  # Windows PowerShell:\n"
                    f"  docker compose down\n"
                    f"  Remove-Item -Recurse -Force data\n"
                    f"  docker compose up -d\n\n"
                    f"  # Linux/macOS:\n"
                    f"  docker compose down\n"
                    f"  rm -rf data\n"
                    f"  docker compose up -d\n\n"
                    f"NOTE: docker compose down clears Redis sessions automatically.\n"
                    f"Then run tests again. The test suite will automatically create\n"
                    f"the test admin user on the fresh database.\n\n"
                    f"{'='*70}\n",
                    returncode=1
                )
            print("[Test Setup] Successfully logged in as test admin")

        _mirror_secure_session_cookies_for_http(session)
        
        return session
    
    except requests.exceptions.RequestException as e:
        raise Exception(
            f"\n{'='*70}\n"
            f"AUTHENTICATION SETUP FAILED\n"
            f"{'='*70}\n"
            f"Network error while setting up authentication.\n"
            f"Error: {str(e)}\n\n"
            f"Make sure the API server is running:\n"
            f"  docker compose up -d\n\n"
            f"Check that the API is accessible at: {API_BASE_URL}\n"
            f"{'='*70}\n"
        )
    except Exception as e:
        # Re-raise if already formatted
        if "AUTHENTICATION SETUP FAILED" in str(e):
            raise
        # Otherwise, wrap in our format
        raise Exception(
            f"\n{'='*70}\n"
            f"AUTHENTICATION SETUP FAILED\n"
            f"{'='*70}\n"
            f"Unexpected error during authentication setup.\n"
            f"Error: {str(e)}\n"
            f"{'='*70}\n"
        )


@pytest.fixture(scope='session', autouse=True)
def cleanup_all_data(request, test_admin_session):
    """Clean up all test data before and after entire test session (API tests only)."""
    # Only run for API tests
    if 'unit' in request.keywords:
        return
    
    # Cleanup before all tests - ensure we start with clean state
    _delete_all_data(test_admin_session)
    time.sleep(CLEANUP_DELAY_LONG)  # Extra time to ensure cleanup completes
    
    yield
    
    # Cleanup after all tests
    _delete_all_data(test_admin_session)


@pytest.fixture
def authenticated_session(test_admin_session):
    """Provide authenticated session for individual tests (API tests only).
    
    Verifies the session is still valid, and if not (e.g., after DB reset),
    recreates the test admin user and re-authenticates.
    """
    # Check if session is still valid
    _mirror_secure_session_cookies_for_http(test_admin_session)
    check_response = test_admin_session.get(f"{API_BASE_URL}/api/auth/check")
    
    # If session is invalid (503 = no users, 401 = not authenticated)
    if check_response.status_code in (503, 401):
        print(f"\n[Test Setup] Session invalid (HTTP {check_response.status_code}) - recreating test admin...")
        
        # Clear cookies
        test_admin_session.cookies.clear()

        deadline = time.time() + 10
        last_error = "unknown"

        while time.time() < deadline:
            setup_response = test_admin_session.get(f"{API_BASE_URL}/api/auth/setup/status")
            if setup_response.status_code != 200:
                last_error = f"setup status HTTP {setup_response.status_code}"
                time.sleep(0.2)
                continue

            setup_data = setup_response.json()

            if not setup_data.get('setup_complete', False):
                admin_response = test_admin_session.post(f"{API_BASE_URL}/api/auth/setup/admin", json={
                    "email": "test-admin@localhost",
                    "username": "test-admin",
                    "password": "TestAdmin123!",
                    "display_name": "Test Admin"
                })
                if admin_response.status_code in (200, 201):
                    print("[Test Setup] Test admin recreated successfully")
                    _mirror_secure_session_cookies_for_http(test_admin_session)
                elif _is_setup_already_complete_response(admin_response) and _login_test_admin(test_admin_session):
                    print("[Test Setup] Setup completed during recreate; logged in as test admin")
                else:
                    last_error = f"setup admin HTTP {admin_response.status_code}"
                    time.sleep(0.2)
                    continue
            else:
                if _login_test_admin(test_admin_session):
                    print("[Test Setup] Logged in as test admin successfully")
                    _mirror_secure_session_cookies_for_http(test_admin_session)
                else:
                    last_error = "login HTTP 401"
                    time.sleep(0.2)
                    continue

            verify_response = test_admin_session.get(f"{API_BASE_URL}/api/auth/check")
            if verify_response.status_code == 200:
                break

            last_error = f"auth check HTTP {verify_response.status_code}"
            time.sleep(0.2)
        else:
            raise Exception(f"Session still invalid after recreation: {last_error}")
    
    return test_admin_session


@pytest.fixture
def clean_database(request, test_admin_session):
    """Ensure database is clean before test runs. Use this for tests that need empty DB (API tests only)."""
    # Only run for API tests
    if 'unit' in request.keywords:
        return
    
    _delete_all_data(test_admin_session)
    time.sleep(CLEANUP_DELAY_MEDIUM)
    yield
    # Cleanup after as well
    time.sleep(CLEANUP_DELAY_SHORT)
    _delete_all_data(test_admin_session)


@pytest.fixture(autouse=True)
def cleanup_between_tests(request, test_admin_session):
    """Clean up data after each test to ensure isolation (API tests only).
    
    Note: We don't clean BEFORE tests because:
    1. Session-level cleanup ensures the first test starts clean
    2. Each test's post-cleanup ensures the next test starts clean
    3. Pre-test cleanup would delete fixture data (race condition)
    
    For tests that explicitly need empty DB, use clean_database or isolated_test fixtures.
    """
    yield
    
    # Only cleanup for API tests
    if 'unit' not in request.keywords:
        # Skip cleanup if test uses empty_database fixture (it handles its own cleanup)
        if 'empty_database' in request.fixturenames:
            return
        
        # Cleanup after each test (important for isolation)
        time.sleep(CLEANUP_DELAY_SHORT)
        _delete_all_data(test_admin_session)
    

@pytest.fixture
def isolated_test(test_admin_session):
    """Fixture to ensure complete test isolation - cleans before the test."""
    _delete_all_data(test_admin_session)
    time.sleep(CLEANUP_DELAY_MEDIUM)
    yield


def _delete_all_data(session=None):
    """Helper to delete all boards, notifications and settings, ensuring clean state.
    
    Args:
        session: Optional authenticated requests.Session. If None, uses unauthenticated requests.
    """
    # Use provided session or fallback to requests module
    http = session if session else requests

    def _setup_is_incomplete():
        try:
            status_response = requests.get(f"{API_BASE_URL}/api/auth/setup/status", timeout=5)
            if status_response.status_code != 200:
                return True
            return not status_response.json().get('setup_complete', False)
        except requests.exceptions.RequestException:
            return True

    def _refresh_authenticated_session():
        if not isinstance(session, requests.Session):
            return False

        try:
            check_response = session.get(f"{API_BASE_URL}/api/auth/check", timeout=5)
            if check_response.status_code == 200:
                return True

            if check_response.status_code == 503 and _setup_is_incomplete():
                session.cookies.clear()
                return False

            session.cookies.clear()

            for email, password in TEST_ADMIN_LOGIN_CANDIDATES:
                login_response = session.post(
                    f"{API_BASE_URL}/api/auth/login",
                    json={"email": email, "password": password},
                    timeout=5,
                )
                if login_response.status_code == 200:
                    _mirror_secure_session_cookies_for_http(session)
                    return True

            return False
        except requests.exceptions.RequestException:
            return False

    def _request_with_reauth(method, url, **kwargs):
        response = method(url, **kwargs)

        if not isinstance(session, requests.Session):
            return response

        if response.status_code not in (401, 503):
            return response

        if response.status_code == 503 and _setup_is_incomplete():
            return response

        if _refresh_authenticated_session():
            return method(url, **kwargs)

        return response
    
    try:
        if isinstance(session, requests.Session):
            _refresh_authenticated_session()

        # Delete all boards (cascades to columns and cards)
        response = _request_with_reauth(http.get, f"{API_BASE_URL}/api/boards", timeout=5)
        if response.status_code == 200:
            boards = response.json().get('boards', [])
            failed_deletes = []
            
            for board in boards:
                delete_response = _request_with_reauth(
                    http.delete,
                    f"{API_BASE_URL}/api/boards/{board['id']}",
                    timeout=5,
                )
                # 404 means the board was already removed between list and delete.
                if delete_response.status_code not in (200, 404):
                    failed_deletes.append({
                        'id': board['id'],
                        'name': board['name'],
                        'status': delete_response.status_code,
                        'error': delete_response.json().get('message', 'Unknown error')
                    })
            
            # If any deletes failed due to permissions, we have orphaned data
            if failed_deletes:
                error_msg = (
                    f"\n{'='*70}\n"
                    f"TEST CLEANUP FAILED - PERMISSION DENIED\n"
                    f"{'='*70}\n"
                    f"Failed to delete {len(failed_deletes)} board(s):\n"
                )
                for fail in failed_deletes:
                    error_msg += f"  - Board {fail['id']} ({fail['name']}): {fail['status']} - {fail['error']}\n"
                error_msg += (
                    f"\nThis usually means boards were created by a different user.\n"
                    f"Tests require a clean database with no pre-existing data.\n\n"
                )
                
                error_msg += (
                    f"\nREQUIRED ACTION: Manually reset the database:\n"
                    f"  docker compose down\n"
                    f"  Remove-Item -Recurse -Force data  # Windows\n"
                    f"  # rm -rf data  # Linux/macOS\n"
                    f"  docker compose up -d\n"
                    f"{'='*70}\n"
                )
                raise Exception(error_msg)
        
        # Verify boards are actually deleted before proceeding
        verify_response = _request_with_reauth(http.get, f"{API_BASE_URL}/api/boards", timeout=5)
        if verify_response.status_code == 200:
            remaining = verify_response.json().get('boards', [])
            if remaining:
                # Handle eventual consistency/race windows by retrying cleanup briefly.
                for _ in range(3):
                    time.sleep(CLEANUP_DELAY_SHORT)
                    for board in remaining:
                        _request_with_reauth(
                            http.delete,
                            f"{API_BASE_URL}/api/boards/{board['id']}",
                            timeout=5,
                        )
                    verify_response = _request_with_reauth(http.get, f"{API_BASE_URL}/api/boards", timeout=5)
                    if verify_response.status_code != 200:
                        break
                    remaining = verify_response.json().get('boards', [])
                    if not remaining:
                        break

                if verify_response.status_code == 200 and remaining:
                    raise Exception(
                        f"Cleanup verification failed: {len(remaining)} board(s) still exist after cleanup. "
                        f"Database may be in an inconsistent state."
                    )
        elif verify_response.status_code == 503 and _setup_is_incomplete():
            return
        
        # Delete all notifications
        delete_notif_response = _request_with_reauth(
            http.delete,
            f"{API_BASE_URL}/api/notifications/delete-all",
            timeout=5,
        )
        if delete_notif_response.status_code == 503 and _setup_is_incomplete():
            return
        if delete_notif_response.status_code not in (200, 404):  # 404 is OK if no notifications
            raise Exception(f"Failed to delete notifications: {delete_notif_response.status_code}")
        
        # Reset settings to defaults
        settings_response = _request_with_reauth(
            http.put,
            f"{API_BASE_URL}/api/settings/default_board",
            json={'value': None},
            timeout=5,
        )
        if settings_response.status_code == 503 and _setup_is_incomplete():
            return
        if settings_response.status_code not in (200, 404):
            # Settings failures are less critical, just warn
            print(f"Warning: Failed to reset default_board setting: {settings_response.status_code}")
        
        # Reset backup settings to migration defaults
        backup_response = _request_with_reauth(
            http.put,
            f"{API_BASE_URL}/api/settings/backup/config",
            json={
                'enabled': False,
                'frequency_value': 1,
                'frequency_unit': 'daily',
                'start_time': '00:00',
                'retention_count': 7,
                'minimum_free_space_mb': 100
            },
            timeout=5,
        )
        if backup_response.status_code == 503 and _setup_is_incomplete():
            return
        if backup_response.status_code not in (200, 404):
            print(f"Warning: Failed to reset backup settings: {backup_response.status_code}")
            
    except requests.exceptions.RequestException as e:
        raise Exception(
            f"Cleanup failed with network error: {e}\n"
            f"Make sure the API server is running: docker compose up -d"
        )


@pytest.fixture
def api_client():
    """Provide API base URL for tests."""
    return API_BASE_URL


@pytest.fixture
def sample_board(api_client, authenticated_session):
    """Create a sample board for testing."""
    response = authenticated_session.post(f"{api_client}/api/boards", json={
        'name': 'Test Board',
        'description': 'A test board'
    })
    assert response.status_code == 201
    board = response.json()['board']
    return board


@pytest.fixture
def sample_column(api_client, authenticated_session, sample_board):
    """Create a sample column for testing."""
    response = authenticated_session.post(f"{api_client}/api/boards/{sample_board['id']}/columns", json={
        'name': 'Test Column'
    })
    assert response.status_code == 201, f"Failed to create column: {response.status_code} - {response.text}"
    column = response.json()['column']
    
    # Ensure board_id is in the response
    assert 'board_id' in column, f"Column response missing board_id: {column}"
    assert 'id' in column, f"Column response missing id: {column}"
    
    return column


@pytest.fixture
def sample_card(api_client, authenticated_session, sample_column):
    """Create a sample card for testing."""
    response = authenticated_session.post(f"{api_client}/api/columns/{sample_column['id']}/cards", json={
        'title': 'Test Card',
        'description': 'A test card'
    })
    assert response.status_code == 201
    card = response.json()['card']
    return card


@pytest.fixture
def sample_notification(api_client, authenticated_session):
    """Create a sample notification for testing."""
    response = authenticated_session.post(f"{api_client}/api/notifications", json={
        'subject': 'Test Notification',
        'message': 'This is a test notification'
    })
    assert response.status_code == 201
    # New API returns count, need to fetch the notification
    get_response = authenticated_session.get(f"{api_client}/api/notifications")
    assert get_response.status_code == 200
    notifications = get_response.json()['notifications']
    # Find the notification we just created
    notification = next((n for n in notifications if n['subject'] == 'Test Notification'), None)
    assert notification is not None, (
        f"Expected to find notification with subject 'Test Notification', "
        f"but found subjects: {[n.get('subject') for n in notifications]}"
    )
    return notification


@pytest.fixture
def second_user_session(api_client, test_admin_session):
    """Return an authenticated session for a unique second user.

    The user is created and approved per test to avoid brittle reuse of
    previously-created pending accounts from earlier runs.
    """
    session = requests.Session()

    suffix = uuid.uuid4().hex[:8]
    generated_password = f"TestUserB-{uuid.uuid4().hex[:12]}-Aa1!"
    test_user_payload = {
        "email": f"test-user-b-{suffix}@localhost",
        "username": f"test-user-b-{suffix}",
        "password": generated_password,
        "display_name": f"Test User B {suffix}",
    }

    # Register user B and approve it before login.
    register_response = session.post(f"{api_client}/api/auth/register", json={
        "email": test_user_payload["email"],
        "username": test_user_payload["username"],
        "password": test_user_payload["password"],
        "display_name": test_user_payload["display_name"],
    })
    assert register_response.status_code == 201, (
        f"Failed to register test-user-b: {register_response.status_code} - {register_response.text}"
    )

    register_data = register_response.json()
    user_id = register_data.get('user', {}).get('id') or register_data.get('data', {}).get('user', {}).get('id')
    assert user_id is not None, "Register response missing user id for test-user-b"

    approve_resp = test_admin_session.post(f"{api_client}/api/users/{user_id}/approve")
    assert approve_resp.status_code == 200, (
        f"Failed to approve test-user-b: {approve_resp.status_code} - {approve_resp.text}"
    )

    login_response = session.post(f"{api_client}/api/auth/login", json={
        "email": test_user_payload["email"],
        "password": test_user_payload["password"],
    })
    assert login_response.status_code == 200, (
        f"Login as test-user-b failed: {login_response.status_code} – {login_response.text}"
    )

    yield session

    # Clean up boards visible to user B first. This prevents cross-test residue
    # if admin-scoped cleanup cannot delete user-owned boards under stricter permissions.
    try:
        boards_response = session.get(f"{api_client}/api/boards")
        if boards_response.status_code == 200:
            for board in boards_response.json().get('boards', []):
                session.delete(f"{api_client}/api/boards/{board['id']}")
    except requests.exceptions.RequestException:
        pass

    # Clean up user B's notifications after the test.
    try:
        session.delete(f"{api_client}/api/notifications/delete-all")
    except requests.exceptions.RequestException:
        pass
