"""Security regression tests for Socket.IO authentication and authorization."""

import os
import importlib
from types import SimpleNamespace

import pytest

# Unit tests import app module directly, so ensure required startup env vars
# exist before import-time configuration is evaluated.
os.environ.setdefault('ENABLE_SERVER_SIDE_SESSIONS', 'false')
os.environ.setdefault('SECRET_KEY', 'unit-test-secret-key')
os.environ.setdefault('AFT_SKIP_SCHEDULER_INIT', 'true')


_APP_MODULE = None
_WS_MODULE = None


def _get_app_module():
    """Import app lazily to avoid module-import side effects during test collection."""
    global _APP_MODULE
    if _APP_MODULE is None:
        _APP_MODULE = importlib.import_module('app')
    return _APP_MODULE


def _get_ws_module():
    """Import websocket_handlers lazily."""
    global _WS_MODULE
    if _WS_MODULE is None:
        _WS_MODULE = importlib.import_module('websocket_handlers')
    return _WS_MODULE


pytestmark = [pytest.mark.unit, pytest.mark.security]


def _make_socket_client(app_module):
    """Create a Flask-SocketIO test client."""
    flask_client = app_module.app.test_client()
    return app_module.socketio.test_client(app_module.app, flask_test_client=flask_client)


def _ack_payload(ack_response):
    """Normalize Socket.IO callback payload shape for assertions."""
    payload = ack_response
    if isinstance(payload, list) and len(payload) == 1:
        payload = payload[0]

    assert isinstance(payload, dict)
    return payload


class TestWebSocketSecurity:
    """Regression tests for websocket auth and event-injection controls."""

    def test_unauthenticated_socket_connect_is_rejected(self, monkeypatch):
        """Critical #2 regression: unauthenticated Socket.IO connect must fail."""
        app_module = _get_app_module()
        ws_module = _get_ws_module()
        monkeypatch.setattr(ws_module, 'get_authenticated_socket_user', lambda: None)

        client = _make_socket_client(app_module)
        assert client.is_connected() is False

    def test_authenticated_join_board_requires_authorized_access(self, monkeypatch):
        """join_board must enforce server-side board authorization."""
        app_module = _get_app_module()
        ws_module = _get_ws_module()
        user = SimpleNamespace(id=1)
        monkeypatch.setattr(ws_module, 'get_authenticated_socket_user', lambda: user)

        def _mock_can_access_board(user_id, board_id):
            return board_id == 123, False

        monkeypatch.setattr(ws_module, 'can_access_board', _mock_can_access_board)

        client = _make_socket_client(app_module)
        try:
            assert client.is_connected() is True

            allowed_ack = _ack_payload(client.emit('join_board', {'board_id': 123}, callback=True))
            assert allowed_ack['success'] is True
            assert allowed_ack['board_id'] == 123

            denied_ack = _ack_payload(client.emit('join_board', {'board_id': 999}, callback=True))
            assert denied_ack['success'] is False
            assert denied_ack['message'] == 'Access denied to this board'
        finally:
            client.disconnect()

    def test_client_mutation_event_is_rejected_and_not_rebroadcast(self, monkeypatch):
        """Client-emitted mutation events must be rejected by the server."""
        app_module = _get_app_module()
        ws_module = _get_ws_module()
        user = SimpleNamespace(id=1)
        monkeypatch.setattr(ws_module, 'get_authenticated_socket_user', lambda: user)
        monkeypatch.setattr(ws_module, 'can_access_board', lambda user_id, board_id: (True, False))

        sender = _make_socket_client(app_module)
        receiver = _make_socket_client(app_module)
        try:
            assert sender.is_connected() is True
            assert receiver.is_connected() is True

            sender.emit('join_board', {'board_id': 321}, callback=True)
            receiver.emit('join_board', {'board_id': 321}, callback=True)
            receiver.get_received()  # Clear connect/join events before mutation test.

            mutation_ack = _ack_payload(
                sender.emit(
                    'card_updated',
                    {'board_id': 321, 'card_id': 77, 'title': 'spoofed'},
                    callback=True,
                )
            )
            assert mutation_ack['success'] is False
            assert mutation_ack['event'] == 'card_updated'

            broadcast_events = [
                event for event in receiver.get_received() if event.get('name') == 'card_updated'
            ]
            assert broadcast_events == []
        finally:
            sender.disconnect()
            receiver.disconnect()

    def test_join_global_board_requires_access(self, monkeypatch):
        """join_global_board must go through the global board access check (#663)."""
        app_module = _get_app_module()
        ws_module = _get_ws_module()
        user = SimpleNamespace(id=1)
        monkeypatch.setattr(ws_module, 'get_authenticated_socket_user', lambda: user)
        checked = []

        def _mock_access(user_id, global_board_id):
            checked.append((user_id, global_board_id))
            return global_board_id == 5

        monkeypatch.setattr(ws_module, '_can_access_global_board', _mock_access)

        client = _make_socket_client(app_module)
        try:
            allowed_ack = _ack_payload(client.emit('join_global_board', {'global_board_id': 5}, callback=True))
            assert allowed_ack == {'success': True, 'global_board_id': 5}

            denied_ack = _ack_payload(client.emit('join_global_board', {'global_board_id': 6}, callback=True))
            assert denied_ack['success'] is False
            assert denied_ack['message'] == 'Access denied to this global board'
            assert checked == [(1, 5), (1, 6)]
        finally:
            client.disconnect()
