"""Sections board layout (#297).

A board shows its columns side by side (``columns``) or as sections stacked in
lanes (``sections``). The layout is a board setting, and each column keeps its
own lane and position in the sections layout, separate from its column order.
"""
import json

import pytest
import requests

from tests.test_api_card_broadcasts import BoardEvents


def _url(api_client, path):
    return f'{api_client}{path}'


def _make_columns(session, api_client, board_id, names):
    columns = []
    for name in names:
        response = session.post(
            _url(api_client, f'/api/boards/{board_id}/columns'), json={'name': name}
        )
        assert response.status_code == 201, response.text
        columns.append(response.json()['column'])
    return columns


def _board(session, api_client, board_id, path='cards'):
    response = session.get(_url(api_client, f'/api/boards/{board_id}/{path}'))
    assert response.status_code == 200, response.text
    return response.json()['board']


def _set_layout(session, api_client, board_id, value):
    return session.put(
        _url(api_client, f'/api/boards/{board_id}/settings/layout'), json={'value': value}
    )


def _save_sections(session, api_client, board_id, sections):
    return session.put(
        _url(api_client, f'/api/boards/{board_id}/section-layout'), json={'sections': sections}
    )


def _user_id(session, api_client):
    return session.get(_url(api_client, '/api/auth/me')).json()['user']['id']


@pytest.fixture
def three_columns(api_client, authenticated_session, sample_board):
    return _make_columns(
        authenticated_session, api_client, sample_board['id'], ['To do', 'Doing', 'Done']
    )


@pytest.mark.api
class TestBoardLayoutSetting:
    """Switching a board between columns and sections."""

    def test_new_board_uses_columns_layout(
        self, api_client, authenticated_session, sample_board, three_columns
    ):
        """Test a new board defaults to columns, with no section positions."""
        board = _board(authenticated_session, api_client, sample_board['id'])
        assert board['layout'] == 'columns'
        for column in board['columns']:
            assert column['section_lane'] is None
            assert column['section_order'] is None

    def test_set_layout_to_sections_and_back(
        self, api_client, authenticated_session, sample_board, three_columns
    ):
        """Test the layout is saved and returned with the board."""
        response = _set_layout(authenticated_session, api_client, sample_board['id'], 'sections')
        assert response.status_code == 200, response.text
        assert response.json()['value'] == 'sections'
        assert _board(authenticated_session, api_client, sample_board['id'])['layout'] == 'sections'
        scheduled = _board(authenticated_session, api_client, sample_board['id'], 'cards/scheduled')
        assert scheduled['layout'] == 'sections'

        response = _set_layout(authenticated_session, api_client, sample_board['id'], 'columns')
        assert response.status_code == 200, response.text
        assert _board(authenticated_session, api_client, sample_board['id'])['layout'] == 'columns'

    @pytest.mark.parametrize('body', [
        {},
        {'value': 'grid'},
        {'value': ''},
        {'value': None},
        {'value': 1},
        {'value': ['sections']},
        {'value': 'Sections'},
    ])
    def test_set_layout_rejects_invalid_values(
        self, api_client, authenticated_session, sample_board, body
    ):
        """Test only columns and sections are accepted."""
        response = authenticated_session.put(
            _url(api_client, f'/api/boards/{sample_board["id"]}/settings/layout'), json=body
        )
        assert response.status_code == 400, response.text
        assert response.json()['success'] is False
        assert _board(authenticated_session, api_client, sample_board['id'])['layout'] == 'columns'

    def test_set_layout_requires_authentication(self, api_client, sample_board):
        """Test anonymous requests are refused."""
        response = requests.put(
            _url(api_client, f'/api/boards/{sample_board["id"]}/settings/layout'),
            json={'value': 'sections'},
        )
        assert response.status_code == 401

    def test_board_viewer_sees_layout_but_cannot_change_it(
        self, api_client, authenticated_session, second_user_session, sample_board, three_columns
    ):
        """Test a viewer gets the layout but can't change it or arrange sections."""
        board_id = sample_board['id']
        assert _set_layout(authenticated_session, api_client, board_id, 'sections').status_code == 200
        role = authenticated_session.post(
            _url(api_client, f'/api/users/{_user_id(second_user_session, api_client)}/roles'),
            json={'role_name': 'board_viewer', 'board_id': board_id},
        )
        assert role.status_code == 200, role.text

        assert _board(second_user_session, api_client, board_id)['layout'] == 'sections'
        assert _set_layout(second_user_session, api_client, board_id, 'columns').status_code == 403
        sections = [{'column_id': column['id'], 'lane': 0} for column in three_columns]
        assert _save_sections(second_user_session, api_client, board_id, sections).status_code == 403
        assert _board(authenticated_session, api_client, board_id)['layout'] == 'sections'

    def test_other_users_board_is_refused(
        self, api_client, authenticated_session, second_user_session, sample_board, three_columns
    ):
        """Test someone with no access to the board can't change it."""
        board_id = sample_board['id']
        assert _set_layout(second_user_session, api_client, board_id, 'sections').status_code == 403
        sections = [{'column_id': column['id'], 'lane': 0} for column in three_columns]
        assert _save_sections(second_user_session, api_client, board_id, sections).status_code == 403

    def test_public_board_includes_layout_and_positions(
        self, api_client, authenticated_session, sample_board, three_columns
    ):
        """Test the public board shows the same layout."""
        board_id = sample_board['id']
        response = authenticated_session.patch(
            _url(api_client, f'/api/boards/{board_id}'), json={'is_public': True}
        )
        assert response.status_code == 200, response.text
        slug = response.json()['board']['public_slug']
        assert _set_layout(authenticated_session, api_client, board_id, 'sections').status_code == 200
        sections = [{'column_id': column['id'], 'lane': 1} for column in three_columns]
        assert _save_sections(authenticated_session, api_client, board_id, sections).status_code == 200

        public = requests.get(_url(api_client, f'/api/public/boards/{slug}'))
        assert public.status_code == 200, public.text
        board = public.json()['board']
        assert board['layout'] == 'sections'
        # One lane in use, so it's numbered 0.
        assert {column['section_lane'] for column in board['columns']} == {0}

    def test_layout_change_is_broadcast(
        self, api_client, authenticated_session, sample_board, three_columns
    ):
        """Test other clients on the board hear about a layout change."""
        events = BoardEvents(api_client, authenticated_session, sample_board['id'])
        try:
            assert _set_layout(
                authenticated_session, api_client, sample_board['id'], 'sections'
            ).status_code == 200
            data = events.wait_for('board_layout_changed')
            assert data['board_id'] == sample_board['id']
            assert data['layout'] == 'sections'
        finally:
            events.close()


@pytest.mark.api
class TestSectionLayout:
    """Saving where sections sit."""

    def test_save_sections_keeps_column_order(
        self, api_client, authenticated_session, sample_board, three_columns
    ):
        """Test lanes and positions are saved without reordering the columns."""
        board_id = sample_board['id']
        todo, doing, done = three_columns
        sections = [
            {'column_id': done['id'], 'lane': 0},
            {'column_id': todo['id'], 'lane': 0},
            {'column_id': doing['id'], 'lane': 2},
        ]
        response = _save_sections(authenticated_session, api_client, board_id, sections)
        assert response.status_code == 200, response.text
        assert [s['section_order'] for s in response.json()['sections']] == [0, 1, 2]

        board = _board(authenticated_session, api_client, board_id)
        columns = {column['id']: column for column in board['columns']}
        assert [column['id'] for column in board['columns']] == [todo['id'], doing['id'], done['id']]
        assert (columns[done['id']]['section_lane'], columns[done['id']]['section_order']) == (0, 0)
        assert (columns[todo['id']]['section_lane'], columns[todo['id']]['section_order']) == (0, 1)
        # Lane 1 was empty, so lane 2 closes up to 1.
        assert (columns[doing['id']]['section_lane'], columns[doing['id']]['section_order']) == (1, 2)

        listed = authenticated_session.get(_url(api_client, f'/api/boards/{board_id}/columns'))
        assert listed.status_code == 200
        assert {c['id']: c['section_lane'] for c in listed.json()['columns']}[doing['id']] == 1

    def test_new_column_has_no_section_position(
        self, api_client, authenticated_session, sample_board, three_columns
    ):
        """Test a column added after arranging is left for the board to place."""
        board_id = sample_board['id']
        sections = [{'column_id': column['id'], 'lane': 0} for column in three_columns]
        assert _save_sections(authenticated_session, api_client, board_id, sections).status_code == 200
        new_column = _make_columns(authenticated_session, api_client, board_id, ['Later'])[0]

        board = _board(authenticated_session, api_client, board_id)
        added = next(column for column in board['columns'] if column['id'] == new_column['id'])
        assert added['section_lane'] is None
        assert added['section_order'] is None

    def test_lanes_have_no_limit_and_close_up(
        self, api_client, authenticated_session, sample_board, three_columns
    ):
        """Test any lane number is allowed, and lanes are renumbered without gaps."""
        lanes = [5, 2 ** 31 - 1, 5]
        sections = [
            {'column_id': column['id'], 'lane': lane} for column, lane in zip(three_columns, lanes)
        ]
        response = _save_sections(authenticated_session, api_client, sample_board['id'], sections)
        assert response.status_code == 200, response.text
        assert [s['lane'] for s in response.json()['sections']] == [0, 1, 0]

        board = _board(authenticated_session, api_client, sample_board['id'])
        saved = {column['id']: column['section_lane'] for column in board['columns']}
        assert [saved[column['id']] for column in three_columns] == [0, 1, 0]

    def test_many_lanes_are_allowed(self, api_client, authenticated_session, sample_board):
        """Test a board can have more lanes than there used to be a limit for."""
        columns = _make_columns(
            authenticated_session, api_client, sample_board['id'], [f'Lane {i}' for i in range(15)]
        )
        sections = [{'column_id': column['id'], 'lane': index} for index, column in enumerate(columns)]
        response = _save_sections(authenticated_session, api_client, sample_board['id'], sections)
        assert response.status_code == 200, response.text
        assert [s['lane'] for s in response.json()['sections']] == list(range(15))

    @pytest.mark.parametrize('lane', [-1, 2 ** 31, 1.5, '1', None, True])
    def test_invalid_lane_is_rejected(
        self, api_client, authenticated_session, sample_board, three_columns, lane
    ):
        """Test lanes that are negative, too big to store, or not integers are refused."""
        sections = [{'column_id': column['id'], 'lane': 0} for column in three_columns]
        sections[1]['lane'] = lane
        response = _save_sections(authenticated_session, api_client, sample_board['id'], sections)
        assert response.status_code == 400, response.text
        board = _board(authenticated_session, api_client, sample_board['id'])
        assert all(column['section_lane'] is None for column in board['columns'])

    @pytest.mark.parametrize('body', [
        {},
        {'sections': []},
        {'sections': 'all'},
        {'sections': {'column_id': 1, 'lane': 0}},
    ])
    def test_invalid_sections_list_is_rejected(
        self, api_client, authenticated_session, sample_board, three_columns, body
    ):
        """Test the body must hold a non-empty list."""
        response = authenticated_session.put(
            _url(api_client, f'/api/boards/{sample_board["id"]}/section-layout'), json=body
        )
        assert response.status_code == 400, response.text

    @pytest.mark.parametrize('bad_entry', [
        'column',
        {'column_id': '1', 'lane': 0},
        {'column_id': True, 'lane': 0},
        {'lane': 0},
    ])
    def test_invalid_entry_is_rejected(
        self, api_client, authenticated_session, sample_board, three_columns, bad_entry
    ):
        """Test each entry needs an integer column_id and a lane."""
        sections = [{'column_id': column['id'], 'lane': 0} for column in three_columns[:2]]
        sections.append(bad_entry)
        response = _save_sections(authenticated_session, api_client, sample_board['id'], sections)
        assert response.status_code == 400, response.text

    def test_duplicate_column_is_rejected(
        self, api_client, authenticated_session, sample_board, three_columns
    ):
        """Test a column can't be listed twice."""
        sections = [{'column_id': column['id'], 'lane': 0} for column in three_columns[:2]]
        sections.append({'column_id': three_columns[0]['id'], 'lane': 1})
        response = _save_sections(authenticated_session, api_client, sample_board['id'], sections)
        assert response.status_code == 400, response.text

    def test_missing_column_is_a_conflict(
        self, api_client, authenticated_session, sample_board, three_columns
    ):
        """Test a list without every column is refused, so a stale page reloads."""
        sections = [{'column_id': column['id'], 'lane': 0} for column in three_columns[:2]]
        response = _save_sections(authenticated_session, api_client, sample_board['id'], sections)
        assert response.status_code == 409, response.text

    def test_column_from_another_board_is_a_conflict(
        self, api_client, authenticated_session, sample_board, three_columns
    ):
        """Test columns of another board can't be arranged through this one."""
        other = authenticated_session.post(_url(api_client, '/api/boards'), json={'name': 'Other'})
        assert other.status_code == 201
        other_column = _make_columns(
            authenticated_session, api_client, other.json()['board']['id'], ['Elsewhere']
        )[0]
        sections = [{'column_id': column['id'], 'lane': 0} for column in three_columns[:2]]
        sections.append({'column_id': other_column['id'], 'lane': 0})
        response = _save_sections(authenticated_session, api_client, sample_board['id'], sections)
        assert response.status_code == 409, response.text

        other_board = _board(authenticated_session, api_client, other.json()['board']['id'])
        assert other_board['columns'][0]['section_lane'] is None

    def test_too_many_entries_is_a_conflict(
        self, api_client, authenticated_session, sample_board, three_columns
    ):
        """Test a list longer than the board's columns is refused before it's read."""
        sections = [{'column_id': column['id'], 'lane': 0} for column in three_columns]
        sections.append({'column_id': 999999, 'lane': 0})
        response = _save_sections(authenticated_session, api_client, sample_board['id'], sections)
        assert response.status_code == 409, response.text

    def test_save_is_broadcast(
        self, api_client, authenticated_session, sample_board, three_columns
    ):
        """Test other clients on the board reload after sections move."""
        events = BoardEvents(api_client, authenticated_session, sample_board['id'])
        try:
            sections = [{'column_id': column['id'], 'lane': 0} for column in three_columns]
            assert _save_sections(
                authenticated_session, api_client, sample_board['id'], sections
            ).status_code == 200
            assert events.wait_for('column_reordered')['board_id'] == sample_board['id']
        finally:
            events.close()


@pytest.mark.api
class TestSectionLayoutExportImport:
    """The layout and section positions travel with an AFT export."""

    def test_export_import_round_trip(
        self, api_client, authenticated_session, sample_board, three_columns
    ):
        """Test an imported board keeps its layout and section positions."""
        board_id = sample_board['id']
        assert _set_layout(authenticated_session, api_client, board_id, 'sections').status_code == 200
        lanes = {three_columns[0]['id']: 2, three_columns[1]['id']: 0, three_columns[2]['id']: 1}
        sections = [{'column_id': cid, 'lane': lane} for cid, lane in lanes.items()]
        assert _save_sections(authenticated_session, api_client, board_id, sections).status_code == 200

        export = authenticated_session.get(_url(api_client, f'/api/boards/{board_id}/export'))
        assert export.status_code == 200
        payload = export.json()
        exported = {column['id']: column for column in payload['columns']}
        assert exported[three_columns[0]['id']]['section_lane'] == 2
        assert any(
            setting['key'] == 'board_layout' and json.loads(setting['value']) == 'sections'
            for setting in payload['board_settings']
        )

        imported = authenticated_session.post(
            _url(api_client, '/api/boards/import'),
            data={'duplicate_strategy': 'append_suffix'},
            files={'file': ('board-export.json', json.dumps(payload), 'application/json')},
        )
        assert imported.status_code == 201, imported.text
        board = _board(authenticated_session, api_client, imported.json()['board']['id'])
        assert board['layout'] == 'sections'
        by_name = {column['name']: column for column in board['columns']}
        for source in three_columns:
            assert by_name[source['name']]['section_lane'] == lanes[source['id']]
        assert [by_name[c['name']]['section_order'] for c in three_columns] == [0, 1, 2]

    @pytest.mark.parametrize('lane, order', [
        (2 ** 31, 0), (-1, 0), ('1', 0), (True, 0), (0, -1), (0, 'x'), (0, 10 ** 12),
    ])
    def test_import_drops_invalid_positions(
        self, api_client, authenticated_session, sample_board, three_columns, lane, order
    ):
        """Test bad positions in an export are dropped, leaving the column to be placed."""
        export = authenticated_session.get(
            _url(api_client, f'/api/boards/{sample_board["id"]}/export')
        ).json()
        export['columns'][0]['section_lane'] = lane
        export['columns'][0]['section_order'] = order
        imported = authenticated_session.post(
            _url(api_client, '/api/boards/import'),
            data={'duplicate_strategy': 'append_suffix'},
            files={'file': ('board-export.json', json.dumps(export), 'application/json')},
        )
        assert imported.status_code == 201, imported.text
        board = _board(authenticated_session, api_client, imported.json()['board']['id'])
        first = next(c for c in board['columns'] if c['name'] == export['columns'][0]['name'])
        assert first['section_lane'] is None or first['section_order'] is None

    def test_import_of_older_export_has_no_positions(
        self, api_client, authenticated_session, sample_board, three_columns
    ):
        """Test exports from before sections import with columns left to be placed."""
        export = authenticated_session.get(
            _url(api_client, f'/api/boards/{sample_board["id"]}/export')
        ).json()
        export['export']['format_version'] = '1.1'
        for column in export['columns']:
            column.pop('section_lane', None)
            column.pop('section_order', None)
        imported = authenticated_session.post(
            _url(api_client, '/api/boards/import'),
            data={'duplicate_strategy': 'append_suffix'},
            files={'file': ('board-export.json', json.dumps(export), 'application/json')},
        )
        assert imported.status_code == 201, imported.text
        board = _board(authenticated_session, api_client, imported.json()['board']['id'])
        assert board['layout'] == 'columns'
        assert all(column['section_lane'] is None for column in board['columns'])

    def test_import_closes_gaps_between_lanes(
        self, api_client, authenticated_session, sample_board, three_columns
    ):
        """Test lanes in an export are renumbered without gaps on import."""
        export = authenticated_session.get(
            _url(api_client, f'/api/boards/{sample_board["id"]}/export')
        ).json()
        for index, (column, lane) in enumerate(zip(export['columns'], [3, 7, 7])):
            column['section_lane'] = lane
            column['section_order'] = index
        imported = authenticated_session.post(
            _url(api_client, '/api/boards/import'),
            data={'duplicate_strategy': 'append_suffix'},
            files={'file': ('board-export.json', json.dumps(export), 'application/json')},
        )
        assert imported.status_code == 201, imported.text
        board = _board(authenticated_session, api_client, imported.json()['board']['id'])
        by_name = {column['name']: column['section_lane'] for column in board['columns']}
        assert [by_name[column['name']] for column in export['columns']] == [0, 1, 1]
