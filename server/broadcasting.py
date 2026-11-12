"""WebSocket broadcast helpers and failure tracking.

broadcast_event and broadcast_theme_event are instantiated by calling
configure_broadcasting(socketio_instance) from app.py after SocketIO is created.
The returned (broadcast_event, broadcast_theme_event) callables are then injected
into route blueprints via their configure_* functions.
"""

import logging
import threading

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thread-safe broadcast failure tracking
# ---------------------------------------------------------------------------
# Format: {room_name: {event_name: error_message}}
# Protected by lock for concurrent access in multi-worker/multi-threaded environment.
# IMPORTANT: All access must occur within a "with broadcast_failures_lock:" block.
broadcast_failures: dict = {}
broadcast_failures_lock = threading.Lock()


def record_broadcast_failure(room_name: str, event_name: str, error_message: str) -> None:
    """Thread-safe helper to record a broadcast failure."""
    with broadcast_failures_lock:
        if room_name not in broadcast_failures:
            broadcast_failures[room_name] = {}
        broadcast_failures[room_name][event_name] = error_message


def clear_broadcast_failure(room_name: str, event_name: str) -> None:
    """Thread-safe helper to clear a broadcast failure record."""
    with broadcast_failures_lock:
        if room_name in broadcast_failures:
            broadcast_failures[room_name].pop(event_name, None)


# ---------------------------------------------------------------------------
# Factory — call once from app.py after creating SocketIO
# ---------------------------------------------------------------------------

def configure_broadcasting(socketio_instance):
    """Create and return broadcast callables bound to a SocketIO instance.

    Returns:
        (broadcast_event, broadcast_theme_event, broadcast_global_board_event)
        — callables ready to be injected into route blueprints.
    """

    def broadcast_global_board_event(event_name, data, global_board_id, skip_sid=None):
        """Broadcast a WebSocket event to everyone viewing a global board (#663).

        Global board events carry no card content, because people on the same
        global board can see different cards. Clients refetch through the
        scoped API instead.
        """
        room_name = f'global_board_{global_board_id}'

        def do_emit():
            try:
                socketio_instance.emit(event_name, data, room=room_name, skip_sid=skip_sid, namespace='/')
                clear_broadcast_failure(room_name, event_name)
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Error broadcasting {event_name} to {room_name}: {error_msg}")
                record_broadcast_failure(room_name, event_name, error_msg)

        socketio_instance.start_background_task(do_emit)

    def broadcast_event(event_name, data, board_id, skip_sid=None):
        """Broadcast a WebSocket event to all clients in a board room.

        Args:
            event_name: Name of the event to broadcast
            data: Event data to send
            board_id: Board ID to broadcast to (determines the room)
            skip_sid: Optional Socket.IO session ID to exclude from broadcast

        Note: Broadcasts happen asynchronously in background tasks. Failures are
        logged but do not affect the API response. Clients should implement refresh
        logic as a fallback (e.g., client reloads board on reconnection).
        """
        room_name = f'board_{board_id}'

        def do_emit():
            try:
                logger.info(f"Broadcasting {event_name} to room {room_name} with data: {data}")
                socketio_instance.emit(event_name, data, room=room_name, skip_sid=skip_sid, namespace='/')
                logger.info(f"✓ Successfully emitted {event_name}")
                clear_broadcast_failure(room_name, event_name)
            except Exception as e:
                error_msg = str(e)
                logger.error(f"❌ Error broadcasting {event_name} to {room_name}: {error_msg}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                record_broadcast_failure(room_name, event_name, error_msg)

        socketio_instance.start_background_task(do_emit)

    def broadcast_theme_event(event_name, data, user_id=None):
        """Broadcast a WebSocket event to theme subscribers.

        When user_id is provided, emit only to that user's theme room.
        Otherwise, emit to the shared theme room for global theme events.

        Note: Broadcasts happen asynchronously in background tasks. Failures are
        logged but do not affect the API response. Clients should implement refresh
        logic as fallback.
        """
        room_name = f'theme_user_{user_id}' if user_id is not None else 'theme'

        def do_emit():
            try:
                logger.info(f"📢 Broadcasting {event_name} to room {room_name} with data: {data}")
                socketio_instance.emit(event_name, data, room=room_name, namespace='/')
                logger.info(f"✓ Successfully emitted {event_name} to room {room_name}")
                clear_broadcast_failure(room_name, event_name)
            except Exception as e:
                error_msg = str(e)
                logger.error(f"✗ Error broadcasting {event_name} to room {room_name}: {error_msg}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                record_broadcast_failure(room_name, event_name, error_msg)

        socketio_instance.start_background_task(do_emit)

    return broadcast_event, broadcast_theme_event, broadcast_global_board_event
