"""Tests for the card actions user setting."""
import pytest
import requests


URL = '/api/settings/card_actions'


@pytest.mark.api
class TestCardActionsSetting:
    """Test the card_actions setting through the settings API."""

    @pytest.fixture(autouse=True)
    def reset_setting(self, api_client, authenticated_session):
        yield
        authenticated_session.put(f'{api_client}{URL}', json={'value': None})

    @pytest.mark.parametrize('value', [
        {'desktop': ['done', 'archive', 'delete'], 'mobile': ['done', 'move']},
        {'desktop': ['move'], 'mobile': []},
        {'desktop': ['top', 'move'], 'mobile': ['top']},
        None,
    ])
    def test_set_and_get(self, api_client, authenticated_session, value):
        """Test the setting saves and reads back unchanged."""
        response = authenticated_session.put(f'{api_client}{URL}', json={'value': value})
        assert response.status_code == 200

        response = authenticated_session.get(f'{api_client}{URL}')
        assert response.status_code == 200
        assert response.json()['value'] == value

    @pytest.mark.parametrize('value', [
        'done',
        ['done'],
        {},
        {'desktop': ['done']},
        {'desktop': [], 'mobile': [], 'tablet': []},
        {'desktop': 'done', 'mobile': []},
        {'desktop': ['done', 'archive', 'move', 'delete'], 'mobile': []},
        {'desktop': ['done', 'done'], 'mobile': []},
        {'desktop': ['unarchive'], 'mobile': []},
        {'desktop': [1], 'mobile': []},
        {'desktop': [['done']], 'mobile': []},
        {'desktop': ['<script>alert(1)</script>'], 'mobile': []},
    ])
    def test_rejects_invalid_values(self, api_client, authenticated_session, value):
        """Test anything but known, unique actions within the limit is rejected."""
        response = authenticated_session.put(f'{api_client}{URL}', json={'value': value})
        assert response.status_code == 400
        assert response.json()['success'] is False

    def test_requires_authentication(self, api_client):
        """Test the setting cannot be read without a session."""
        response = requests.get(f'{api_client}{URL}', timeout=5)
        assert response.status_code == 401
