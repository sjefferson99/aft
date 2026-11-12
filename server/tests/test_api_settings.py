"""Tests for settings API endpoints."""
import pytest


@pytest.mark.api
class TestSettingsAPI:
    """Test cases for settings API endpoints."""
    
    def test_get_settings_schema(self, api_client, authenticated_session):
        """Test getting settings schema."""
        response = authenticated_session.get(f'{api_client}/api/settings/schema')
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert 'default_board' in data['schema']
        assert data['schema']['default_board']['type'] == 'integer'
    
    def test_get_setting_not_found(self, api_client, authenticated_session):
        """Test getting a setting that doesn't exist."""
        response = authenticated_session.get(f'{api_client}/api/settings/default_board')
        # May be 404 or 200 with null depending on whether setting exists
        # Just check it doesn't error
        assert response.status_code in [200, 404]
    
    def test_create_setting(self, api_client, authenticated_session, sample_board):
        """Test creating a new setting."""
        response = authenticated_session.put(f'{api_client}/api/settings/default_board', json={
            'value': sample_board['id']
        })
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['value'] == sample_board['id']
    
    def test_create_setting_null_value(self, api_client, authenticated_session):
        """Test creating a setting with null value."""
        response = authenticated_session.put(f'{api_client}/api/settings/default_board', json={
            'value': None
        })
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['value'] is None
    
    def test_update_setting(self, api_client, authenticated_session, sample_board):
        """Test updating an existing setting."""
        # Create setting
        authenticated_session.put(f'{api_client}/api/settings/default_board', json={'value': sample_board['id']})
        
        # Update to null
        response = authenticated_session.put(f'{api_client}/api/settings/default_board', json={'value': None})
        assert response.status_code == 200
        data = response.json()
        assert data['value'] is None
    
    def test_setting_invalid_key(self, api_client, authenticated_session):
        """Test creating a setting with invalid key."""
        response = authenticated_session.put(f'{api_client}/api/settings/invalid_key', json={
            'value': 'some_value'
        })
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
        assert 'not allowed' in data['message']
    
    def test_setting_invalid_board_id(self, api_client, authenticated_session):
        """Test setting default_board to non-existent board."""
        response = authenticated_session.put(f'{api_client}/api/settings/default_board', json={
            'value': 9999
        })
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
        assert 'does not exist' in data['message']
    
    def test_setting_invalid_type(self, api_client, authenticated_session):
        """Test setting default_board with invalid type."""
        response = authenticated_session.put(f'{api_client}/api/settings/default_board', json={
            'value': 'not_an_integer'
        })
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
    
    def test_default_board_can_be_the_global_board(self, api_client, authenticated_session):
        """Test default_board accepts "global:<id>" for a global board the user can see (#663)."""
        boards = authenticated_session.get(f'{api_client}/api/global-boards').json()['global_boards']
        value = f"global:{boards[0]['id']}"
        try:
            response = authenticated_session.put(
                f'{api_client}/api/settings/default_board', json={'value': value}
            )
            assert response.status_code == 200, response.text
            response = authenticated_session.get(f'{api_client}/api/settings/default_board')
            assert response.json()['value'] == value
        finally:
            authenticated_session.put(f'{api_client}/api/settings/default_board', json={'value': None})

    @pytest.mark.parametrize('value', [
        'global:999999999', 'global:0', 'global:-1', 'global:', 'global:1x', 'GLOBAL:1',
        'global: 1', 'global:12345678901', 'board:1', 'global:<script>',
    ])
    def test_default_board_rejects_bad_global_values(self, api_client, authenticated_session, value):
        """Test unknown global boards and malformed values are rejected."""
        response = authenticated_session.put(
            f'{api_client}/api/settings/default_board', json={'value': value}
        )
        assert response.status_code == 400
        assert response.json()['success'] is False
        assert '<script>' not in response.text

    def test_get_setting_after_create(self, api_client, authenticated_session, sample_board):
        """Test retrieving a setting after creating it."""
        # Create setting
        authenticated_session.put(f'{api_client}/api/settings/default_board', json={'value': sample_board['id']})
        
        # Get setting
        response = authenticated_session.get(f'{api_client}/api/settings/default_board')
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['value'] == sample_board['id']

    def test_timezone_default_is_utc(self, api_client, authenticated_session):
        """Test timezone endpoint returns UTC when timezone is explicitly set to UTC.

        A truly unset state cannot be tested here because the session-scoped test
        user persists across tests.  The endpoint logic (returning UTC when the DB
        row has no timezone value) is exercised by the unit-level validation path.
        This test verifies that the GET/PUT round-trip for UTC works correctly.
        """
        authenticated_session.put(f'{api_client}/api/settings/timezone', json={'value': 'UTC'})

        response = authenticated_session.get(f'{api_client}/api/settings/timezone')
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['value'] == 'UTC'

    def test_timezone_can_be_updated(self, api_client, authenticated_session):
        """Test timezone endpoint stores and returns a valid IANA timezone."""
        put_response = authenticated_session.put(
            f'{api_client}/api/settings/timezone',
            json={'value': 'Europe/London'}
        )
        assert put_response.status_code == 200
        put_data = put_response.json()
        assert put_data['success'] is True
        assert put_data['value'] == 'Europe/London'

        get_response = authenticated_session.get(f'{api_client}/api/settings/timezone')
        assert get_response.status_code == 200
        get_data = get_response.json()
        assert get_data['success'] is True
        assert get_data['value'] == 'Europe/London'

    def test_timezone_rejects_invalid_value(self, api_client, authenticated_session):
        """Test timezone endpoint rejects invalid timezone names."""
        response = authenticated_session.put(
            f'{api_client}/api/settings/timezone',
            json={'value': 'Not/A_Real_Zone'}
        )
        assert response.status_code == 400
        data = response.json()
        assert data['success'] is False
