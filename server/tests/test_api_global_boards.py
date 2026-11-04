"""API tests for global boards (#663).

Cover access isolation, the done window and the card lifecycle rules for
promoted cards.
"""
import time

import pytest
import requests


def _url(api_client, path):
    return f'{api_client}{path}'


def _global_board(session, api_client):
    response = session.get(_url(api_client, '/api/global-boards'))
    assert response.status_code == 200, response.text
    boards = response.json()['global_boards']
    assert len(boards) == 1
    return boards[0]


def _make_board(session, api_client, name='Epic', style='agile', columns=('Feature',)):
    board = session.post(_url(api_client, '/api/boards'), json={'name': name})
    assert board.status_code == 201, board.text
    board_id = board.json()['board']['id']
    style_response = session.put(
        _url(api_client, f'/api/boards/{board_id}/settings/working-style'),
        json={'value': style},
    )
    assert style_response.status_code == 200, style_response.text
    column_ids = []
    for column_name in columns:
        column = session.post(
            _url(api_client, f'/api/boards/{board_id}/columns'), json={'name': column_name}
        )
        assert column.status_code == 201, column.text
        column_ids.append(column.json()['column']['id'])
    return board_id, column_ids


def _make_card(session, api_client, column_id, title='Story'):
    card = session.post(_url(api_client, f'/api/columns/{column_id}/cards'), json={'title': title})
    assert card.status_code == 201, card.text
    return card.json()['card']['id']


def _promote(session, api_client, global_board_id, card_id, **extra):
    return session.post(
        _url(api_client, f'/api/global-boards/{global_board_id}/cards'),
        json={'card_id': card_id, **extra},
    )


def _move(session, api_client, global_board_id, card_id, state, after_card_id=None):
    return session.patch(
        _url(api_client, f'/api/global-boards/{global_board_id}/cards/{card_id}'),
        json={'state': state, 'after_card_id': after_card_id},
    )


def _states(session, api_client, global_board_id, query=''):
    response = session.get(_url(api_client, f'/api/global-boards/{global_board_id}/cards{query}'))
    assert response.status_code == 200, response.text
    return response.json()['states']


def _ids(states, state):
    return [card['card_id'] for card in states[state]]


def _user_id(session, api_client):
    return session.get(_url(api_client, '/api/auth/me')).json()['user']['id']


@pytest.fixture
def global_board(api_client, authenticated_session):
    """The instance global board, restored to its defaults afterwards."""
    board = _global_board(authenticated_session, api_client)
    yield board
    authenticated_session.patch(
        _url(api_client, f"/api/global-boards/{board['id']}"),
        json={'name': 'Global', 'done_visible_days': 14},
    )


@pytest.fixture
def epic(api_client, authenticated_session):
    """An agile board with two feature columns, owned by the test admin."""
    board_id, column_ids = _make_board(
        authenticated_session, api_client, columns=('Feature A', 'Feature B')
    )
    return {'board_id': board_id, 'column_ids': column_ids}


@pytest.mark.api
class TestGlobalBoardSettings:
    """The global board itself: listing and managing it."""

    def test_instance_board_is_seeded(self, api_client, authenticated_session, global_board):
        """Test one instance board exists with the default done window."""
        assert global_board['name'] == 'Global'
        assert global_board['visibility'] == 'everyone'
        assert global_board['done_visible_days'] == 14
        assert global_board['can_manage'] is True

    def test_admin_can_rename_and_set_window(self, api_client, authenticated_session, global_board):
        """Test renaming to Sprint and clearing the done window."""
        response = authenticated_session.patch(
            _url(api_client, f"/api/global-boards/{global_board['id']}"),
            json={'name': '  Sprint  ', 'done_visible_days': None},
        )
        assert response.status_code == 200, response.text
        updated = response.json()['global_board']
        assert updated['name'] == 'Sprint'
        assert updated['done_visible_days'] is None
        assert _global_board(authenticated_session, api_client)['name'] == 'Sprint'

    @pytest.mark.parametrize('payload', [
        {},
        {'name': ''},
        {'name': '   '},
        {'name': 123},
        {'name': 'x' * 101},
        {'done_visible_days': 0},
        {'done_visible_days': 3651},
        {'done_visible_days': '7'},
        {'done_visible_days': True},
    ])
    def test_invalid_updates_are_rejected(
        self, api_client, authenticated_session, global_board, payload
    ):
        """Test bad names and done windows return 400 and change nothing."""
        response = authenticated_session.patch(
            _url(api_client, f"/api/global-boards/{global_board['id']}"), json=payload
        )
        assert response.status_code == 400, response.text
        assert _global_board(authenticated_session, api_client) == global_board

    def test_unknown_global_board_is_404(self, api_client, authenticated_session):
        """Test a global board id that doesn't exist."""
        assert authenticated_session.get(
            _url(api_client, '/api/global-boards/999999/cards')
        ).status_code == 404
        assert authenticated_session.patch(
            _url(api_client, '/api/global-boards/999999'), json={'name': 'x'}
        ).status_code == 404

    def test_regular_user_sees_board_but_cannot_manage(
        self, api_client, second_user_session, global_board
    ):
        """Test everyone sees the instance board, but only managers change it."""
        board = _global_board(second_user_session, api_client)
        assert board['id'] == global_board['id']
        assert board['can_manage'] is False

        response = second_user_session.patch(
            _url(api_client, f"/api/global-boards/{global_board['id']}"), json={'name': 'Mine'}
        )
        assert response.status_code == 403

    def test_requires_authentication(self, api_client, global_board):
        """Test the endpoints need a session."""
        assert requests.get(_url(api_client, '/api/global-boards')).status_code == 401
        assert requests.get(
            _url(api_client, f"/api/global-boards/{global_board['id']}/cards")
        ).status_code == 401


@pytest.mark.api
class TestPromotion:
    """Promoting and demoting cards."""

    def test_agile_board_lists_eligible_global_board(
        self, api_client, authenticated_session, global_board, epic
    ):
        """Test an agile board can promote to the instance board."""
        response = authenticated_session.get(
            _url(api_client, f"/api/boards/{epic['board_id']}/global-boards")
        )
        assert response.status_code == 200, response.text
        assert [b['id'] for b in response.json()['global_boards']] == [global_board['id']]

    def test_kanban_board_has_no_eligible_global_boards(
        self, api_client, authenticated_session, global_board
    ):
        """Test kanban boards can't promote, and the server rejects it."""
        board_id, (column_id,) = _make_board(authenticated_session, api_client, style='kanban')
        response = authenticated_session.get(
            _url(api_client, f'/api/boards/{board_id}/global-boards')
        )
        assert response.json()['global_boards'] == []

        card_id = _make_card(authenticated_session, api_client, column_id)
        response = _promote(authenticated_session, api_client, global_board['id'], card_id)
        assert response.status_code == 403

    def test_promote_lists_card_with_epic_and_feature(
        self, api_client, authenticated_session, global_board, epic
    ):
        """Test a promoted card shows in New with its board and column names."""
        card_id = _make_card(authenticated_session, api_client, epic['column_ids'][0], 'Login page')
        response = _promote(authenticated_session, api_client, global_board['id'], card_id)
        assert response.status_code == 201, response.text

        states = _states(authenticated_session, api_client, global_board['id'])
        assert _ids(states, 'new') == [card_id]
        card = states['new'][0]
        assert card['title'] == 'Login page'
        assert card['board_name'] == 'Epic'
        assert card['column_name'] == 'Feature A'
        assert card['state'] == 'new'
        assert card['can_edit'] is True

    def test_promote_into_a_given_state(self, api_client, authenticated_session, global_board, epic):
        """Test promoting straight into In Progress."""
        card_id = _make_card(authenticated_session, api_client, epic['column_ids'][0])
        response = _promote(
            authenticated_session, api_client, global_board['id'], card_id, state='in_progress'
        )
        assert response.status_code == 201, response.text
        states = _states(authenticated_session, api_client, global_board['id'])
        assert _ids(states, 'in_progress') == [card_id]

    @pytest.mark.parametrize('payload', [
        {},
        {'card_id': 'abc'},
        {'card_id': 0},
        {'card_id': True},
    ])
    def test_promote_rejects_bad_card_id(
        self, api_client, authenticated_session, global_board, payload
    ):
        """Test a missing or invalid card id is a client error."""
        response = authenticated_session.post(
            _url(api_client, f"/api/global-boards/{global_board['id']}/cards"), json=payload
        )
        assert response.status_code in (400, 403, 404), response.text

    def test_promote_rejects_done_state_and_unknown_state(
        self, api_client, authenticated_session, global_board, epic
    ):
        """Test promotion only accepts the stored states."""
        card_id = _make_card(authenticated_session, api_client, epic['column_ids'][0])
        for state in ('done', 'blocked'):
            response = _promote(
                authenticated_session, api_client, global_board['id'], card_id, state=state
            )
            assert response.status_code == 400, response.text

    def test_promote_twice_is_conflict(self, api_client, authenticated_session, global_board, epic):
        """Test a story is on one global board at a time."""
        card_id = _make_card(authenticated_session, api_client, epic['column_ids'][0])
        assert _promote(authenticated_session, api_client, global_board['id'], card_id).status_code == 201
        assert _promote(authenticated_session, api_client, global_board['id'], card_id).status_code == 409

    def test_cannot_promote_done_or_archived_card(
        self, api_client, authenticated_session, global_board, epic
    ):
        """Test done and archived cards can't be promoted."""
        done_id = _make_card(authenticated_session, api_client, epic['column_ids'][0], 'Done')
        authenticated_session.patch(_url(api_client, f'/api/cards/{done_id}/done'), json={'done': True})
        archived_id = _make_card(authenticated_session, api_client, epic['column_ids'][0], 'Old')
        authenticated_session.patch(_url(api_client, f'/api/cards/{archived_id}/archive'))

        for card_id in (done_id, archived_id):
            response = _promote(authenticated_session, api_client, global_board['id'], card_id)
            assert response.status_code == 400, response.text

    def test_cannot_promote_schedule_template(
        self, api_client, authenticated_session, global_board, epic
    ):
        """Test a scheduled template card can't be promoted."""
        card_id = _make_card(authenticated_session, api_client, epic['column_ids'][0])
        schedule = authenticated_session.post(_url(api_client, '/api/schedules'), json={
            'card_id': card_id,
            'run_every': 1,
            'unit': 'day',
            'start_datetime': '2099-01-01T09:00:00Z',
        })
        assert schedule.status_code == 201, schedule.text
        template_id = schedule.json()['schedule']['card_id']

        response = _promote(authenticated_session, api_client, global_board['id'], template_id)
        assert response.status_code == 400, response.text

    def test_demote_removes_card(self, api_client, authenticated_session, global_board, epic):
        """Test demote takes the card off and leaves the card itself alone."""
        card_id = _make_card(authenticated_session, api_client, epic['column_ids'][0])
        _promote(authenticated_session, api_client, global_board['id'], card_id)

        response = authenticated_session.delete(
            _url(api_client, f"/api/global-boards/{global_board['id']}/cards/{card_id}")
        )
        assert response.status_code == 200, response.text
        states = _states(authenticated_session, api_client, global_board['id'])
        assert all(card_id not in _ids(states, state) for state in states)
        assert authenticated_session.get(_url(api_client, f'/api/cards/{card_id}')).status_code == 200

        again = authenticated_session.delete(
            _url(api_client, f"/api/global-boards/{global_board['id']}/cards/{card_id}")
        )
        assert again.status_code == 404


@pytest.mark.api
class TestStatesAndDone:
    """Moving cards between states, and how done works."""

    def test_move_between_states_and_order(
        self, api_client, authenticated_session, global_board, epic
    ):
        """Test moves use 'after card X', with no id meaning the top."""
        gid = global_board['id']
        first, second, third = (
            _make_card(authenticated_session, api_client, epic['column_ids'][0], title)
            for title in ('One', 'Two', 'Three')
        )
        for card_id in (first, second, third):
            _promote(authenticated_session, api_client, gid, card_id)
        assert _ids(_states(authenticated_session, api_client, gid), 'new') == [first, second, third]

        assert _move(authenticated_session, api_client, gid, third, 'new').status_code == 200
        assert _ids(_states(authenticated_session, api_client, gid), 'new') == [third, first, second]

        assert _move(authenticated_session, api_client, gid, third, 'new', first).status_code == 200
        assert _ids(_states(authenticated_session, api_client, gid), 'new') == [first, third, second]

        assert _move(authenticated_session, api_client, gid, second, 'waiting').status_code == 200
        assert _move(authenticated_session, api_client, gid, first, 'waiting', second).status_code == 200
        states = _states(authenticated_session, api_client, gid)
        assert _ids(states, 'new') == [third]
        assert _ids(states, 'waiting') == [second, first]

    def test_move_rejects_bad_input(self, api_client, authenticated_session, global_board, epic):
        """Test bad states and after-card ids are rejected."""
        gid = global_board['id']
        card_id = _make_card(authenticated_session, api_client, epic['column_ids'][0])
        other_id = _make_card(authenticated_session, api_client, epic['column_ids'][0])
        _promote(authenticated_session, api_client, gid, card_id)
        _promote(authenticated_session, api_client, gid, other_id, state='waiting')

        assert _move(authenticated_session, api_client, gid, card_id, 'blocked').status_code == 400
        assert _move(authenticated_session, api_client, gid, card_id, 'new', card_id).status_code == 400
        assert _move(authenticated_session, api_client, gid, card_id, 'new', 'x').status_code == 400
        # The after card must already be in the target state.
        assert _move(authenticated_session, api_client, gid, card_id, 'new', other_id).status_code == 400

    def test_move_unpromoted_card_is_404(self, api_client, authenticated_session, global_board, epic):
        """Test moving a card that isn't on the board."""
        card_id = _make_card(authenticated_session, api_client, epic['column_ids'][0])
        assert _move(authenticated_session, api_client, global_board['id'], card_id, 'new').status_code == 404

    def test_done_on_epic_board_returns_to_previous_state(
        self, api_client, authenticated_session, global_board, epic
    ):
        """Test ticking done shows the card as Done, and unticking restores its state."""
        gid = global_board['id']
        card_id = _make_card(authenticated_session, api_client, epic['column_ids'][0])
        _promote(authenticated_session, api_client, gid, card_id, state='waiting')

        authenticated_session.patch(_url(api_client, f'/api/cards/{card_id}/done'), json={'done': True})
        states = _states(authenticated_session, api_client, gid)
        assert _ids(states, 'done') == [card_id]
        assert states['done'][0]['stored_state'] == 'waiting'
        assert states['done'][0]['done_datetime'] is not None

        undone = authenticated_session.patch(
            _url(api_client, f'/api/cards/{card_id}/done'), json={'done': False}
        )
        assert undone.json()['done_datetime'] is None
        assert _ids(_states(authenticated_session, api_client, gid), 'waiting') == [card_id]

    def test_drag_to_done_and_back(self, api_client, authenticated_session, global_board, epic):
        """Test moving to Done ticks the card, and moving out unticks it."""
        gid = global_board['id']
        card_id = _make_card(authenticated_session, api_client, epic['column_ids'][0])
        _promote(authenticated_session, api_client, gid, card_id, state='in_progress')

        assert _move(authenticated_session, api_client, gid, card_id, 'done').status_code == 200
        card = authenticated_session.get(_url(api_client, f'/api/cards/{card_id}/done')).json()
        assert card['done'] is True
        assert card['done_datetime'] is not None

        assert _move(authenticated_session, api_client, gid, card_id, 'new').status_code == 200
        card = authenticated_session.get(_url(api_client, f'/api/cards/{card_id}/done')).json()
        assert card['done'] is False
        assert card['done_datetime'] is None
        assert _ids(_states(authenticated_session, api_client, gid), 'new') == [card_id]

    def test_done_is_newest_first(self, api_client, authenticated_session, global_board, epic):
        """Test the Done list sorts by done time, newest first."""
        gid = global_board['id']
        first = _make_card(authenticated_session, api_client, epic['column_ids'][0], 'First')
        second = _make_card(authenticated_session, api_client, epic['column_ids'][0], 'Second')
        for card_id in (first, second):
            _promote(authenticated_session, api_client, gid, card_id)
        _move(authenticated_session, api_client, gid, first, 'done')
        time.sleep(1.1)  # done_datetime has one-second resolution
        _move(authenticated_session, api_client, gid, second, 'done')

        assert _ids(_states(authenticated_session, api_client, gid), 'done') == [second, first]

    def test_promoted_card_on_kanban_board_records_done_time(
        self, api_client, authenticated_session, global_board, epic
    ):
        """Test done time is kept for promoted cards after the board turns kanban."""
        gid = global_board['id']
        card_id = _make_card(authenticated_session, api_client, epic['column_ids'][0])
        _promote(authenticated_session, api_client, gid, card_id)
        authenticated_session.put(
            _url(api_client, f"/api/boards/{epic['board_id']}/settings/working-style"),
            json={'value': 'kanban'},
        )

        done = authenticated_session.patch(
            _url(api_client, f'/api/cards/{card_id}/done'), json={'done': True}
        )
        assert done.json()['done_datetime'] is not None
        assert _ids(_states(authenticated_session, api_client, gid), 'done') == [card_id]

    def test_done_window_none_shows_done_cards(
        self, api_client, authenticated_session, global_board, epic
    ):
        """Test done cards inside the window, and with no window, are listed."""
        gid = global_board['id']
        card_id = _make_card(authenticated_session, api_client, epic['column_ids'][0])
        _promote(authenticated_session, api_client, gid, card_id)
        _move(authenticated_session, api_client, gid, card_id, 'done')

        authenticated_session.patch(
            _url(api_client, f'/api/global-boards/{gid}'), json={'done_visible_days': 1}
        )
        assert _ids(_states(authenticated_session, api_client, gid), 'done') == [card_id]

        authenticated_session.patch(
            _url(api_client, f'/api/global-boards/{gid}'), json={'done_visible_days': None}
        )
        assert _ids(_states(authenticated_session, api_client, gid), 'done') == [card_id]


@pytest.mark.api
class TestLifecycle:
    """What happens to promotions when cards and boards change."""

    def test_archived_card_is_hidden_and_returns(
        self, api_client, authenticated_session, global_board, epic
    ):
        """Test archiving hides a card, and unarchiving brings it back in its state."""
        gid = global_board['id']
        card_id = _make_card(authenticated_session, api_client, epic['column_ids'][0])
        _promote(authenticated_session, api_client, gid, card_id, state='waiting')

        authenticated_session.patch(_url(api_client, f'/api/cards/{card_id}/archive'))
        states = _states(authenticated_session, api_client, gid)
        assert all(card_id not in _ids(states, state) for state in states)

        authenticated_session.patch(_url(api_client, f'/api/cards/{card_id}/unarchive'))
        assert _ids(_states(authenticated_session, api_client, gid), 'waiting') == [card_id]

    def test_archived_board_hides_cards(self, api_client, authenticated_session, global_board, epic):
        """Test archiving the epic hides its cards until it's unarchived."""
        gid = global_board['id']
        card_id = _make_card(authenticated_session, api_client, epic['column_ids'][0])
        _promote(authenticated_session, api_client, gid, card_id)

        authenticated_session.patch(_url(api_client, f"/api/boards/{epic['board_id']}/archive"))
        assert _ids(_states(authenticated_session, api_client, gid), 'new') == []

        authenticated_session.patch(_url(api_client, f"/api/boards/{epic['board_id']}/unarchive"))
        assert _ids(_states(authenticated_session, api_client, gid), 'new') == [card_id]

    def test_deleting_card_column_or_board_removes_entry(
        self, api_client, authenticated_session, global_board, epic
    ):
        """Test deletes cascade to the global board."""
        gid = global_board['id']
        by_card = _make_card(authenticated_session, api_client, epic['column_ids'][0])
        by_column = _make_card(authenticated_session, api_client, epic['column_ids'][1])
        other_board_id, (other_column,) = _make_board(authenticated_session, api_client, 'Other')
        by_board = _make_card(authenticated_session, api_client, other_column)
        for card_id in (by_card, by_column, by_board):
            _promote(authenticated_session, api_client, gid, card_id)

        authenticated_session.delete(_url(api_client, f'/api/cards/{by_card}'))
        authenticated_session.delete(_url(api_client, f"/api/columns/{epic['column_ids'][1]}"))
        authenticated_session.delete(_url(api_client, f'/api/boards/{other_board_id}'))

        assert _ids(_states(authenticated_session, api_client, gid), 'new') == []

    def test_board_switched_to_kanban_keeps_promotions(
        self, api_client, authenticated_session, global_board, epic
    ):
        """Test promotions stay when the epic turns kanban, but no new ones are allowed."""
        gid = global_board['id']
        kept = _make_card(authenticated_session, api_client, epic['column_ids'][0])
        _promote(authenticated_session, api_client, gid, kept)
        authenticated_session.put(
            _url(api_client, f"/api/boards/{epic['board_id']}/settings/working-style"),
            json={'value': 'kanban'},
        )

        assert _ids(_states(authenticated_session, api_client, gid), 'new') == [kept]
        assert _move(authenticated_session, api_client, gid, kept, 'in_progress').status_code == 200

        new_card = _make_card(authenticated_session, api_client, epic['column_ids'][0])
        assert _promote(authenticated_session, api_client, gid, new_card).status_code == 403

    @pytest.mark.parametrize('target_style', ['agile', 'kanban'])
    def test_card_moved_to_another_board_stays_promoted(
        self, api_client, authenticated_session, global_board, epic, target_style
    ):
        """Test a cross-board move keeps the promotion and shows the new epic."""
        gid = global_board['id']
        card_id = _make_card(authenticated_session, api_client, epic['column_ids'][0])
        _promote(authenticated_session, api_client, gid, card_id, state='in_progress')
        _, (target_column,) = _make_board(
            authenticated_session, api_client, 'Target', style=target_style
        )

        moved = authenticated_session.patch(
            _url(api_client, f'/api/cards/{card_id}'),
            json={'column_id': target_column, 'position': 'bottom'},
        )
        assert moved.status_code == 200, moved.text

        states = _states(authenticated_session, api_client, gid)
        assert _ids(states, 'in_progress') == [card_id]
        assert states['in_progress'][0]['board_name'] == 'Target'

    def test_column_move_to_another_board_keeps_promotions(
        self, api_client, authenticated_session, global_board, epic
    ):
        """Test moving a whole column's cards keeps their promotions."""
        gid = global_board['id']
        card_id = _make_card(authenticated_session, api_client, epic['column_ids'][0])
        _promote(authenticated_session, api_client, gid, card_id)
        _, (target_column,) = _make_board(authenticated_session, api_client, 'Target')

        moved = authenticated_session.post(
            _url(api_client, f"/api/columns/{epic['column_ids'][0]}/cards/move"),
            json={'target_column_id': target_column, 'position': 'bottom'},
        )
        assert moved.status_code == 200, moved.text
        assert _ids(_states(authenticated_session, api_client, gid), 'new') == [card_id]

    def test_board_copy_does_not_carry_promotion(
        self, api_client, authenticated_session, global_board, epic
    ):
        """Test copying an epic doesn't promote the copied cards."""
        gid = global_board['id']
        card_id = _make_card(authenticated_session, api_client, epic['column_ids'][0])
        _promote(authenticated_session, api_client, gid, card_id)

        export = authenticated_session.get(_url(api_client, f"/api/boards/{epic['board_id']}/export"))
        assert export.status_code == 200, export.text
        assert 'global' not in export.text.lower()


@pytest.mark.api
class TestAccessIsolation:
    """People only see and change cards on boards they can access."""

    @pytest.fixture
    def admin_card(self, api_client, authenticated_session, global_board, epic):
        card_id = _make_card(authenticated_session, api_client, epic['column_ids'][0], 'Secret')
        _promote(authenticated_session, api_client, global_board['id'], card_id)
        return card_id

    def test_user_without_board_access_sees_nothing(
        self, api_client, second_user_session, global_board, admin_card
    ):
        """Test a user can't see promoted cards from boards they can't access."""
        states = _states(second_user_session, api_client, global_board['id'])
        assert all(not cards for cards in states.values())
        assert 'Secret' not in str(states)

    def test_user_without_board_access_cannot_change_card(
        self, api_client, authenticated_session, second_user_session, global_board, admin_card
    ):
        """Test promote, move and demote are refused for another user's card."""
        gid = global_board['id']
        assert _move(second_user_session, api_client, gid, admin_card, 'done').status_code in (403, 404)
        assert second_user_session.delete(
            _url(api_client, f'/api/global-boards/{gid}/cards/{admin_card}')
        ).status_code in (403, 404)
        assert authenticated_session.delete(
            _url(api_client, f'/api/global-boards/{gid}/cards/{admin_card}')
        ).status_code == 200
        assert _promote(second_user_session, api_client, gid, admin_card).status_code in (403, 404)

    def test_board_viewer_sees_card_read_only(
        self, api_client, authenticated_session, second_user_session, global_board, epic, admin_card
    ):
        """Test a viewer sees the card, marked read-only, and can't move it."""
        user_id = _user_id(second_user_session, api_client)
        role = authenticated_session.post(
            _url(api_client, f'/api/users/{user_id}/roles'),
            json={'role_name': 'board_viewer', 'board_id': epic['board_id']},
        )
        assert role.status_code == 200, role.text

        states = _states(second_user_session, api_client, global_board['id'])
        assert _ids(states, 'new') == [admin_card]
        assert states['new'][0]['can_edit'] is False

        response = _move(second_user_session, api_client, global_board['id'], admin_card, 'waiting')
        assert response.status_code == 403
        assert authenticated_session.get(
            _url(api_client, f'/api/cards/{admin_card}/done')
        ).json()['done'] is False

    def test_board_editor_can_move_card(
        self, api_client, authenticated_session, second_user_session, global_board, epic, admin_card
    ):
        """Test an editor on the epic can move its promoted cards."""
        user_id = _user_id(second_user_session, api_client)
        authenticated_session.post(
            _url(api_client, f'/api/users/{user_id}/roles'),
            json={'role_name': 'board_editor', 'board_id': epic['board_id']},
        )

        response = _move(second_user_session, api_client, global_board['id'], admin_card, 'waiting')
        assert response.status_code == 200, response.text
        assert _ids(_states(authenticated_session, api_client, global_board['id']), 'waiting') == [
            admin_card
        ]

    def test_users_see_only_their_own_cards(
        self, api_client, authenticated_session, second_user_session, global_board, admin_card
    ):
        """Test two users on one global board see different cards, and admins see both."""
        gid = global_board['id']
        _, (column_id,) = _make_board(second_user_session, api_client, 'User epic')
        user_card = _make_card(second_user_session, api_client, column_id, 'Mine')
        assert _promote(second_user_session, api_client, gid, user_card).status_code == 201

        assert _ids(_states(second_user_session, api_client, gid), 'new') == [user_card]
        assert sorted(_ids(_states(authenticated_session, api_client, gid), 'new')) == sorted(
            [admin_card, user_card]
        )

    def test_eligible_list_needs_board_access(
        self, api_client, second_user_session, global_board, epic
    ):
        """Test another user's board can't be queried for eligible global boards."""
        response = second_user_session.get(
            _url(api_client, f"/api/boards/{epic['board_id']}/global-boards")
        )
        assert response.status_code == 403


@pytest.mark.api
class TestFilters:
    """Assignee and epic filters on the card list."""

    def test_filter_by_epic_and_assignee(self, api_client, authenticated_session, global_board, epic):
        """Test board_ids and assignee_ids narrow the list."""
        gid = global_board['id']
        admin_id = _user_id(authenticated_session, api_client)
        mine = _make_card(authenticated_session, api_client, epic['column_ids'][0], 'Mine')
        authenticated_session.put(
            _url(api_client, f'/api/cards/{mine}/assignees'), json={'assigned_to_id': admin_id}
        )
        unassigned = _make_card(authenticated_session, api_client, epic['column_ids'][0], 'Nobody')
        _, (other_column,) = _make_board(authenticated_session, api_client, 'Other epic')
        elsewhere = _make_card(authenticated_session, api_client, other_column, 'Elsewhere')
        for card_id in (mine, unassigned, elsewhere):
            _promote(authenticated_session, api_client, gid, card_id)

        by_epic = _states(authenticated_session, api_client, gid, f"?board_ids={epic['board_id']}")
        assert sorted(_ids(by_epic, 'new')) == sorted([mine, unassigned])

        by_assignee = _states(authenticated_session, api_client, gid, f'?assignee_ids={admin_id}')
        assert _ids(by_assignee, 'new') == [mine]

        response = authenticated_session.get(_url(api_client, f'/api/global-boards/{gid}/cards'))
        epics = {e['name'] for e in response.json()['epics']}
        assert epics == {'Epic', 'Other epic'}


@pytest.mark.api
class TestMenuVisibility:
    """show_in_menu keeps the global board out of kanban-only users' menus."""

    def _show_in_menu(self, session, api_client):
        response = session.get(_url(api_client, '/api/global-boards'))
        assert response.status_code == 200, response.text
        return response.json()['show_in_menu']

    def test_hidden_without_agile_boards_or_cards(self, api_client, second_user_session):
        """Test a user with no boards, then only a kanban board, doesn't get the menu item."""
        assert self._show_in_menu(second_user_session, api_client) is False
        _make_board(second_user_session, api_client, 'Kanban only', style='kanban')
        assert self._show_in_menu(second_user_session, api_client) is False

    def test_shown_with_an_agile_board(self, api_client, second_user_session):
        """Test an agile board brings the menu item."""
        _make_board(second_user_session, api_client, 'Agile epic', style='agile')
        assert self._show_in_menu(second_user_session, api_client) is True

    def test_archived_agile_board_does_not_count(self, api_client, second_user_session):
        """Test an archived agile board doesn't bring the menu item."""
        board_id, _ = _make_board(second_user_session, api_client, 'Old epic', style='agile')
        archive = second_user_session.patch(_url(api_client, f'/api/boards/{board_id}/archive'))
        assert archive.status_code == 200, archive.text
        assert self._show_in_menu(second_user_session, api_client) is False

    def test_shown_with_a_promoted_card_on_a_kanban_board(
        self, api_client, second_user_session, global_board
    ):
        """Test a promoted card keeps the menu item after its board switches to kanban."""
        board_id, (column_id,) = _make_board(second_user_session, api_client, 'Switched epic')
        card_id = _make_card(second_user_session, api_client, column_id)
        assert _promote(second_user_session, api_client, global_board['id'], card_id).status_code == 201
        switch = second_user_session.put(
            _url(api_client, f'/api/boards/{board_id}/settings/working-style'),
            json={'value': 'kanban'},
        )
        assert switch.status_code == 200, switch.text
        assert self._show_in_menu(second_user_session, api_client) is True
