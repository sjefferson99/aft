"""Card serialization shared by the board endpoint and card WebSocket broadcasts.

The board view renders cards from `GET /api/boards/<id>/cards`. Card
broadcasts carry the same per-card shape so a client can patch one card in
place instead of refetching the whole board.
"""
from sqlalchemy import func

from datetime_helpers import serialize_datetime
from models import BoardColumn, Card, Comment


def serialize_board_card(card, comment_count):
    """Serialize a card as the board view renders it.

    Callers serializing many cards should eager-load `assigned_to` and
    `checklist_items` (selectinload) to avoid per-card queries.
    """
    return {
        "id": card.id,
        "title": card.title,
        "description": card.description,
        "order": card.order,
        "archived": card.archived,
        "done": card.done,
        "done_datetime": serialize_datetime(card.done_datetime),
        "scheduled": card.scheduled,
        "schedule": card.schedule,
        "created_at": serialize_datetime(card.created_at),
        "updated_at": serialize_datetime(card.updated_at),
        "assigned_to": {
            "id": card.assigned_to.id,
            "display_name": card.assigned_to.display_name,
            "username": card.assigned_to.username,
            "profile_colour": card.assigned_to.profile_colour,
        } if card.assigned_to else None,
        "checklist_items": [
            {
                "id": item.id,
                "card_id": item.card_id,
                "name": item.name,
                "checked": item.checked,
                "order": item.order,
                "created_at": serialize_datetime(item.created_at),
                "updated_at": serialize_datetime(item.updated_at)
            }
            for item in card.checklist_items
        ],
        "comment_count": comment_count,
    }


def get_comment_counts(db, card_ids):
    """Return {card_id: comment count} using one grouped COUNT query."""
    if not card_ids:
        return {}
    return dict(
        db.query(Comment.card_id, func.count(Comment.id))
        .filter(Comment.card_id.in_(card_ids))
        .group_by(Comment.card_id)
        .all()
    )


def build_card_broadcast_data(db, card):
    """Serialize one card for a card WebSocket broadcast's `card_data`.

    The board card shape plus `column_id`, `start_date` and `end_date`, which
    earlier broadcast payloads carried and existing listeners may read.
    """
    data = serialize_board_card(card, get_comment_counts(db, [card.id]).get(card.id, 0))
    data["column_id"] = card.column_id
    data["start_date"] = serialize_datetime(card.start_date)
    data["end_date"] = serialize_datetime(card.end_date)
    return data


def get_column_card_orders(db, column_ids, board_id):
    """Return {"<column_id>": {"<card_id>": order}} for every card in the columns.

    Creating, moving or unarchiving a card renumbers its siblings. Broadcasts
    for those changes include this map so clients can bring every affected
    card's order up to date without refetching the board. Keys are strings
    because the map is sent as JSON.

    Only columns on `board_id` (the board the broadcast goes to) are included,
    so a card moved in from another board doesn't expose that board's cards.
    """
    requested = {int(column_id) for column_id in column_ids if column_id is not None}
    if not requested:
        return {}
    board_column_ids = [
        column_id for (column_id,) in db.query(BoardColumn.id)
        .filter(BoardColumn.id.in_(requested), BoardColumn.board_id == board_id)
        .all()
    ]
    orders = {str(column_id): {} for column_id in board_column_ids}
    if not orders:
        return orders
    rows = (
        db.query(Card.column_id, Card.id, Card.order)
        .filter(Card.column_id.in_(board_column_ids))
        .all()
    )
    for column_id, card_id, order in rows:
        orders[str(column_id)][str(card_id)] = order
    return orders
