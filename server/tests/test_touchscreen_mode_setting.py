"""Tests for the touchscreen mode user setting."""
import pytest
import requests


@pytest.mark.api
class TestTouchscreenModeSetting:
    """Test the touchscreen_mode setting through the settings API."""

    @pytest.fixture(autouse=True)
    def reset_setting(self, api_client, authenticated_session):
        yield
        authenticated_session.put(
            f'{api_client}/api/settings/touchscreen_mode', json={'value': False}
        )

    @pytest.mark.parametrize('value', [True, False])
    def test_set_and_get(self, api_client, authenticated_session, value):
        """Test the setting saves and reads back as a boolean."""
        response = authenticated_session.put(
            f'{api_client}/api/settings/touchscreen_mode', json={'value': value}
        )
        assert response.status_code == 200

        response = authenticated_session.get(f'{api_client}/api/settings/touchscreen_mode')
        assert response.status_code == 200
        assert response.json()['value'] is value

    @pytest.mark.parametrize('value', ['true', 1, None, []])
    def test_rejects_non_boolean(self, api_client, authenticated_session, value):
        """Test non-boolean values are rejected."""
        response = authenticated_session.put(
            f'{api_client}/api/settings/touchscreen_mode', json={'value': value}
        )
        assert response.status_code == 400
        assert response.json()['success'] is False

    def test_appears_in_schema(self, api_client, authenticated_session):
        """Test the setting is listed in the settings schema."""
        response = authenticated_session.get(f'{api_client}/api/settings/schema')
        assert response.status_code == 200
        assert 'touchscreen_mode' in response.text

    def test_requires_authentication(self, api_client):
        """Test the setting cannot be read without a session."""
        response = requests.get(f'{api_client}/api/settings/touchscreen_mode', timeout=5)
        assert response.status_code == 401
