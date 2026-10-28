"""Card WebSocket broadcast payloads (issue #525 item 2.3a).

Card broadcasts carry the card in the same shape as `GET /api/boards/:id/cards`
(`card_data`) and, for changes that renumber sibling cards, the order of every
card in the affected columns (`column_orders`). Clients patch the board from
these payloads instead of refetching it.

A real Socket.IO client connects through nginx with the test session's cookies
and joins the board room. Requests from the test session carry no socket id,
so the server doesn't skip this client when broadcasting.
"""
import queue
import time

import pytest
import socketio

BOARD_CARD_KEYS = {
    "id", "title", "description", "order", "archived", "done", "done_datetime",
    "scheduled", "schedule", "created_at", "updated_at", "assigned_to",
    "checklist_items", "comment_count",
}

EVENT_TIMEOUT_SECONDS = 5


class BoardEvents:
    """Socket.IO client joined to one board room, collecting its events."""

    def __init__(self, base_url, session, board_id):
        self._events = queue.Queue()
        self.client = socketio.Client()
        self.client.on("*", lambda event, data: self._events.put((event, data)))
        cookies = {cookie.name: cookie.value for cookie in session.cookies}
        cookie_header = "; ".join(f"{name}={value}" for name, value in cookies.items())
        self.client.connect(base_url, headers={"Cookie": cookie_header}, transports=["websocket"])
        ack = self.client.call("join_board", {"board_id": board_id}, timeout=EVENT_TIMEOUT_SECONDS)
        assert ack and ack.get("success") is True, f"join_board failed: {ack}"

    def wait_for(self, event_name, card_id=None):
        """Return the next `event_name` payload (for `card_id` if given), skipping others."""
        deadline = time.monotonic() + EVENT_TIMEOUT_SECONDS
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                pytest.fail(f"No {event_name} broadcast received for card {card_id}")
            try:
                event, data = self._events.get(timeout=remaining)
            except queue.Empty:
                continue
            if event == event_name and (card_id is None or data.get("card_id") == card_id):
                return data

    def close(self):
        self.client.disconnect()


@pytest.fixture
def board_events(api_client, authenticated_session, sample_board):
    events = BoardEvents(api_client, authenticated_session, sample_board["id"])
    yield events
    events.close()


@pytest.fixture
def second_column(api_client, authenticated_session, sample_board):
    response = authenticated_session.post(
        f"{api_client}/api/boards/{sample_board['id']}/columns", json={"name": "Second Column"}
    )
    assert response.status_code == 201
    return response.json()["column"]


def _create_card(api_client, session, column_id, title, **extra):
    response = session.post(f"{api_client}/api/columns/{column_id}/cards", json={"title": title, **extra})
    assert response.status_code == 201, response.text
    return response.json()["card"]


def _board_cards(api_client, session, board_id):
    """Return {card_id: (column_id, board card dict)} from the board endpoint, all cards."""
    response = session.get(f"{api_client}/api/boards/{board_id}/cards?archived=both")
    assert response.status_code == 200, response.text
    return {
        card["id"]: (column["id"], card)
        for column in response.json()["board"]["columns"]
        for card in column["cards"]
    }


def _assert_matches_board(api_client, session, board_id, card_data):
    """card_data must carry the board card shape with the same values as a fresh board fetch."""
    assert BOARD_CARD_KEYS <= set(card_data), f"Missing keys: {BOARD_CARD_KEYS - set(card_data)}"
    column_id, board_card = _board_cards(api_client, session, board_id)[card_data["id"]]
    assert {key: card_data[key] for key in board_card} == board_card
    assert card_data["column_id"] == column_id


def _assert_orders_match_board(api_client, session, board_id, column_orders, column_ids):
    """column_orders must hold every card in each column with its current order."""
    assert set(column_orders) == {str(column_id) for column_id in column_ids}
    expected = {str(column_id): {} for column_id in column_ids}
    for card_id, (column_id, card) in _board_cards(api_client, session, board_id).items():
        if str(column_id) in expected:
            expected[str(column_id)][str(card_id)] = card["order"]
    assert column_orders == expected


@pytest.mark.api
class TestCardBroadcastPayloads:

    def test_card_created_carries_board_card_and_column_orders(
        self, api_client, authenticated_session, sample_board, sample_column, board_events
    ):
        first = _create_card(api_client, authenticated_session, sample_column["id"], "First")
        board_events.wait_for("card_created", first["id"])

        # Inserting at the top renumbers the existing card.
        top = _create_card(api_client, authenticated_session, sample_column["id"], "Top", order=0)
        data = board_events.wait_for("card_created", top["id"])

        _assert_matches_board(api_client, authenticated_session, sample_board["id"], data["card_data"])
        assert data["card_data"]["checklist_items"] == []
        assert data["card_data"]["comment_count"] == 0
        assert data["card_data"]["assigned_to"] is None
        _assert_orders_match_board(
            api_client, authenticated_session, sample_board["id"], data["column_orders"], [sample_column["id"]]
        )
        assert data["column_orders"][str(sample_column["id"])] == {str(top["id"]): 0, str(first["id"]): 1}

    def test_card_updated_without_move_has_no_column_orders(
        self, api_client, authenticated_session, sample_board, sample_card, board_events
    ):
        response = authenticated_session.patch(
            f"{api_client}/api/cards/{sample_card['id']}", json={"title": "Renamed"}
        )
        assert response.status_code == 200
        data = board_events.wait_for("card_updated", sample_card["id"])

        assert data["moved"] is False
        assert "column_orders" not in data
        assert data["card_data"]["title"] == "Renamed"
        _assert_matches_board(api_client, authenticated_session, sample_board["id"], data["card_data"])

    def test_card_moved_between_columns_carries_both_column_orders(
        self, api_client, authenticated_session, sample_board, sample_column, second_column, board_events
    ):
        moving = _create_card(api_client, authenticated_session, sample_column["id"], "Moving")
        staying = _create_card(api_client, authenticated_session, sample_column["id"], "Staying")
        target = _create_card(api_client, authenticated_session, second_column["id"], "Target")

        response = authenticated_session.patch(
            f"{api_client}/api/cards/{moving['id']}", json={"column_id": second_column["id"], "order": 0}
        )
        assert response.status_code == 200
        data = board_events.wait_for("card_updated", moving["id"])

        assert data["moved"] is True
        assert data["old_column_id"] == sample_column["id"]
        assert data["column_id"] == second_column["id"]
        _assert_matches_board(api_client, authenticated_session, sample_board["id"], data["card_data"])
        _assert_orders_match_board(
            api_client, authenticated_session, sample_board["id"], data["column_orders"],
            [sample_column["id"], second_column["id"]],
        )
        assert data["column_orders"][str(sample_column["id"])] == {str(staying["id"]): 0}
        assert data["column_orders"][str(second_column["id"])] == {str(moving["id"]): 0, str(target["id"]): 1}

    def test_card_reordered_within_column_carries_column_orders(
        self, api_client, authenticated_session, sample_board, sample_column, board_events
    ):
        first = _create_card(api_client, authenticated_session, sample_column["id"], "First")
        second = _create_card(api_client, authenticated_session, sample_column["id"], "Second")

        response = authenticated_session.patch(f"{api_client}/api/cards/{second['id']}", json={"order": 0})
        assert response.status_code == 200
        data = board_events.wait_for("card_updated", second["id"])

        assert data["moved"] is True
        assert data["old_column_id"] == sample_column["id"]
        assert data["column_orders"] == {
            str(sample_column["id"]): {str(second["id"]): 0, str(first["id"]): 1}
        }

    def test_card_moved_from_another_board_omits_source_column(
        self, api_client, authenticated_session, sample_board, sample_column, board_events
    ):
        """The target board's room must not receive the source board's column or card orders."""
        response = authenticated_session.post(f"{api_client}/api/boards", json={"name": "Source Board"})
        assert response.status_code == 201
        source_board = response.json()["board"]
        response = authenticated_session.post(
            f"{api_client}/api/boards/{source_board['id']}/columns", json={"name": "Source Column"}
        )
        assert response.status_code == 201
        source_column = response.json()["column"]
        moving = _create_card(api_client, authenticated_session, source_column["id"], "Moving")
        _create_card(api_client, authenticated_session, source_column["id"], "Left behind")

        response = authenticated_session.patch(
            f"{api_client}/api/cards/{moving['id']}", json={"column_id": sample_column["id"], "order": 0}
        )
        assert response.status_code == 200, response.text
        data = board_events.wait_for("card_updated", moving["id"])

        assert data["moved"] is True
        assert "old_column_id" not in data
        assert data["column_orders"] == {str(sample_column["id"]): {str(moving["id"]): 0}}

    def test_card_archived_and_unarchived(
        self, api_client, authenticated_session, sample_board, sample_card, board_events
    ):
        response = authenticated_session.patch(f"{api_client}/api/cards/{sample_card['id']}/archive")
        assert response.status_code == 200
        archived = board_events.wait_for("card_archived", sample_card["id"])
        assert archived["card_data"]["archived"] is True
        _assert_matches_board(api_client, authenticated_session, sample_board["id"], archived["card_data"])

        response = authenticated_session.patch(f"{api_client}/api/cards/{sample_card['id']}/unarchive")
        assert response.status_code == 200
        unarchived = board_events.wait_for("card_unarchived", sample_card["id"])
        assert unarchived["card_data"]["archived"] is False
        _assert_matches_board(api_client, authenticated_session, sample_board["id"], unarchived["card_data"])
        _assert_orders_match_board(
            api_client, authenticated_session, sample_board["id"], unarchived["column_orders"],
            [sample_card["column_id"]],
        )

    def test_card_done_status_changed_carries_board_card(
        self, api_client, authenticated_session, sample_board, sample_card, board_events
    ):
        response = authenticated_session.patch(
            f"{api_client}/api/cards/{sample_card['id']}/done", json={"done": True}
        )
        assert response.status_code == 200
        data = board_events.wait_for("card_done_status_changed", sample_card["id"])
        assert data["done"] is True
        assert data["card_data"]["done"] is True
        _assert_matches_board(api_client, authenticated_session, sample_board["id"], data["card_data"])

    def test_card_data_includes_assignee_and_comment_count(
        self, api_client, authenticated_session, sample_board, sample_card, board_events
    ):
        me = authenticated_session.get(f"{api_client}/api/auth/me").json()["user"]
        response = authenticated_session.put(
            f"{api_client}/api/cards/{sample_card['id']}/assignees",
            json={"assigned_to_id": me["id"], "secondary_assignee_ids": []},
        )
        assert response.status_code == 200, response.text
        response = authenticated_session.post(
            f"{api_client}/api/cards/{sample_card['id']}/comments", json={"comment": "A comment"}
        )
        assert response.status_code == 201, response.text

        response = authenticated_session.patch(
            f"{api_client}/api/cards/{sample_card['id']}", json={"description": "Changed"}
        )
        assert response.status_code == 200
        data = board_events.wait_for("card_updated", sample_card["id"])

        assert data["card_data"]["assigned_to"]["id"] == me["id"]
        assert data["card_data"]["comment_count"] == 1
        _assert_matches_board(api_client, authenticated_session, sample_board["id"], data["card_data"])


@pytest.mark.api
class TestChecklistBroadcastPayloads:

    def test_checklist_item_events_carry_updated_card(
        self, api_client, authenticated_session, sample_board, sample_card, board_events
    ):
        response = authenticated_session.post(
            f"{api_client}/api/cards/{sample_card['id']}/checklist-items", json={"name": "Item"}
        )
        assert response.status_code == 201, response.text
        item_id = response.json()["checklist_item"]["id"]
        added = board_events.wait_for("checklist_item_added", sample_card["id"])
        assert added["item_id"] == item_id
        assert [item["id"] for item in added["card_data"]["checklist_items"]] == [item_id]
        _assert_matches_board(api_client, authenticated_session, sample_board["id"], added["card_data"])

        response = authenticated_session.patch(
            f"{api_client}/api/checklist-items/{item_id}", json={"checked": True}
        )
        assert response.status_code == 200
        updated = board_events.wait_for("checklist_item_updated", sample_card["id"])
        assert updated["card_data"]["checklist_items"][0]["checked"] is True
        _assert_matches_board(api_client, authenticated_session, sample_board["id"], updated["card_data"])

        response = authenticated_session.delete(f"{api_client}/api/checklist-items/{item_id}")
        assert response.status_code == 200
        deleted = board_events.wait_for("checklist_item_deleted", sample_card["id"])
        assert deleted["item_id"] == item_id
        assert deleted["card_data"]["checklist_items"] == []
        _assert_matches_board(api_client, authenticated_session, sample_board["id"], deleted["card_data"])
