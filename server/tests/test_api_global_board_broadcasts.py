"""Global board real-time updates (#663).

Promote, demote, move and settings changes send a contentless
global_board_changed to the global_board_<id> room, and clients refetch through
the scoped API. A move into or out of Done also sends the done route's
card_done_status_changed to the epic board's room, and promote, demote and
other moves send card_updated there, so the epic board's badge updates.

A real Socket.IO client connects through nginx with the test session's
cookies. Requests from the test session carry no socket id, so the server
doesn't skip this client when broadcasting.
"""
import queue
import time

import pytest
import socketio

EVENT_TIMEOUT_SECONDS = 5
QUIET_SECONDS = 1


def _url(api_client, path):
    return f'{api_client}{path}'


class RoomEvents:
    """Socket.IO client that collects every event it receives."""

    def __init__(self, base_url, session):
        self._events = queue.Queue()
        self.client = socketio.Client()
        self.client.on('*', lambda event, data: self._events.put((event, data)))
        cookie_header = '; '.join(f'{cookie.name}={cookie.value}' for cookie in session.cookies)
        self.client.connect(base_url, headers={'Cookie': cookie_header}, transports=['websocket'])

    def call(self, event, data):
        return self.client.call(event, data, timeout=EVENT_TIMEOUT_SECONDS)

    def wait_for(self, event_name, timeout=EVENT_TIMEOUT_SECONDS):
        """Return the next `event_name` payload, skipping others, or None on timeout."""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                event, data = self._events.get(timeout=remaining)
            except queue.Empty:
                return None
            if event == event_name:
                return data

    def expect(self, event_name):
        data = self.wait_for(event_name)
        assert data is not None, f'No {event_name} broadcast received'
        return data

    def close(self):
        self.client.disconnect()


@pytest.fixture
def global_board_id(api_client, authenticated_session):
    response = authenticated_session.get(_url(api_client, '/api/global-boards'))
    assert response.status_code == 200, response.text
    board_id = response.json()['global_boards'][0]['id']
    yield board_id
    authenticated_session.patch(
        _url(api_client, f'/api/global-boards/{board_id}'),
        json={'name': 'Global', 'done_visible_days': 14},
    )


@pytest.fixture
def epic_card(api_client, authenticated_session):
    """An agile board with one card. Returns (board_id, card_id)."""
    board = authenticated_session.post(_url(api_client, '/api/boards'), json={'name': 'Epic'})
    assert board.status_code == 201, board.text
    board_id = board.json()['board']['id']
    style = authenticated_session.put(
        _url(api_client, f'/api/boards/{board_id}/settings/working-style'), json={'value': 'agile'}
    )
    assert style.status_code == 200, style.text
    column = authenticated_session.post(
        _url(api_client, f'/api/boards/{board_id}/columns'), json={'name': 'Feature'}
    )
    assert column.status_code == 201, column.text
    card = authenticated_session.post(
        _url(api_client, f"/api/columns/{column.json()['column']['id']}/cards"), json={'title': 'Story'}
    )
    assert card.status_code == 201, card.text
    return board_id, card.json()['card']['id']


@pytest.fixture
def events(api_client, authenticated_session):
    client = RoomEvents(api_client, authenticated_session)
    yield client
    client.close()


@pytest.mark.api
class TestGlobalBoardRoom:

    def test_join_validates_the_global_board(self, events, global_board_id):
        """Test joining needs a real global board id."""
        ack = events.call('join_global_board', {'global_board_id': global_board_id})
        assert ack == {'success': True, 'global_board_id': global_board_id}

        assert events.call('join_global_board', {'global_board_id': 999999})['success'] is False
        for payload in ({}, {'global_board_id': 'x'}, {'global_board_id': 0}, {'global_board_id': True}, 'bad'):
            assert events.call('join_global_board', payload)['success'] is False

    def test_promote_move_demote_broadcast_without_card_content(
        self, api_client, authenticated_session, events, global_board_id, epic_card
    ):
        """Test each change sends global_board_changed carrying only the board id."""
        _, card_id = epic_card
        events.call('join_global_board', {'global_board_id': global_board_id})
        expected = {'global_board_id': global_board_id}

        promote = authenticated_session.post(
            _url(api_client, f'/api/global-boards/{global_board_id}/cards'), json={'card_id': card_id}
        )
        assert promote.status_code == 201, promote.text
        assert events.expect('global_board_changed') == expected

        move = authenticated_session.patch(
            _url(api_client, f'/api/global-boards/{global_board_id}/cards/{card_id}'),
            json={'state': 'in_progress'},
        )
        assert move.status_code == 200, move.text
        assert events.expect('global_board_changed') == expected

        demote = authenticated_session.delete(
            _url(api_client, f'/api/global-boards/{global_board_id}/cards/{card_id}')
        )
        assert demote.status_code == 200, demote.text
        assert events.expect('global_board_changed') == expected

    def test_settings_change_broadcasts(self, api_client, authenticated_session, events, global_board_id):
        """Test a rename tells viewers to refetch."""
        events.call('join_global_board', {'global_board_id': global_board_id})
        response = authenticated_session.patch(
            _url(api_client, f'/api/global-boards/{global_board_id}'), json={'name': 'Sprint'}
        )
        assert response.status_code == 200, response.text
        assert events.expect('global_board_changed') == {'global_board_id': global_board_id}

    def test_not_in_room_gets_nothing(self, api_client, authenticated_session, events, global_board_id, epic_card):
        """Test a client that hasn't joined the room gets no global board events."""
        _, card_id = epic_card
        promote = authenticated_session.post(
            _url(api_client, f'/api/global-boards/{global_board_id}/cards'), json={'card_id': card_id}
        )
        assert promote.status_code == 201, promote.text
        assert events.wait_for('global_board_changed', timeout=QUIET_SECONDS) is None

    def test_left_room_gets_nothing(self, api_client, authenticated_session, events, global_board_id, epic_card):
        """Test leaving the room stops its events."""
        _, card_id = epic_card
        events.call('join_global_board', {'global_board_id': global_board_id})
        ack = events.call('leave_global_board', {'global_board_id': global_board_id})
        assert ack == {'success': True, 'global_board_id': global_board_id}
        promote = authenticated_session.post(
            _url(api_client, f'/api/global-boards/{global_board_id}/cards'), json={'card_id': card_id}
        )
        assert promote.status_code == 201, promote.text
        assert events.wait_for('global_board_changed', timeout=QUIET_SECONDS) is None


@pytest.mark.api
class TestEpicBoardDoneBroadcast:

    def test_moving_into_and_out_of_done_updates_the_epic_board(
        self, api_client, authenticated_session, events, global_board_id, epic_card
    ):
        """Test done changes from the global board reach the epic board's room."""
        board_id, card_id = epic_card
        assert events.call('join_board', {'board_id': board_id})['success'] is True
        promote = authenticated_session.post(
            _url(api_client, f'/api/global-boards/{global_board_id}/cards'), json={'card_id': card_id}
        )
        assert promote.status_code == 201, promote.text
        move_url = _url(api_client, f'/api/global-boards/{global_board_id}/cards/{card_id}')

        # A move between open states doesn't change done.
        assert authenticated_session.patch(move_url, json={'state': 'waiting'}).status_code == 200
        assert events.wait_for('card_done_status_changed', timeout=QUIET_SECONDS) is None

        assert authenticated_session.patch(move_url, json={'state': 'done'}).status_code == 200
        data = events.expect('card_done_status_changed')
        assert data['card_id'] == card_id
        assert data['board_id'] == board_id
        assert data['done'] is True
        assert data['card_data']['done'] is True
        assert data['card_data']['done_datetime'] is not None
        assert data['card_data']['global_state'] == 'done'

        assert authenticated_session.patch(move_url, json={'state': 'new'}).status_code == 200
        data = events.expect('card_done_status_changed')
        assert data['done'] is False
        assert data['card_data']['done_datetime'] is None
        assert data['card_data']['global_state'] == 'new'


@pytest.mark.api
class TestEpicBoardBadgeBroadcast:

    def test_promote_move_demote_update_the_epic_card(
        self, api_client, authenticated_session, events, global_board_id, epic_card
    ):
        """Test the epic board gets card_updated carrying the card's new global state."""
        board_id, card_id = epic_card
        assert events.call('join_board', {'board_id': board_id})['success'] is True
        cards_url = _url(api_client, f'/api/global-boards/{global_board_id}/cards')

        def expect_card(global_state):
            data = events.expect('card_updated')
            assert data['board_id'] == board_id
            assert data['card_id'] == card_id
            card_data = data['card_data']
            assert card_data['id'] == card_id
            assert card_data['global_state'] == global_state
            assert card_data['global_board_id'] == (global_board_id if global_state else None)
            assert str(card_data['column_id']) in data['column_counts']

        promote = authenticated_session.post(cards_url, json={'card_id': card_id})
        assert promote.status_code == 201, promote.text
        expect_card('new')

        move = authenticated_session.patch(f'{cards_url}/{card_id}', json={'state': 'in_progress'})
        assert move.status_code == 200, move.text
        expect_card('in_progress')

        demote = authenticated_session.delete(f'{cards_url}/{card_id}')
        assert demote.status_code == 200, demote.text
        expect_card(None)

    def test_other_board_room_gets_nothing(
        self, api_client, authenticated_session, events, global_board_id, epic_card
    ):
        """Test the badge update goes only to the card's own board."""
        _, card_id = epic_card
        other = authenticated_session.post(_url(api_client, '/api/boards'), json={'name': 'Other'})
        assert other.status_code == 201, other.text
        other_id = other.json()['board']['id']
        assert events.call('join_board', {'board_id': other_id})['success'] is True

        promote = authenticated_session.post(
            _url(api_client, f'/api/global-boards/{global_board_id}/cards'), json={'card_id': card_id}
        )
        assert promote.status_code == 201, promote.text
        assert events.wait_for('card_updated', timeout=QUIET_SECONDS) is None
