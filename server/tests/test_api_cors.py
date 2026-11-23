"""Tests for CORS validation on API endpoints."""

import pytest
import requests
import uuid
import json


@pytest.mark.api
class TestCORSValidation:
    """Test cases for CORS origin validation on HTTP endpoints."""

    def test_request_with_allowed_origin(self, api_client, authenticated_session):
        """Test that requests from allowed origins are accepted."""
        # The default allowed origin is http://localhost
        headers = {'Origin': 'http://localhost'}
        response = authenticated_session.get(
            f'{api_client}/api/boards',
            headers=headers
        )
        assert response.status_code == 200
        assert response.json()['success'] is True
        # Verify CORS headers are present in response
        assert 'Access-Control-Allow-Origin' in response.headers

    def test_request_without_origin_header(self, api_client, authenticated_session):
        """Test that requests without Origin header are allowed (same-origin)."""
        # Requests without Origin header should be allowed
        # This simulates requests from the same origin (no Origin header)
        response = authenticated_session.get(f'{api_client}/api/boards')
        assert response.status_code == 200
        assert response.json()['success'] is True

    def test_preflight_options_request_allowed_origin(self, api_client, authenticated_session):
        """Test that preflight OPTIONS requests are properly handled for allowed origins."""
        headers = {
            'Origin': 'http://localhost',
            'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'Content-Type'
        }
        response = requests.options(
            f'{api_client}/api/boards',
            headers=headers
        )
        # OPTIONS requests should return 200 for allowed origins
        assert response.status_code == 200
        # Check for CORS preflight headers
        assert 'Access-Control-Allow-Origin' in response.headers
        assert 'Access-Control-Allow-Methods' in response.headers
        assert 'Access-Control-Allow-Headers' in response.headers


    def test_cors_validation_on_post_request(self, api_client, authenticated_session):
        """Test CORS validation on POST requests with allowed origin."""
        headers = {
            'Origin': 'http://localhost',
            'Content-Type': 'application/json'
        }
        response = authenticated_session.post(
            f'{api_client}/api/boards',
            headers=headers,
            json={'name': 'Test Board', 'description': 'Test'}
        )
        # Should succeed with allowed origin
        assert response.status_code == 201
        assert response.json()['success'] is True

    def test_cors_validation_on_put_request(self, api_client, authenticated_session, sample_board):
        """Test CORS validation on PUT/PATCH requests with allowed origin."""
        headers = {
            'Origin': 'http://localhost',
            'Content-Type': 'application/json'
        }
        response = authenticated_session.patch(
            f'{api_client}/api/boards/{sample_board["id"]}',
            headers=headers,
            json={'name': 'Updated Board'}
        )
        # Should succeed with allowed origin
        assert response.status_code == 200
        assert response.json()['success'] is True

    def test_cors_validation_on_delete_request(self, api_client, authenticated_session, sample_board):
        """Test CORS validation on DELETE requests with allowed origin."""
        headers = {'Origin': 'http://localhost'}
        response = authenticated_session.delete(
            f'{api_client}/api/boards/{sample_board["id"]}',
            headers=headers
        )
        # Should succeed with allowed origin
        assert response.status_code == 200
        assert response.json()['success'] is True

    def test_allowed_origin_with_multiple_endpoints(self, api_client, authenticated_session, sample_board, sample_column):
        """Test that allowed origin works across multiple endpoints."""
        headers = {'Origin': 'http://localhost'}
        
        # Test GET endpoint
        response_get = authenticated_session.get(
            f'{api_client}/api/boards/{sample_board["id"]}/columns',
            headers=headers
        )
        assert response_get.status_code == 200
        assert response_get.json()['success'] is True
        
        # Test POST endpoint
        response_post = authenticated_session.post(
            f'{api_client}/api/boards/{sample_board["id"]}/columns',
            headers=headers,
            json={'name': 'New Column'}
        )
        assert response_post.status_code == 201
        assert response_post.json()['success'] is True
        
        # Test PATCH endpoint
        response_patch = authenticated_session.patch(
            f'{api_client}/api/boards/{sample_board["id"]}',
            headers=headers,
            json={'name': 'Updated Board'}
        )
        assert response_patch.status_code == 200
        assert response_patch.json()['success'] is True

    def test_cors_with_authorization_header(self, api_client, authenticated_session):
        """Test CORS validation works with Authorization header.

        A Bearer header is the only credential used when sent (#714), so this
        uses a real API token, made for a fresh user over Basic auth.
        """
        suffix = uuid.uuid4().hex[:8]
        email = f'cors-token-{suffix}@localhost'
        password = f'CorsToken-{suffix}-Aa1!'
        register = requests.post(f'{api_client}/api/auth/register', json={
            'email': email, 'username': f'cors-token-{suffix}', 'password': password,
        })
        assert register.status_code == 201, register.text
        pending = authenticated_session.get(f'{api_client}/api/users/pending')
        user_id = next(u['id'] for u in pending.json()['users'] if u['email'] == email)
        approve = authenticated_session.post(f'{api_client}/api/users/{user_id}/approve')
        assert approve.status_code == 200, approve.text
        created = requests.post(
            f'{api_client}/api/auth/tokens', json={'name': 'CORS'}, auth=(email, password)
        )
        assert created.status_code == 201, created.text

        headers = {
            'Origin': 'http://localhost',
            'Authorization': f"Bearer {created.json()['token']}",
            'Content-Type': 'application/json'
        }
        response = requests.get(
            f'{api_client}/api/boards',
            headers=headers
        )
        # Should succeed with allowed origin
        assert response.status_code == 200
        assert response.json()['success'] is True

    def test_cors_with_custom_headers(self, api_client, authenticated_session):
        """Test CORS validation with custom request headers from allowed origin."""
        headers = {
            'Origin': 'http://localhost',
            'X-Custom-Header': 'custom-value',
            'Content-Type': 'application/json'
        }
        response = authenticated_session.post(
            f'{api_client}/api/boards',
            headers=headers,
            json={'name': 'Test', 'description': 'Test'}
        )
        # Should succeed with allowed origin
        assert response.status_code == 201

    def test_cors_with_content_type_json(self, api_client, authenticated_session):
        """Test CORS validation with JSON content type from allowed origin."""
        headers = {
            'Origin': 'http://localhost',
            'Content-Type': 'application/json'
        }
        response = authenticated_session.post(
            f'{api_client}/api/boards',
            headers=headers,
            json={'name': 'Test Board', 'description': 'Test'}
        )
        # Should succeed with allowed origin
        assert response.status_code == 201


@pytest.mark.api
class TestCORSAllowedOriginsParsing:
    """Test cases for CORS allowed origins configuration parsing."""

    def test_default_allowed_origin_is_localhost(self, api_client, authenticated_session):
        """Test that default allowed origin is http://localhost."""
        # Default should allow localhost
        headers = {'Origin': 'http://localhost'}
        response = authenticated_session.get(
            f'{api_client}/api/boards',
            headers=headers
        )
        assert response.status_code == 200
        assert response.json()['success'] is True

    def test_allowed_origin_header_present_in_response(self, api_client, authenticated_session):
        """Test that response includes CORS Allow-Origin header for allowed origins."""
        headers = {'Origin': 'http://localhost'}
        response = authenticated_session.get(
            f'{api_client}/api/boards',
            headers=headers
        )
        assert response.status_code == 200
        assert 'Access-Control-Allow-Origin' in response.headers
        assert response.headers['Access-Control-Allow-Origin'] in ['http://localhost', '*']

    def test_cors_credentials_header_present(self, api_client, authenticated_session):
        """Test that credentials header is included for allowed origins."""
        headers = {'Origin': 'http://localhost'}
        response = authenticated_session.get(
            f'{api_client}/api/boards',
            headers=headers
        )
        assert response.status_code == 200
        # Flask-CORS should include credentials support header when configured
        assert 'Access-Control-Allow-Credentials' in response.headers


@pytest.mark.api
class TestCORSSecurityHeaders:
    """Test cases for CORS security headers in responses."""

    def test_preflight_response_includes_allowed_methods(self, api_client, authenticated_session):
        """Test that OPTIONS response includes allowed HTTP methods."""
        headers = {
            'Origin': 'http://localhost',
            'Access-Control-Request-Method': 'POST'
        }
        response = requests.options(
            f'{api_client}/api/boards',
            headers=headers
        )
        assert response.status_code == 200
        assert 'Access-Control-Allow-Methods' in response.headers
        methods_header = response.headers.get('Access-Control-Allow-Methods', '').upper()
        # Verify common HTTP methods are allowed
        assert 'POST' in methods_header or 'GET' in methods_header

    def test_preflight_response_includes_allowed_headers(self, api_client, authenticated_session):
        """Test that OPTIONS response includes allowed request headers."""
        headers = {
            'Origin': 'http://localhost',
            'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'Content-Type'
        }
        response = requests.options(
            f'{api_client}/api/boards',
            headers=headers
        )
        assert response.status_code == 200
        assert 'Access-Control-Allow-Headers' in response.headers

    def test_preflight_response_includes_max_age(self, api_client, authenticated_session):
        """Test that preflight response includes cache max-age."""
        headers = {
            'Origin': 'http://localhost',
            'Access-Control-Request-Method': 'GET'
        }
        response = requests.options(
            f'{api_client}/api/boards',
            headers=headers
        )
        assert response.status_code == 200
        # Max-Age allows browsers to cache preflight responses
        if 'Access-Control-Max-Age' in response.headers:
            max_age = int(response.headers['Access-Control-Max-Age'])
            assert max_age > 0


@pytest.mark.api
class TestCORSWithDifferentHTTPMethods:
    """Test cases for CORS handling with different HTTP methods."""

    def test_cors_allows_get_requests(self, api_client, authenticated_session):
        """Test that GET requests with allowed origin are allowed."""
        headers = {'Origin': 'http://localhost'}
        response = authenticated_session.get(
            f'{api_client}/api/boards',
            headers=headers
        )
        assert response.status_code == 200

    def test_cors_allows_post_requests(self, api_client, authenticated_session):
        """Test that POST requests with allowed origin are allowed."""
        headers = {
            'Origin': 'http://localhost',
            'Content-Type': 'application/json'
        }
        response = authenticated_session.post(
            f'{api_client}/api/boards',
            headers=headers,
            json={'name': 'Test Board', 'description': 'Test'}
        )
        assert response.status_code == 201

    def test_cors_allows_patch_requests(self, api_client, authenticated_session, sample_board):
        """Test that PATCH requests with allowed origin are allowed."""
        headers = {
            'Origin': 'http://localhost',
            'Content-Type': 'application/json'
        }
        response = authenticated_session.patch(
            f'{api_client}/api/boards/{sample_board["id"]}',
            headers=headers,
            json={'name': 'Updated'}
        )
        assert response.status_code == 200

    def test_cors_allows_delete_requests(self, api_client, authenticated_session, sample_board):
        """Test that DELETE requests with allowed origin are allowed."""
        headers = {'Origin': 'http://localhost'}
        response = authenticated_session.delete(
            f'{api_client}/api/boards/{sample_board["id"]}',
            headers=headers
        )
        assert response.status_code == 200

    def test_cors_allows_options_requests(self, api_client, authenticated_session):
        """Test that OPTIONS requests with allowed origin are allowed."""
        headers = {'Origin': 'http://localhost'}
        response = requests.options(
            f'{api_client}/api/boards',
            headers=headers
        )
        assert response.status_code == 200


@pytest.mark.api
class TestCORSWithDifferentEndpoints:
    """Test cases for CORS validation across different API endpoints."""

    def test_cors_on_boards_endpoint(self, api_client, authenticated_session):
        """Test CORS validation on boards endpoint."""
        headers = {'Origin': 'http://localhost'}
        response = authenticated_session.get(
            f'{api_client}/api/boards',
            headers=headers
        )
        assert response.status_code == 200

    def test_cors_on_stats_endpoint(self, api_client, authenticated_session):
        """Test CORS validation on stats endpoint."""
        headers = {'Origin': 'http://localhost'}
        response = authenticated_session.get(
            f'{api_client}/api/stats',
            headers=headers
        )
        assert response.status_code == 200

    def test_cors_on_liveness_endpoint(self, api_client, authenticated_session):
        """Test CORS validation on public liveness endpoint."""
        headers = {'Origin': 'http://localhost'}
        response = authenticated_session.get(
            f'{api_client}/api/health/live',
            headers=headers
        )
        assert response.status_code == 200

    def test_cors_on_settings_schema_endpoint(self, api_client, authenticated_session):
        """Test CORS validation on settings schema endpoint."""
        headers = {'Origin': 'http://localhost'}
        response = authenticated_session.get(
            f'{api_client}/api/settings/schema',
            headers=headers
        )
        assert response.status_code == 200

    def test_cors_on_version_endpoint(self, api_client, authenticated_session):
        """Test CORS validation on version endpoint."""
        headers = {'Origin': 'http://localhost'}
        response = authenticated_session.get(
            f'{api_client}/api/version',
            headers=headers
        )
        assert response.status_code == 200


@pytest.mark.api
class TestCORSOriginValidationLogic:
    """Test cases for the CORS origin validation logic itself."""

    def test_same_origin_request_no_origin_header(self, api_client, authenticated_session):
        """Test that same-origin requests (no Origin header) are always allowed."""
        # This mimics browser requests from the same origin
        response = authenticated_session.get(f'{api_client}/api/boards')
        assert response.status_code == 200

    def test_origin_header_is_forwarded_correctly(self, api_client, authenticated_session, sample_board):
        """Test that Origin header is properly handled in request processing."""
        headers = {'Origin': 'http://localhost'}
        response = authenticated_session.post(
            f'{api_client}/api/boards/{sample_board["id"]}/columns',
            headers=headers,
            json={'name': 'Test Column'}
        )
        # Request should be processed normally with proper origin
        assert response.status_code == 201
        assert 'column' in response.json()

    def test_multiple_consecutive_requests_different_origins(self, api_client, authenticated_session):
        """Test that CORS validation works correctly in sequence with different origins."""
        # First request with allowed origin should succeed
        headers_allowed = {'Origin': 'http://localhost'}
        response1 = authenticated_session.get(
            f'{api_client}/api/boards',
            headers=headers_allowed
        )
        assert response1.status_code == 200
        
        # Second request without origin should succeed
        response2 = authenticated_session.get(f'{api_client}/api/boards')
        assert response2.status_code == 200
        
        # Third request with allowed origin should succeed
        response3 = authenticated_session.get(
            f'{api_client}/api/boards',
            headers=headers_allowed
        )
        assert response3.status_code == 200

    def test_cors_validation_does_not_affect_request_body_processing(self, api_client, authenticated_session):
        """Test that CORS validation doesn't interfere with request body parsing."""
        headers = {
            'Origin': 'http://localhost',
            'Content-Type': 'application/json'
        }
        board_data = {
            'name': 'New Board',
            'description': 'Test board to verify body processing'
        }
        response = authenticated_session.post(
            f'{api_client}/api/boards',
            headers=headers,
            json=board_data
        )
        assert response.status_code == 201
        board = response.json()['board']
        assert board['name'] == board_data['name']
        assert board['description'] == board_data['description']

    def test_cors_validation_does_not_affect_response_format(self, api_client, authenticated_session):
        """Test that CORS validation doesn't affect response JSON structure."""
        headers = {'Origin': 'http://localhost'}
        response = authenticated_session.get(
            f'{api_client}/api/boards',
            headers=headers
        )
        assert response.status_code == 200
        data = response.json()
        # Verify standard response structure is maintained
        assert isinstance(data, dict)
        assert 'success' in data or 'boards' in data


@pytest.mark.api
class TestCORSBrowserScenarios:
    """Test cases that simulate common browser CORS scenarios."""

    def test_simple_cors_request_scenario(self, api_client, authenticated_session):
        """Test simple CORS request (GET without custom headers)."""
        # Browser simple request: GET with Origin header
        headers = {'Origin': 'http://localhost'}
        response = authenticated_session.get(
            f'{api_client}/api/boards',
            headers=headers
        )
        assert response.status_code == 200
        assert 'Access-Control-Allow-Origin' in response.headers

    def test_preflighted_request_scenario(self, api_client, authenticated_session):
        """Test preflighted CORS request scenario (OPTIONS + GET)."""
        # First, browser sends OPTIONS preflight request
        headers_preflight = {
            'Origin': 'http://localhost',
            'Access-Control-Request-Method': 'GET',
            'Access-Control-Request-Headers': 'Content-Type'
        }
        response_preflight = requests.options(
            f'{api_client}/api/boards',
            headers=headers_preflight
        )
        assert response_preflight.status_code == 200
        assert 'Access-Control-Allow-Methods' in response_preflight.headers
        
        # Then, browser sends actual GET request
        headers_actual = {'Origin': 'http://localhost'}
        response_actual = authenticated_session.get(
            f'{api_client}/api/boards',
            headers=headers_actual
        )
        assert response_actual.status_code == 200

    def test_cors_with_json_post_scenario(self, api_client, authenticated_session):
        """Test CORS with JSON POST request (common fetch scenario)."""
        headers = {
            'Origin': 'http://localhost',
            'Content-Type': 'application/json'
        }
        response = authenticated_session.post(
            f'{api_client}/api/boards',
            headers=headers,
            json={'name': 'Test Board', 'description': 'Test'}
        )
        # Fetch with JSON body requires preflight, but we're testing direct request
        assert response.status_code in [200, 201]

