"""Tests for sharing a board from the board (#285)."""
import uuid

import pytest
import requests


def _me(api_client, session):
    response = session.get(f'{api_client}/api/auth/me')
    assert response.status_code == 200
    return response.json()['user']


def _new_user_session(api_client, admin_session):
    """Register, approve and sign in a fresh user. Returns (session, user)."""
    session = requests.Session()
    suffix = uuid.uuid4().hex[:8]
    password = f"Share-{uuid.uuid4().hex[:12]}-Aa1!"
    email = f"share-user-{suffix}@localhost"
    register = session.post(f'{api_client}/api/auth/register', json={
        'email': email,
        'username': f'share-user-{suffix}',
        'password': password,
        'display_name': f'Share User {suffix}',
    })
    assert register.status_code == 201, register.text
    body = register.json()
    user_id = body.get('user', {}).get('id') or body.get('data', {}).get('user', {}).get('id')
    approve = admin_session.post(f'{api_client}/api/users/{user_id}/approve')
    assert approve.status_code == 200, approve.text
    login = session.post(f'{api_client}/api/auth/login', json={'email': email, 'password': password})
    assert login.status_code == 200, login.text
    return session, _me(api_client, session)


@pytest.fixture
def third_user(api_client, test_admin_session):
    session, user = _new_user_session(api_client, test_admin_session)
    yield session, user
    try:
        session.delete(f'{api_client}/api/notifications/delete-all')
    except requests.exceptions.RequestException:
        pass


@pytest.fixture
def owned_board(api_client, second_user_session):
    """A board owned by a non-admin user (user B), with one column."""
    response = second_user_session.post(
        f'{api_client}/api/boards',
        json={'name': f'Shared Board {uuid.uuid4().hex[:6]}', 'description': 'Owned by B'},
    )
    assert response.status_code == 201, response.text
    board = response.json()['board']
    column = second_user_session.post(
        f'{api_client}/api/boards/{board["id"]}/columns', json={'name': 'To Do'}
    )
    assert column.status_code == 201, column.text
    board['column_id'] = column.json()['column']['id']
    return board


def _share(api_client, session, board_id, user_id, access):
    return session.put(
        f'{api_client}/api/boards/{board_id}/members/{user_id}', json={'access': access}
    )


def _members(api_client, session, board_id, include_candidates=False):
    suffix = '?include_candidates=true' if include_candidates else ''
    return session.get(f'{api_client}/api/boards/{board_id}/members{suffix}')


@pytest.mark.api
class TestBoardSharing:
    """Owners and administrators share boards as Viewer or Editor."""

    def test_owner_shares_as_viewer(self, api_client, second_user_session, owned_board, third_user):
        c_session, c_user = third_user
        owner = _me(api_client, second_user_session)

        before = c_session.get(f'{api_client}/api/boards/{owned_board["id"]}/cards')
        assert before.status_code == 403

        response = _share(api_client, second_user_session, owned_board['id'], c_user['id'], 'viewer')
        assert response.status_code == 200, response.text
        data = response.json()
        assert data['owner']['id'] == owner['id']
        assert [(m['user']['id'], m['access']) for m in data['members']] == [(c_user['id'], 'viewer')]
        assert c_user['id'] not in [u['id'] for u in data['available_users']]
        assert owner['id'] not in [u['id'] for u in data['available_users']]

        assert c_session.get(f'{api_client}/api/boards/{owned_board["id"]}/cards').status_code == 200
        create = c_session.post(
            f'{api_client}/api/columns/{owned_board["column_id"]}/cards', json={'title': 'Nope'}
        )
        assert create.status_code == 403

        notifications = c_session.get(f'{api_client}/api/notifications').json()['notifications']
        shared = [n for n in notifications if n.get('action_url') == f'/board.html?id={owned_board["id"]}']
        assert len(shared) == 1
        assert 'shared a board with you' in shared[0]['subject']

    def test_shared_board_appears_in_board_list(self, api_client, second_user_session, owned_board, third_user):
        c_session, c_user = third_user
        assert _share(api_client, second_user_session, owned_board['id'], c_user['id'], 'viewer').status_code == 200
        boards = c_session.get(f'{api_client}/api/boards').json()['boards']
        listed = [b for b in boards if b['id'] == owned_board['id']]
        assert len(listed) == 1
        assert listed[0]['can_delete'] is False
        assert listed[0]['can_edit'] is False

    def test_editor_can_edit_but_not_delete_or_share(
        self, api_client, authenticated_session, second_user_session, owned_board, third_user
    ):
        c_session, c_user = third_user
        admin = _me(api_client, authenticated_session)
        assert _share(api_client, second_user_session, owned_board['id'], c_user['id'], 'viewer').status_code == 200
        changed = _share(api_client, second_user_session, owned_board['id'], c_user['id'], 'editor')
        assert changed.status_code == 200
        assert [m['access'] for m in changed.json()['members']] == ['editor']

        # Changing access doesn't notify again.
        notifications = c_session.get(f'{api_client}/api/notifications').json()['notifications']
        shared = [n for n in notifications if n.get('action_url') == f'/board.html?id={owned_board["id"]}']
        assert len(shared) == 1

        create = c_session.post(
            f'{api_client}/api/columns/{owned_board["column_id"]}/cards', json={'title': 'Editor card'}
        )
        assert create.status_code == 201

        boards = c_session.get(f'{api_client}/api/boards').json()['boards']
        listed = [b for b in boards if b['id'] == owned_board['id']][0]
        assert listed['can_edit'] is True
        assert listed['can_delete'] is False

        assert c_session.delete(f'{api_client}/api/boards/{owned_board["id"]}').status_code == 403
        assert _share(api_client, c_session, owned_board['id'], admin['id'], 'viewer').status_code == 403
        assert c_session.delete(
            f'{api_client}/api/boards/{owned_board["id"]}/members/{c_user["id"]}'
        ).status_code in (400, 403)

    def test_members_visible_to_anyone_who_can_view(self, api_client, second_user_session, owned_board, third_user):
        c_session, c_user = third_user
        owner = _me(api_client, second_user_session)
        assert _share(api_client, second_user_session, owned_board['id'], c_user['id'], 'viewer').status_code == 200

        response = _members(api_client, c_session, owned_board['id'], include_candidates=True)
        assert response.status_code == 200
        data = response.json()
        assert data['can_share'] is False
        assert 'available_users' not in data
        assert data['owner']['id'] == owner['id']
        assert [m['user']['id'] for m in data['members']] == [c_user['id']]
        assert 'email' not in data['owner']

    def test_members_forbidden_without_access(self, api_client, owned_board, third_user):
        c_session, _ = third_user
        assert _members(api_client, c_session, owned_board['id']).status_code == 403

    def test_remove_access_unassigns_cards(self, api_client, second_user_session, owned_board, third_user):
        c_session, c_user = third_user
        owner = _me(api_client, second_user_session)
        assert _share(api_client, second_user_session, owned_board['id'], c_user['id'], 'editor').status_code == 200

        card_ids = []
        for title in ('Primary', 'Secondary'):
            card = second_user_session.post(
                f'{api_client}/api/columns/{owned_board["column_id"]}/cards', json={'title': title}
            )
            assert card.status_code == 201
            card_ids.append(card.json()['card']['id'])

        primary = second_user_session.put(
            f'{api_client}/api/cards/{card_ids[0]}/assignees',
            json={'assigned_to_id': c_user['id'], 'secondary_assignee_ids': []},
        )
        assert primary.status_code == 200, primary.text
        secondary = second_user_session.put(
            f'{api_client}/api/cards/{card_ids[1]}/assignees',
            json={'assigned_to_id': owner['id'], 'secondary_assignee_ids': [c_user['id']]},
        )
        assert secondary.status_code == 200, secondary.text

        removed = second_user_session.delete(
            f'{api_client}/api/boards/{owned_board["id"]}/members/{c_user["id"]}'
        )
        assert removed.status_code == 200, removed.text
        assert removed.json()['members'] == []
        assert removed.json()['cards_unassigned'] == 2

        assert c_session.get(f'{api_client}/api/boards/{owned_board["id"]}/cards').status_code == 403

        first = second_user_session.get(f'{api_client}/api/cards/{card_ids[0]}/assignees').json()
        assert first['primary_assignee'] is None
        second = second_user_session.get(f'{api_client}/api/cards/{card_ids[1]}/assignees').json()
        assert second['primary_assignee']['id'] == owner['id']
        assert second['secondary_assignees'] == []

    def test_remove_unshared_user_is_404(self, api_client, second_user_session, owned_board, third_user):
        _, c_user = third_user
        response = second_user_session.delete(
            f'{api_client}/api/boards/{owned_board["id"]}/members/{c_user["id"]}'
        )
        assert response.status_code == 404

    @pytest.mark.parametrize('access', ['owner', 'admin', '', None, 1, ['editor']])
    def test_invalid_access_rejected(self, api_client, second_user_session, owned_board, third_user, access):
        _, c_user = third_user
        response = _share(api_client, second_user_session, owned_board['id'], c_user['id'], access)
        assert response.status_code == 400

    def test_cannot_share_with_self_or_unknown_user(self, api_client, second_user_session, owned_board):
        owner = _me(api_client, second_user_session)
        assert _share(api_client, second_user_session, owned_board['id'], owner['id'], 'viewer').status_code == 400
        assert _share(api_client, second_user_session, owned_board['id'], 999999999, 'viewer').status_code == 404

    def test_admin_can_share_and_owner_cannot_be_changed(
        self, api_client, authenticated_session, second_user_session, owned_board, third_user
    ):
        _, c_user = third_user
        owner = _me(api_client, second_user_session)
        shared = _share(api_client, authenticated_session, owned_board['id'], c_user['id'], 'viewer')
        assert shared.status_code == 200
        assert shared.json()['can_share'] is True

        assert _share(api_client, authenticated_session, owned_board['id'], owner['id'], 'viewer').status_code == 400
        assert authenticated_session.delete(
            f'{api_client}/api/boards/{owned_board["id"]}/members/{owner["id"]}'
        ).status_code == 400

    def test_no_access_user_cannot_share(self, api_client, owned_board, third_user, authenticated_session):
        c_session, _ = third_user
        admin = _me(api_client, authenticated_session)
        assert _share(api_client, c_session, owned_board['id'], admin['id'], 'viewer').status_code == 403


@pytest.mark.api
class TestReassignKeepsPreviousOwner:
    """Handing a board over keeps the previous owner as an editor unless told not to."""

    def test_previous_owner_kept_as_editor_by_default(self, api_client, second_user_session, owned_board, third_user):
        c_session, c_user = third_user
        previous = _me(api_client, second_user_session)
        assert _share(api_client, second_user_session, owned_board['id'], c_user['id'], 'viewer').status_code == 200

        response = second_user_session.put(
            f'{api_client}/api/boards/{owned_board["id"]}/owner', json={'owner_id': c_user['id']}
        )
        assert response.status_code == 200, response.text

        members = _members(api_client, c_session, owned_board['id']).json()
        assert members['owner']['id'] == c_user['id']
        assert members['can_share'] is True
        # The new owner's old share is dropped; the previous owner is an editor.
        assert [(m['user']['id'], m['access']) for m in members['members']] == [(previous['id'], 'editor')]

        assert second_user_session.get(f'{api_client}/api/boards/{owned_board["id"]}/cards').status_code == 200
        assert second_user_session.delete(f'{api_client}/api/boards/{owned_board["id"]}').status_code == 403

    def test_previous_owner_can_be_removed(self, api_client, second_user_session, owned_board, third_user):
        c_session, c_user = third_user
        previous = _me(api_client, second_user_session)
        card = second_user_session.post(
            f'{api_client}/api/columns/{owned_board["column_id"]}/cards', json={'title': 'Mine'}
        )
        assert card.status_code == 201
        card_id = card.json()['card']['id']
        assigned = second_user_session.put(
            f'{api_client}/api/cards/{card_id}/assignees',
            json={'assigned_to_id': previous['id'], 'secondary_assignee_ids': []},
        )
        assert assigned.status_code == 200

        response = second_user_session.put(
            f'{api_client}/api/boards/{owned_board["id"]}/owner',
            json={'owner_id': c_user['id'], 'keep_previous_owner': False},
        )
        assert response.status_code == 200, response.text
        assert second_user_session.get(f'{api_client}/api/boards/{owned_board["id"]}/cards').status_code == 403

        members = _members(api_client, c_session, owned_board['id']).json()
        assert members['members'] == []
        assignees = c_session.get(f'{api_client}/api/cards/{card_id}/assignees').json()
        assert assignees['primary_assignee'] is None

    def test_keep_previous_owner_must_be_boolean(self, api_client, second_user_session, owned_board, third_user):
        _, c_user = third_user
        response = second_user_session.put(
            f'{api_client}/api/boards/{owned_board["id"]}/owner',
            json={'owner_id': c_user['id'], 'keep_previous_owner': 'no'},
        )
        assert response.status_code == 400


@pytest.mark.api
class TestCanDeleteFlag:
    """The board menu shows Delete Board from can_delete in the owner data."""

    def test_can_delete_by_access(self, api_client, authenticated_session, second_user_session, owned_board, third_user):
        c_session, c_user = third_user
        url = f'{api_client}/api/boards/{owned_board["id"]}/owner'

        assert second_user_session.get(url).json()['can_delete'] is True
        assert authenticated_session.get(url).json()['can_delete'] is True

        assert _share(api_client, second_user_session, owned_board['id'], c_user['id'], 'editor').status_code == 200
        assert c_session.get(url).json()['can_delete'] is False
        cards = c_session.get(f'{api_client}/api/boards/{owned_board["id"]}/cards')
        assert cards.status_code == 200
        assert cards.json()['board']['can_delete'] is False

        assert _share(api_client, second_user_session, owned_board['id'], c_user['id'], 'viewer').status_code == 200
        assert c_session.get(url).json()['can_delete'] is False
