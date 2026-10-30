# Testing Guide

## Overview

This test suite includes both **unit tests** and **API integration tests**. 

- **Unit Tests**: Test individual functions and utilities without requiring a running server
- **API Integration Tests**: Make HTTP requests to validate the external behaviour of API endpoints

## Test Organisation

```
server/tests/
├── __init__.py                     # Test package
├── conftest.py                     # Pytest fixtures and configuration
├── test_utils.py                   # Unit tests for validation utilities (25 tests)
├── test_api_authentication.py      # Authentication and user management API tests
├── test_api_boards.py              # Board and column API tests
├── test_api_cards.py               # Card API tests
├── test_api_checklist_items.py     # Checklist item API tests
├── test_api_comments.py            # Comment API tests
├── test_api_notifications.py       # Notification API tests
├── test_api_settings.py            # Settings API tests
├── test_api_themes.py              # Theme API tests
├── test_api_edge_cases.py          # Edge case and security tests (40+ tests)
├── test_api_database_backups.py    # Database backup/restore API tests
├── test_api_card_scheduler.py      # Card scheduling API tests
├── test_api_housekeeping.py        # Housekeeping and cleanup tests
└── ... (additional test files)     # Other specialised tests
```

## Running Tests Locally (Recommended)

### Prerequisites

1. **Python 3.11+** installed on your machine
2. **Docker containers running** for the database and API server:
```powershell
docker compose up -d
```
   - The API must be running at `http://localhost` (via nginx)
   - Wait a few seconds for the server to be ready
3. **Passkeys enabled** for the passkey tests (`tests/test_api_passkeys.py`). Add these to `.env` and rebuild the server; without them the passkey ceremony tests are skipped:
```
WEBAUTHN_RP_ID=localhost
WEBAUTHN_ORIGINS=http://localhost,https://localhost
```
4. **Server requirements in the venv**: some unit tests import server modules, so install both `server/requirements.txt` and `server/requirements-dev.txt`.

### Important: Authentication for Tests

**Tests now require authentication** (as of user support implementation). The test suite automatically handles authentication by:

1. **Creating a test admin user** on first run (via `/api/auth/setup/admin` on fresh DB)
2. **Logging in with known credentials** on subsequent runs
3. **Using authenticated sessions** for all API requests

The test admin credentials are:
- Email: `test-admin@localhost`
- Username: `test-admin`
- Password: `TestAdmin123!`

**You do NOT need to manually create users or login**. The test fixtures handle this automatically.

#### When to Use a Fresh Database

**IMPORTANT:** Automatic test admin creation **only works on a fresh database** with no existing users. If there is already an admin user in the system, the test admin creation will fail because new user registrations require admin approval.

You **MUST** start with a fresh database if:

- There are existing admin users in the system
- Tests are failing with authentication errors
- You want to test the initial setup flow
- Previous test runs left the database in an unexpected state

**To start with a fresh database:**

```powershell
# Windows PowerShell
docker compose down
Remove-Item -Recurse -Force data
docker compose up -d
```

```bash
# Linux/macOS
docker compose down
rm -rf data
docker compose up -d
```

Wait a few seconds for the server to be ready, then run tests.

**Note:** Once the test admin user exists, tests will work fine with existing data by logging in with the known credentials.

### Setup Local Environment

1. **Create virtual environment** (one-time setup):
```powershell
cd server
python -m venv venv
.\venv\Scripts\Activate.ps1
```

2. **Install development dependencies** (includes pytest and test tools):
```powershell
pip install -r requirements-dev.txt
```

3. **Configure VS Code** (optional):
   - Select Python interpreter: `Ctrl+Shift+P` → "Python: Select Interpreter"
   - Choose: `.\server\venv\Scripts\python.exe`
   - Tests will auto-discover in the Testing panel

### Run Tests

```powershell
cd server
.\venv\Scripts\Activate.ps1

# Run all tests (both unit and integration)
pytest

# Run only unit tests (fast, no API required)
pytest -m unit

# Run only API integration tests (requires Docker)
pytest -m api

# Run with verbose output
pytest -v

# Run with detailed output and stop on first failure
pytest -v -x

# Run specific test file
pytest tests/test_utils.py -v
pytest tests/test_api_boards.py -v
pytest tests/test_api_edge_cases.py -v
```

### Note on Coverage

**Coverage reporting is not applicable** for API integration tests because they make HTTP requests to an external server (Docker container). The tests validate API behaviour, not internal code paths. 

However, unit tests in `test_utils.py` do test internal code paths and provide code coverage for validation utilities.

### Run Specific Test Categories

```powershell
# Run only API tests
pytest -m api

# Run only unit tests
pytest -m unit

# Run only integration tests
pytest -m integration
```

### Run Specific Test Files

```powershell
# Test boards API
pytest tests/test_api_boards.py

# Test cards API
pytest tests/test_api_cards.py

# Test settings API
pytest tests/test_api_settings.py
```

### Run Specific Test Functions

```powershell
# Run a specific test by name
pytest tests/test_api_boards.py::TestBoardsAPI::test_create_board

# Run tests matching a pattern
pytest -k "test_create"

# Run with extra verbosity to see request/response details
pytest -v -s
```

## VS Code Integration

Tests are configured to work with VS Code's Testing panel:

1. Ensure Docker containers are running: `docker compose up -d`
2. Open the Testing view (beaker icon in sidebar)
3. Tests will auto-discover
4. Click play buttons to run individual tests or test suites

### VS Code Test Features

- ✅ Run tests from the UI
- ✅ Debug tests with breakpoints
- ✅ Auto-discover tests on save
- ✅ View test results inline
- ✅ Navigate to failed tests

**Note**: When running tests from VS Code, they may occasionally fail due to timing issues. Running from command line (`pytest tests/`) is more reliable for full test suite execution.

## Test Architecture

The test suite includes two types of tests:

### Unit Tests (`test_utils.py`)
- **Fast**: No API server required
- **Focused**: Test individual validation functions in isolation
- **Comprehensive**: 25 tests covering edge cases, boundary conditions, and error handling
- Tests for:
  - String length validation
  - Integer validation (including type checking, min/max constraints)
  - String sanitization
  - Validation constants

### API Integration Tests
These are **API integration tests** that:
- Make real HTTP requests to `http://localhost` (via nginx)
- Test the running Docker container, not Python code directly
- Validate API behaviour, status codes, and response data
- Automatically clean up test data between runs

**Test Files**:
- `test_api_boards.py` - Board and column CRUD operations
- `test_api_cards.py` - Card CRUD operations  
- `test_api_settings.py` - Settings management
- `test_api_edge_cases.py` - Security and edge case validation (40+ tests)

### Edge Case and Security Tests (`test_api_edge_cases.py`)

This file contains comprehensive tests for:

**Input Validation Tests**:
- Malformed JSON handling
- Oversized inputs (names, titles, descriptions)
- Special characters and Unicode
- Null and empty values
- Wrong data types (integers as strings, arrays, etc.)
- Negative, zero, and huge ID values

**Security Tests**:
- SQL injection attempts
- XSS attack vectors (validated for storage safety)
- Request size limits
- Content-Type validation

**Boundary Condition Tests**:
- Maximum length strings
- Many items (50 columns, 100 cards)
- Edge values for integers

**Concurrency Tests**:
- Double deletion
- Update after delete
- Create in deleted parent

### Backup Security Unit Tests (`test_backup_security.py`)

These tests import backup validation helpers directly from `app.py` and validate SQL/file safety logic only.

- The module explicitly sets `ENABLE_SERVER_SIDE_SESSIONS=false` at test import time.
- This is intentional: backup security tests are session-backend agnostic and should not require optional Redis session packages to run in local unit-test environments.
- Runtime behaviour is unchanged for the application; this only scopes test setup for that file.

### Test Isolation Strategy

- **Session cleanup**: Cleans all data before test suite starts
- **Test cleanup**: Cleans all data after each test completes
- **Explicit fixtures**: `clean_database` and `isolated_test` for tests needing guaranteed clean state
- **Data fixtures**: `sample_board`, `sample_column`, `sample_card` create test data as needed

## Test Structure

```
server/tests/
├── __init__.py              # Test package
├── conftest.py              # Pytest fixtures and configuration
├── test_api_boards.py       # Board and column API endpoint tests
├── test_api_cards.py        # Card API endpoint tests
└── test_api_settings.py     # Settings API endpoint tests
```

## Available Fixtures

Defined in `conftest.py`:

- `api_client` - Base URL for API (`http://localhost` via nginx)
- `clean_database` - Ensures database is empty before test runs (API tests only)
- `isolated_test` - Ensures database is clean before fixtures create data (API tests only)
- `sample_board` - Creates a test board via API
- `sample_column` - Creates a test column via API (requires `sample_board`)
- `sample_card` - Creates a test card via API (requires `sample_column`)

**Note**: Unit tests automatically skip API-related fixtures for faster execution.

## Writing New Tests

### Example Unit Test

```python
import pytest
from utils import validate_string_length, MAX_TITLE_LENGTH

@pytest.mark.unit
class TestMyValidation:
    def test_valid_input(self):
        """Test validation passes for valid input."""
        is_valid, error = validate_string_length("Test", MAX_TITLE_LENGTH, "Name")
        assert is_valid is True
        assert error is None
```

### Example API Test

```python
import requests
import pytest

@pytest.mark.api
class TestMyAPI:
    def test_my_endpoint(self, api_client):
        """Test description."""
        response = requests.get(f'{api_client}/api/my-endpoint')
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
    
    def test_with_clean_database(self, api_client, clean_database):
        """Test that needs empty database."""
        response = requests.get(f'{api_client}/api/boards')
        assert response.json()['boards'] == []
    
    def test_with_data(self, api_client, isolated_test, sample_board):
        """Test with exactly one board."""
        response = requests.get(f'{api_client}/api/boards')
        assert len(response.json()['boards']) == 1
```

## Continuous Integration

Tests can be integrated into CI/CD pipelines:

```yaml
# Example GitHub Actions workflow
- name: Start services
  run: docker compose up -d

- name: Wait for API
  run: |
    timeout 30 bash -c 'until curl -f http://localhost/api/version; do sleep 1; done'

- name: Setup Python
  uses: actions/setup-python@v4
  with:
    python-version: '3.11'

- name: Install dependencies
  run: |
    cd server
    pip install -r requirements-dev.txt

- name: Run tests
  run: |
    cd server
    pytest -v
```

## Troubleshooting

### API Connection Issues

If tests fail with connection errors:
```powershell
# Check if API is running
curl http://localhost/api/version

# Restart containers
docker compose restart

# View logs
docker compose logs server
```

### Tests Fail Randomly in VS Code

The command line is more reliable. Run tests via:
```powershell
cd server
pytest tests/ -v
```

### Database State Issues

Tests automatically clean up, but if you need to manually reset:
```powershell
# Restart database container
docker compose restart db

# Or recreate all containers
docker compose down
docker compose up -d
```

### Permission Errors on Windows

If you see `.coverage` permission errors:
- This is expected - coverage doesn't work for API tests
- Tests will still run successfully
- You can disable coverage in `pytest.ini` if it bothers you
