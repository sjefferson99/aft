"""Tests that personal settings stay separate between users, admins included."""
import pytest


def _set_value(session, url, value):
    response = session.put(url, json={'value': value})
    assert response.status_code == 200, response.text


def _get_value(session, url):
    response = session.get(url)
    assert response.status_code == 200, response.text
    return response.json()['value']


@pytest.fixture
def second_admin_session(api_client, test_admin_session, second_user_session):
    """Give the second user the administrator role for one test."""
    user_id = second_user_session.get(f'{api_client}/api/auth/me').json()['user']['id']
    response = test_admin_session.post(
        f'{api_client}/api/users/{user_id}/roles', json={'role_name': 'administrator'}
    )
    assert response.status_code == 200, response.text

    yield second_user_session

    roles = test_admin_session.get(f'{api_client}/api/roles').json()['roles']
    admin_role = next(role for role in roles if role['name'] == 'administrator')
    test_admin_session.delete(f"{api_client}/api/users/{user_id}/roles/{admin_role['id']}")


@pytest.mark.api
class TestSettingsUserIsolation:
    """Test one user's preference never reaches another user."""

    # Each order is tried because the old unscoped query returned whichever row came first
    @pytest.mark.parametrize('path, first, second', [
        ('touchscreen_mode', True, False),
        ('touchscreen_mode', False, True),
        ('time_format', '12', '24'),
        ('time_format', '24', '12'),
        ('working-style', 'agile', 'kanban'),
        ('working-style', 'kanban', 'agile'),
    ])
    def test_admins_keep_their_own_value(
        self, api_client, test_admin_session, second_admin_session, path, first, second
    ):
        """Test two admins can hold different values for the same setting."""
        url = f'{api_client}/api/settings/{path}'
        original = _get_value(test_admin_session, url)

        try:
            _set_value(test_admin_session, url, first)
            _set_value(second_admin_session, url, second)

            assert _get_value(test_admin_session, url) == first
            assert _get_value(second_admin_session, url) == second
        finally:
            _set_value(test_admin_session, url, original)

    def test_admin_can_turn_off_mode_another_admin_has_on(
        self, api_client, test_admin_session, second_admin_session
    ):
        """Test turning the mode off isn't undone by another admin having it on."""
        url = f'{api_client}/api/settings/touchscreen_mode'
        _set_value(test_admin_session, url, False)
        _set_value(second_admin_session, url, False)

        try:
            for owner, other in (
                (test_admin_session, second_admin_session),
                (second_admin_session, test_admin_session),
            ):
                _set_value(owner, url, True)
                assert _get_value(other, url) is False
                _set_value(other, url, False)
                assert _get_value(other, url) is False
                _set_value(owner, url, False)
        finally:
            _set_value(test_admin_session, url, False)

    def test_regular_user_keeps_their_own_value(
        self, api_client, test_admin_session, second_user_session
    ):
        """Test an admin's value doesn't reach a regular user, or the reverse."""
        url = f'{api_client}/api/settings/touchscreen_mode'

        try:
            _set_value(test_admin_session, url, True)
            _set_value(second_user_session, url, False)

            assert _get_value(test_admin_session, url) is True
            assert _get_value(second_user_session, url) is False
        finally:
            _set_value(test_admin_session, url, False)

    def test_admins_keep_their_own_theme(
        self, api_client, test_admin_session, second_admin_session
    ):
        """Test selecting a theme doesn't overwrite another admin's selection."""
        url = f'{api_client}/api/settings/theme'
        themes = test_admin_session.get(f'{api_client}/api/themes').json()
        first_id, second_id = themes[0]['id'], themes[1]['id']
        original_id = test_admin_session.get(url).json()['id']

        try:
            for admin_theme, other_theme in ((first_id, second_id), (second_id, first_id)):
                assert test_admin_session.put(url, json={'theme_id': admin_theme}).status_code == 200
                assert second_admin_session.put(url, json={'theme_id': other_theme}).status_code == 200

                assert test_admin_session.get(url).json()['id'] == admin_theme
                assert second_admin_session.get(url).json()['id'] == other_theme
        finally:
            test_admin_session.put(url, json={'theme_id': original_id})

    def test_admin_default_board_is_their_own(
        self, api_client, test_admin_session, second_admin_session
    ):
        """Test another admin's default board isn't returned or reset."""
        url = f'{api_client}/api/settings/default_board'
        board = second_admin_session.post(
            f'{api_client}/api/boards', json={'name': 'Second admin default'}
        ).json()['board']
        original = _get_value(test_admin_session, url)

        try:
            _set_value(test_admin_session, url, None)
            _set_value(second_admin_session, url, board['id'])

            assert _get_value(test_admin_session, url) is None
            assert _get_value(second_admin_session, url) == board['id']
        finally:
            _set_value(test_admin_session, url, original)
