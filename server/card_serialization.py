"""Card serialization shared by the board endpoint and card WebSocket broadcasts.

The board view renders cards from `GET /api/boards/<id>/cards`. Card
broadcasts carry the same per-card shape so a client can patch one card in
place instead of refetching the whole board.
"""
from sqlalchemy import case, func

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


def count_cards_by_column(cards_query):
    """Return {column_id: {"total": n, "done": m}} for the cards `cards_query` matches.

    One grouped COUNT; the query's filters decide which cards are counted.
    Columns with no matching cards are absent.
    """
    rows = (
        cards_query.with_entities(
            Card.column_id,
            func.count(Card.id),
            func.sum(case((Card.done.is_(True), 1), else_=0)),
        )
        .group_by(Card.column_id)
        .all()
    )
    return {
        column_id: {"total": int(total), "done": int(done or 0)}
        for column_id, total, done in rows
    }


def _board_column_ids(db, column_ids, board_id):
    """The ids in `column_ids` that belong to `board_id`."""
    requested = {int(column_id) for column_id in column_ids if column_id is not None}
    if not requested:
        return []
    return [
        column_id for (column_id,) in db.query(BoardColumn.id)
        .filter(BoardColumn.id.in_(requested), BoardColumn.board_id == board_id)
        .all()
    ]


def get_column_card_counts(db, column_ids, board_id):
    """Return {"<column_id>": {"total": n, "done": m}} of active cards in each column.

    Active cards are those the board's task view lists: not archived and not
    scheduled templates. Card broadcasts include this map for every column
    whose counts the change can affect, so clients can update column headers
    without holding every card. Only columns on `board_id` are included.
    """
    board_column_ids = _board_column_ids(db, column_ids, board_id)
    if not board_column_ids:
        return {}
    counts = count_cards_by_column(
        db.query(Card).filter(
            Card.column_id.in_(board_column_ids),
            Card.archived.is_(False),
            Card.scheduled.is_(False),
        )
    )
    return {
        str(column_id): counts.get(column_id, {"total": 0, "done": 0})
        for column_id in board_column_ids
    }


def get_column_card_orders(db, column_ids, board_id):
    """Return {"<column_id>": {"<card_id>": order}} for every card in the columns.

    Creating, moving or unarchiving a card renumbers its siblings. Broadcasts
    for those changes include this map so clients can bring every affected
    card's order up to date without refetching the board. Keys are strings
    because the map is sent as JSON.

    Only columns on `board_id` (the board the broadcast goes to) are included,
    so a card moved in from another board doesn't expose that board's cards.
    """
    board_column_ids = _board_column_ids(db, column_ids, board_id)
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
