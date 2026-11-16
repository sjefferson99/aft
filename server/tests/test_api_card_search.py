"""Tests for searching cards across boards (#593): GET /api/search/cards."""
import uuid
from datetime import datetime, timedelta

import pytest
import requests


SEARCH_URL = '/api/search/cards'


def _token():
    """A word unique to this test, so leftovers from other tests never match."""
    return f'srch{uuid.uuid4().hex[:10]}'


def _create_board(api_client, session, name):
    response = session.post(f'{api_client}/api/boards', json={'name': name})
    assert response.status_code == 201, response.text
    board = response.json()['board']
    column = session.post(f'{api_client}/api/boards/{board["id"]}/columns', json={'name': 'To Do'})
    assert column.status_code == 201, column.text
    board['column_id'] = column.json()['column']['id']
    return board


def _create_card(api_client, session, column_id, title, description=''):
    response = session.post(
        f'{api_client}/api/columns/{column_id}/cards',
        json={'title': title, 'description': description},
    )
    assert response.status_code == 201, response.text
    return response.json()['card']


def _search(api_client, session, **params):
    return session.get(f'{api_client}{SEARCH_URL}', params=params)


def _card_views(data):
    """Map card id -> (board id, view) from a search response."""
    found = {}
    for board in data['boards']:
        for view in board['views']:
            for card in view['cards']:
                found[card['id']] = (board['id'], view['view'])
    return found


def _new_user_session(api_client, admin_session):
    """Register, approve and sign in a fresh user. Returns (session, user)."""
    session = requests.Session()
    suffix = uuid.uuid4().hex[:8]
    password = f"Search-{uuid.uuid4().hex[:12]}-Aa1!"
    email = f'search-user-{suffix}@localhost'
    register = session.post(f'{api_client}/api/auth/register', json={
        'email': email,
        'username': f'search-user-{suffix}',
        'password': password,
        'display_name': f'Search User {suffix}',
    })
    assert register.status_code == 201, register.text
    body = register.json()
    user_id = body.get('user', {}).get('id') or body.get('data', {}).get('user', {}).get('id')
    approve = admin_session.post(f'{api_client}/api/users/{user_id}/approve')
    assert approve.status_code == 200, approve.text
    login = session.post(f'{api_client}/api/auth/login', json={'email': email, 'password': password})
    assert login.status_code == 200, login.text
    me = session.get(f'{api_client}/api/auth/me')
    assert me.status_code == 200, me.text
    return session, me.json()['user']


@pytest.mark.api
class TestCardSearchAcrossBoards:
    """Searching every accessible board, grouped by board and view."""

    def test_requires_authentication(self, api_client):
        response = requests.get(f'{api_client}{SEARCH_URL}', params={'q': 'anything'})
        assert response.status_code == 401

    def test_finds_cards_on_several_boards_grouped_by_board(self, api_client, authenticated_session):
        token = _token()
        board_a = _create_board(api_client, authenticated_session, f'Alpha {token}')
        board_b = _create_board(api_client, authenticated_session, f'Beta {token}')
        card_a = _create_card(api_client, authenticated_session, board_a['column_id'], f'{token} on A')
        card_b = _create_card(
            api_client, authenticated_session, board_b['column_id'], 'Other title', f'mentions {token}'
        )
        _create_card(api_client, authenticated_session, board_b['column_id'], 'Unrelated card')

        response = _search(api_client, authenticated_session, q=token)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data['success'] is True
        assert data['total'] == 2
        assert data['returned'] == 2
        assert data['truncated'] is False
        assert [board['id'] for board in data['boards']] == [board_a['id'], board_b['id']]

        found = _card_views(data)
        assert found == {card_a['id']: (board_a['id'], 'task'), card_b['id']: (board_b['id'], 'task')}
        first_card = data['boards'][0]['views'][0]['cards'][0]
        assert first_card['title'] == f'{token} on A'
        assert first_card['column_id'] == board_a['column_id']
        assert first_card['column_name'] == 'To Do'

    def test_matches_checklist_items(self, api_client, authenticated_session):
        token = _token()
        board = _create_board(api_client, authenticated_session, f'Checklist {token}')
        card = _create_card(api_client, authenticated_session, board['column_id'], 'Plain title')
        item = authenticated_session.post(
            f'{api_client}/api/cards/{card["id"]}/checklist-items',
            json={'name': f'step {token}', 'checked': False, 'order': 0},
        )
        assert item.status_code == 201, item.text

        response = _search(api_client, authenticated_session, q=token)
        assert response.status_code == 200
        assert set(_card_views(response.json())) == {card['id']}

    def test_groups_done_archived_and_scheduled_cards_by_view(self, api_client, authenticated_session):
        token = _token()
        agile = _create_board(api_client, authenticated_session, f'Agile {token}')
        style = authenticated_session.put(
            f'{api_client}/api/boards/{agile["id"]}/settings/working-style', json={'value': 'agile'}
        )
        assert style.status_code == 200, style.text
        kanban = _create_board(api_client, authenticated_session, f'Kanban {token}')

        task_card = _create_card(api_client, authenticated_session, agile['column_id'], f'{token} task')
        done_card = _create_card(api_client, authenticated_session, agile['column_id'], f'{token} done')
        archived_card = _create_card(api_client, authenticated_session, agile['column_id'], f'{token} archived')
        kanban_done = _create_card(api_client, authenticated_session, kanban['column_id'], f'{token} kanban done')

        for card_id in (done_card['id'], kanban_done['id']):
            done = authenticated_session.patch(f'{api_client}/api/cards/{card_id}/done', json={'done': True})
            assert done.status_code == 200, done.text
        archived = authenticated_session.patch(f'{api_client}/api/cards/{archived_card["id"]}/archive')
        assert archived.status_code == 200, archived.text

        schedule = authenticated_session.post(f'{api_client}/api/schedules', json={
            'card_id': task_card['id'],
            'keep_source_card': True,
            'run_every': 1,
            'unit': 'day',
            'start_datetime': (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%S'),
            'end_datetime': None,
            'schedule_enabled': True,
            'allow_duplicates': False,
        })
        assert schedule.status_code == 201, schedule.text

        response = _search(api_client, authenticated_session, q=token)
        assert response.status_code == 200, response.text
        data = response.json()
        found = _card_views(data)

        assert found[task_card['id']] == (agile['id'], 'task')
        assert found[done_card['id']] == (agile['id'], 'done')
        assert found[archived_card['id']] == (agile['id'], 'archived')
        # Kanban boards have no done view, so done cards stay in the task view.
        assert found[kanban_done['id']] == (kanban['id'], 'task')

        templates = [card_id for card_id, (_, view) in found.items() if view == 'scheduled']
        assert len(templates) == 1
        assert found[templates[0]] == (agile['id'], 'scheduled')

        agile_entry = next(board for board in data['boards'] if board['id'] == agile['id'])
        assert [view['view'] for view in agile_entry['views']] == ['task', 'done', 'archived', 'scheduled']

    def test_uses_board_search_grammar(self, api_client, authenticated_session):
        token = _token()
        board = _create_board(api_client, authenticated_session, f'Grammar {token}')
        red = _create_card(api_client, authenticated_session, board['column_id'], f'{token} red apple')
        green = _create_card(api_client, authenticated_session, board['column_id'], f'{token} green pear')
        quoted = _create_card(api_client, authenticated_session, board['column_id'], f'{token} say "hi" now')

        def ids(query):
            response = _search(api_client, authenticated_session, q=query)
            assert response.status_code == 200, response.text
            return set(_card_views(response.json()))

        assert ids(f'{token} apple') == {red['id']}
        assert ids(f'{token} apple, {token} pear') == {red['id'], green['id']}
        assert ids(f'"{token} green"') == {green['id']}
        assert ids(f'"say ""hi"""') == {quoted['id']}
        assert ids(f'#{green["id"]}') == {green['id']}
        # A quoted reference is text, which no card contains.
        assert ids(f'"#{green["id"]}" {token}') == set()

    def test_validates_query(self, api_client, authenticated_session):
        for params in ({}, {'q': ''}, {'q': ' a '}):
            response = _search(api_client, authenticated_session, **params)
            assert response.status_code == 400, params
            assert response.json()['success'] is False

        too_long = _search(api_client, authenticated_session, q='x' * 201)
        assert too_long.status_code == 400
        assert '200' in too_long.json()['message']

        too_many_groups = _search(api_client, authenticated_session, q=','.join(['ab'] * 13))
        assert too_many_groups.status_code == 400

        too_many_terms = _search(api_client, authenticated_session, q=' '.join(['ab'] * 25))
        assert too_many_terms.status_code == 400

        long_term = _search(api_client, authenticated_session, q='y' * 81)
        assert long_term.status_code == 400

    @pytest.mark.parametrize('params', [
        {'board_ids': 'abc'},
        {'board_ids': '1,-2'},
        {'board_ids': '0'},
        {'board_ids': ','},
        {'board_ids': ','.join(str(n) for n in range(1, 102))},
        {'include_archived_boards': 'maybe'},
        {'limit': '0'},
        {'limit': '201'},
        {'limit': 'ten'},
    ])
    def test_validates_options(self, api_client, authenticated_session, params):
        response = _search(api_client, authenticated_session, q='valid', **params)
        assert response.status_code == 400, response.text
        assert response.json()['success'] is False

    def test_limits_search_to_chosen_boards(self, api_client, authenticated_session):
        token = _token()
        board_a = _create_board(api_client, authenticated_session, f'Chosen A {token}')
        board_b = _create_board(api_client, authenticated_session, f'Chosen B {token}')
        board_c = _create_board(api_client, authenticated_session, f'Chosen C {token}')
        card_a = _create_card(api_client, authenticated_session, board_a['column_id'], token)
        _create_card(api_client, authenticated_session, board_b['column_id'], token)
        card_c = _create_card(api_client, authenticated_session, board_c['column_id'], token)

        response = _search(
            api_client, authenticated_session, q=token, board_ids=f'{board_a["id"]},{board_c["id"]}'
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert set(_card_views(data)) == {card_a['id'], card_c['id']}
        assert data['total'] == 2

    def test_archived_boards_only_when_asked_or_chosen(self, api_client, authenticated_session):
        token = _token()
        active = _create_board(api_client, authenticated_session, f'Active {token}')
        archived = _create_board(api_client, authenticated_session, f'Archived {token}')
        active_card = _create_card(api_client, authenticated_session, active['column_id'], token)
        archived_card = _create_card(api_client, authenticated_session, archived['column_id'], token)
        archive = authenticated_session.patch(f'{api_client}/api/boards/{archived["id"]}/archive')
        assert archive.status_code == 200, archive.text

        default = _search(api_client, authenticated_session, q=token)
        assert set(_card_views(default.json())) == {active_card['id']}

        included = _search(api_client, authenticated_session, q=token, include_archived_boards='true')
        data = included.json()
        assert set(_card_views(data)) == {active_card['id'], archived_card['id']}
        archived_entry = next(board for board in data['boards'] if board['id'] == archived['id'])
        assert archived_entry['archived'] is True

        chosen = _search(api_client, authenticated_session, q=token, board_ids=str(archived['id']))
        assert set(_card_views(chosen.json())) == {archived_card['id']}

    def test_caps_results_and_reports_total(self, api_client, authenticated_session):
        token = _token()
        board = _create_board(api_client, authenticated_session, f'Cap {token}')
        cards = [
            _create_card(api_client, authenticated_session, board['column_id'], f'{token} {n}')
            for n in range(5)
        ]

        response = _search(api_client, authenticated_session, q=token, limit='3')
        assert response.status_code == 200, response.text
        data = response.json()
        assert data['total'] == 5
        assert data['returned'] == 3
        assert data['limit'] == 3
        assert data['truncated'] is True
        # The most recently updated matches come first.
        assert set(_card_views(data)) == {card['id'] for card in cards[2:]}


@pytest.mark.api
class TestCardSearchAccess:
    """Results never include boards the user can't open."""

    def test_only_searches_boards_the_user_can_access(self, api_client, authenticated_session, test_admin_session):
        token = _token()
        user_session, _ = _new_user_session(api_client, test_admin_session)
        own_board = _create_board(api_client, user_session, f'Mine {token}')
        own_card = _create_card(api_client, user_session, own_board['column_id'], token)
        private_board = _create_board(api_client, authenticated_session, f'Private {token}')
        _create_card(api_client, authenticated_session, private_board['column_id'], token)

        try:
            response = _search(api_client, user_session, q=token)
            assert response.status_code == 200, response.text
            data = response.json()
            assert set(_card_views(data)) == {own_card['id']}
            assert data['total'] == 1
            assert f'Private {token}' not in response.text

            # Naming a board the user can't open returns nothing from it.
            chosen = _search(api_client, user_session, q=token, board_ids=str(private_board['id']))
            assert chosen.status_code == 200, chosen.text
            assert chosen.json()['boards'] == []
            assert chosen.json()['total'] == 0
            assert f'Private {token}' not in chosen.text

            # Admins search every board.
            admin = _search(api_client, authenticated_session, q=token)
            assert {board['id'] for board in admin.json()['boards']} == {own_board['id'], private_board['id']}
        finally:
            user_session.delete(f'{api_client}/api/boards/{own_board["id"]}')

    def test_shared_boards_are_searched_until_access_is_removed(
        self, api_client, authenticated_session, test_admin_session
    ):
        token = _token()
        user_session, user = _new_user_session(api_client, test_admin_session)
        shared = _create_board(api_client, authenticated_session, f'Shared {token}')
        shared_card = _create_card(api_client, authenticated_session, shared['column_id'], token)

        share = authenticated_session.put(
            f'{api_client}/api/boards/{shared["id"]}/members/{user["id"]}', json={'access': 'viewer'}
        )
        assert share.status_code == 200, share.text

        response = _search(api_client, user_session, q=token)
        assert response.status_code == 200, response.text
        assert set(_card_views(response.json())) == {shared_card['id']}

        remove = authenticated_session.delete(f'{api_client}/api/boards/{shared["id"]}/members/{user["id"]}')
        assert remove.status_code == 200, remove.text

        response = _search(api_client, user_session, q=token)
        assert response.status_code == 200, response.text
        assert response.json()['boards'] == []
