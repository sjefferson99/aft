"""Global board routes blueprint (#663).

A global board lists cards promoted from agile boards by state:
  GET            /api/global-boards
  PATCH          /api/global-boards/<id>
  GET            /api/global-boards/<id>/cards
  POST           /api/global-boards/<id>/cards
  PATCH/DELETE   /api/global-boards/<id>/cards/<card_id>
  GET            /api/boards/<board_id>/global-boards

Two checks apply to every request: the global board must pass
can_access_global_board, and each card must be on a board the user can access
(get_user_scoped_query). Changing a card needs card.update on its own board, as
the done route does.

Changes broadcast a contentless global_board_changed to the global_board_<id>
room, and clients refetch through the scoped API, so no card content reaches
people who can't see the card's board.
"""
import logging
from datetime import timedelta

from flask import Blueprint, g, jsonify, request
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from board_routes import (
    _apply_assignee_card_filters,
    _parse_assignee_ids_query_param,
    _user_summary,
)
from card_serialization import build_card_broadcast_data, get_column_card_counts
from database import SessionLocal
from datetime_helpers import serialize_datetime, utc_now
from global_board_utils import (
    DONE_VISIBLE_DAYS_MAX,
    DONE_VISIBLE_DAYS_MIN,
    GLOBAL_BOARD_NAME_MAX_LENGTH,
    GLOBAL_STATE_DONE,
    GLOBAL_STATE_NEW,
    GLOBAL_STATES,
    GLOBAL_STORED_STATES,
    apply_card_done,
    get_accessible_global_board,
    get_accessible_global_boards,
    get_card_promotion,
    get_eligible_global_boards,
)
from models import Board, BoardColumn, BoardSetting, Card, GlobalBoardCard
from permissions import has_permission
from settings_schema import (
    WORKING_STYLE_AGILE,
    normalize_working_style,
    parse_json_setting_value,
)
from utils import (
    create_error_response,
    get_request_socket_id,
    get_user_permissions,
    get_user_scoped_query,
    require_authentication,
    require_board_access,
    require_permission,
    sanitize_string,
    validate_integer,
)

logger = logging.getLogger(__name__)

global_board_bp = Blueprint("global_board", __name__)

GLOBAL_BOARD_NOT_FOUND = "Global board not found"
CARD_NOT_FOUND = "Card not found"
GLOBAL_BOARD_CHANGED_EVENT = "global_board_changed"

# Injected at startup via configure_global_board_routes()
_broadcast_event = None
_broadcast_global_board_event = None


def configure_global_board_routes(broadcast_event_fn, broadcast_global_board_event_fn):
    """Inject the board and global board broadcast callables."""
    global _broadcast_event, _broadcast_global_board_event
    _broadcast_event = broadcast_event_fn
    _broadcast_global_board_event = broadcast_global_board_event_fn


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _notify_global_board_changed(global_board_id):
    """Tell everyone viewing a global board to refetch it. Carries only the id."""
    if _broadcast_global_board_event is None:
        return
    _broadcast_global_board_event(
        GLOBAL_BOARD_CHANGED_EVENT,
        {"global_board_id": global_board_id},
        global_board_id,
        get_request_socket_id(),
    )


def _notify_card_done_changed(db, card, board_id):
    """Send the done route's board event after a global move changes done."""
    if _broadcast_event is None or not board_id:
        return
    _broadcast_event('card_done_status_changed', {
        'board_id': board_id,
        'card_id': card.id,
        'column_id': card.column_id,
        'done': bool(card.done),
        'card_data': build_card_broadcast_data(db, card),
        'column_counts': get_column_card_counts(db, [card.column_id], board_id),
    }, board_id, get_request_socket_id())


def _notify_epic_card_changed(db, card, board_id):
    """Send card_updated to the card's own board so its global badge updates.

    Promote, demote and global moves change only global_board_id and
    global_state in the board card, and the epic board patches the card in
    place from this event.
    """
    if _broadcast_event is None or not board_id:
        return
    _broadcast_event('card_updated', {
        'board_id': board_id,
        'card_id': card.id,
        'column_id': card.column_id,
        'card_data': build_card_broadcast_data(db, card),
        'column_counts': get_column_card_counts(db, [card.column_id], board_id),
    }, board_id, get_request_socket_id())


def _user_has_agile_board(db, user_id):
    """Return whether the user can see an active agile board."""
    board_ids = [
        board_id
        for (board_id,) in get_user_scoped_query(db, Board, user_id)
        .filter(Board.archived.is_(False))
        .with_entities(Board.id)
        .all()
    ]
    if not board_ids:
        return False
    settings = db.query(BoardSetting.value).filter(
        BoardSetting.board_id.in_(board_ids),
        BoardSetting.key == 'working_style',
    ).all()
    return any(
        normalize_working_style(parse_json_setting_value(raw_value)) == WORKING_STYLE_AGILE
        for (raw_value,) in settings
    )


def _user_has_promoted_card(db, user_id, global_board_ids):
    """Return whether the user can see a card promoted to one of these boards."""
    if not global_board_ids:
        return False
    return db.query(GlobalBoardCard.id).filter(
        GlobalBoardCard.global_board_id.in_(global_board_ids),
        GlobalBoardCard.card_id.in_(_scoped_card_ids(db, user_id)),
    ).first() is not None


def _serialize_global_board(global_board, user_permissions):
    return {
        "id": global_board.id,
        "name": global_board.name,
        "visibility": global_board.visibility,
        "done_visible_days": global_board.done_visible_days,
        "can_manage": has_permission(user_permissions, 'global_board.manage'),
    }


def _scoped_card_ids(db, user_id):
    """Subquery of the card ids the user can see, for use in IN filters."""
    return get_user_scoped_query(db, Card, user_id).with_entities(Card.id)


def _get_scoped_card(db, user_id, card_id):
    return get_user_scoped_query(db, Card, user_id).filter(Card.id == card_id).first()


def _global_state(card, promotion):
    return GLOBAL_STATE_DONE if card.done else promotion.state


def _can_edit_board(user_id, board_id, cache):
    if board_id not in cache:
        cache[board_id] = has_permission(get_user_permissions(user_id, board_id), 'card.update')
    return cache[board_id]


def _serialize_global_card(card, promotion, column, board, can_edit):
    assigned_to = card.assigned_to
    return {
        "card_id": card.id,
        "title": card.title,
        "state": _global_state(card, promotion),
        "stored_state": promotion.state,
        "order": promotion.order,
        "done": bool(card.done),
        "done_datetime": serialize_datetime(card.done_datetime),
        "promoted_at": serialize_datetime(promotion.promoted_at),
        "assigned_to": _user_summary(assigned_to) if assigned_to else None,
        "secondary_assignees": [
            _user_summary(entry.user) for entry in card.secondary_assignees if entry.user
        ],
        "board_id": board.id,
        "board_name": board.name,
        "column_id": column.id,
        "column_name": column.name,
        "can_edit": can_edit,
    }


def _next_order(db, global_board_id, state):
    max_order = db.query(func.max(GlobalBoardCard.order)).filter(
        GlobalBoardCard.global_board_id == global_board_id,
        GlobalBoardCard.state == state,
    ).scalar()
    return 0 if max_order is None else int(max_order) + 1


def _place_card(db, promotion, state, after_promotion):
    """Put a promotion in a state, straight after another one or at the top.

    Orders are shifted across the whole state, including cards this user can't
    see, so the result is the same whoever looks at the board.
    """
    if after_promotion is None:
        target_order = db.query(func.min(GlobalBoardCard.order)).filter(
            GlobalBoardCard.global_board_id == promotion.global_board_id,
            GlobalBoardCard.state == state,
            GlobalBoardCard.id != promotion.id,
        ).scalar()
        target_order = 0 if target_order is None else int(target_order)
    else:
        target_order = after_promotion.order + 1

    db.query(GlobalBoardCard).filter(
        GlobalBoardCard.global_board_id == promotion.global_board_id,
        GlobalBoardCard.state == state,
        GlobalBoardCard.order >= target_order,
        GlobalBoardCard.id != promotion.id,
    ).update({GlobalBoardCard.order: GlobalBoardCard.order + 1}, synchronize_session=False)

    promotion.state = state
    promotion.order = target_order


# ---------------------------------------------------------------------------
# Global boards
# ---------------------------------------------------------------------------


@global_board_bp.route("/api/global-boards", methods=["GET"])
@require_authentication
def list_global_boards():
    """List the global boards the current user can see.
    ---
    tags:
      - Global Boards
    security:
      - session: []
    responses:
      200:
        description: >
          Global boards with their name and done window. show_in_menu is true when
          the user can see a global board and has an agile board or a promoted
          card, so people who only use kanban boards don't see the global board
      401:
        description: Authentication required
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        user_permissions = get_user_permissions(g.user.id)
        boards = get_accessible_global_boards(db, g.user.id)
        show_in_menu = bool(boards) and (
            _user_has_agile_board(db, g.user.id)
            or _user_has_promoted_card(db, g.user.id, [b.id for b in boards])
        )
        return jsonify({
            "success": True,
            "global_boards": [_serialize_global_board(b, user_permissions) for b in boards],
            "show_in_menu": show_in_menu,
        }), 200
    except Exception as e:
        logger.error(f"Error listing global boards: {str(e)}")
        return create_error_response("Failed to list global boards", 500)
    finally:
        db.close()


@global_board_bp.route("/api/global-boards/<int:global_board_id>", methods=["PATCH"])
@require_permission('global_board.manage', require_board_context=False)
def update_global_board(global_board_id):
    """Rename a global board or change how long done cards show.
    ---
    tags:
      - Global Boards
    security:
      - session: []
    parameters:
      - name: global_board_id
        in: path
        required: true
        type: integer
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            name:
              type: string
              maxLength: 100
            done_visible_days:
              type: integer
              minimum: 1
              maximum: 3650
              x-nullable: true
              description: Days a done card stays listed. Null shows done cards always
    responses:
      200:
        description: Global board updated
      400:
        description: Invalid fields
      403:
        description: Insufficient permissions
      404:
        description: Global board not found
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not ({"name", "done_visible_days"} & data.keys()):
            return create_error_response("name or done_visible_days is required", 400)

        global_board = get_accessible_global_board(db, g.user.id, global_board_id)
        if global_board is None:
            return create_error_response(GLOBAL_BOARD_NOT_FOUND, 404)

        if "name" in data:
            name = data["name"]
            if not isinstance(name, str):
                return create_error_response("name must be a string", 400)
            name = sanitize_string(name)
            if not name:
                return create_error_response("name cannot be empty", 400)
            if len(name) > GLOBAL_BOARD_NAME_MAX_LENGTH:
                return create_error_response(
                    f"name exceeds maximum length of {GLOBAL_BOARD_NAME_MAX_LENGTH} characters",
                    400,
                )
            global_board.name = name

        if "done_visible_days" in data:
            days = data["done_visible_days"]
            is_valid, error = validate_integer(
                days,
                "done_visible_days",
                min_value=DONE_VISIBLE_DAYS_MIN,
                max_value=DONE_VISIBLE_DAYS_MAX,
                allow_none=True,
            )
            if not is_valid:
                return create_error_response(error, 400)
            global_board.done_visible_days = days

        global_board.updated_at = utc_now()
        db.commit()
        db.refresh(global_board)
        _notify_global_board_changed(global_board.id)

        return jsonify({
            "success": True,
            "global_board": _serialize_global_board(
                global_board, get_user_permissions(g.user.id)
            ),
        }), 200
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating global board {global_board_id}: {str(e)}")
        return create_error_response("Failed to update global board", 500)
    finally:
        db.close()


@global_board_bp.route("/api/boards/<int:board_id>/global-boards", methods=["GET"])
@require_board_access()
@require_permission('board.view')
def list_board_eligible_global_boards(board_id):
    """List the global boards this board's cards can be promoted to.
    ---
    tags:
      - Global Boards
    security:
      - session: []
    parameters:
      - name: board_id
        in: path
        required: true
        type: integer
    responses:
      200:
        description: Eligible global boards. Empty for kanban boards
      403:
        description: Access denied to this board
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        user_permissions = get_user_permissions(g.user.id)
        boards = get_eligible_global_boards(db, board_id, g.user.id)
        return jsonify({
            "success": True,
            "global_boards": [_serialize_global_board(b, user_permissions) for b in boards],
        }), 200
    except Exception as e:
        logger.error(f"Error listing eligible global boards for board {board_id}: {str(e)}")
        return create_error_response("Failed to list global boards", 500)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Promoted cards
# ---------------------------------------------------------------------------


@global_board_bp.route("/api/global-boards/<int:global_board_id>/cards", methods=["GET"])
@require_authentication
def list_global_board_cards(global_board_id):
    """List the promoted cards the current user can see, grouped by state.
    ---
    tags:
      - Global Boards
    security:
      - session: []
    parameters:
      - name: global_board_id
        in: path
        required: true
        type: integer
      - name: assignee_ids
        in: query
        type: string
        description: Comma-separated user ids. Matches primary and secondary assignees
      - name: include_unassigned
        in: query
        type: string
        enum: ['true', 'false']
      - name: board_ids
        in: query
        type: string
        description: Comma-separated epic (board) ids
    responses:
      200:
        description: >
          Cards grouped by state. Done cards older than the board's done window are
          left out, and the Done list is newest first
      404:
        description: Global board not found
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        user_id = g.user.id
        global_board = get_accessible_global_board(db, user_id, global_board_id)
        if global_board is None:
            return create_error_response(GLOBAL_BOARD_NOT_FOUND, 404)

        assignee_ids = _parse_assignee_ids_query_param(request.args.get('assignee_ids'))
        include_unassigned = request.args.get('include_unassigned', 'false').lower() == 'true'
        board_ids = _parse_assignee_ids_query_param(request.args.get('board_ids'))

        query = (
            db.query(GlobalBoardCard, Card, BoardColumn, Board)
            .join(Card, GlobalBoardCard.card_id == Card.id)
            .join(BoardColumn, Card.column_id == BoardColumn.id)
            .join(Board, BoardColumn.board_id == Board.id)
            .filter(
                GlobalBoardCard.global_board_id == global_board.id,
                Card.id.in_(_scoped_card_ids(db, user_id)),
                Card.archived.is_(False),
                Card.scheduled.is_(False),
                Board.archived.is_(False),
            )
            .options(
                selectinload(Card.assigned_to),
                selectinload(Card.secondary_assignees),
            )
        )
        if board_ids:
            query = query.filter(Board.id.in_(board_ids))
        query = _apply_assignee_card_filters(
            query, assignee_ids, include_unassigned, include_secondary_assignees=True
        )

        if global_board.done_visible_days is not None:
            cutoff = utc_now() - timedelta(days=global_board.done_visible_days)
            query = query.filter(or_(
                Card.done.is_(False),
                Card.done_datetime.is_(None),
                Card.done_datetime >= cutoff,
            ))

        rows = query.order_by(GlobalBoardCard.order, GlobalBoardCard.id).all()

        states = {state: [] for state in GLOBAL_STATES}
        edit_cache = {}
        epics = {}
        for promotion, card, column, board in rows:
            can_edit = _can_edit_board(user_id, board.id, edit_cache)
            states[_global_state(card, promotion)].append(
                _serialize_global_card(card, promotion, column, board, can_edit)
            )
            epics[board.id] = board.name

        # Done is newest first; done cards with no time sort last.
        states[GLOBAL_STATE_DONE].sort(
            key=lambda item: item["done_datetime"] or "", reverse=True
        )

        return jsonify({
            "success": True,
            "global_board": _serialize_global_board(
                global_board, get_user_permissions(user_id)
            ),
            "states": states,
            "epics": [
                {"id": board_id, "name": name}
                for board_id, name in sorted(epics.items(), key=lambda item: item[1].lower())
            ],
        }), 200
    except Exception as e:
        logger.error(f"Error listing cards for global board {global_board_id}: {str(e)}")
        return create_error_response("Failed to list global board cards", 500)
    finally:
        db.close()


@global_board_bp.route("/api/global-boards/<int:global_board_id>/cards", methods=["POST"])
@require_permission('card.update')
def promote_card(global_board_id):
    """Promote a card to a global board.
    ---
    tags:
      - Global Boards
    security:
      - session: []
    parameters:
      - name: global_board_id
        in: path
        required: true
        type: integer
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - card_id
          properties:
            card_id:
              type: integer
            state:
              type: string
              enum: [new, in_progress, waiting]
              default: new
    responses:
      201:
        description: Card promoted
      400:
        description: Invalid fields, or the card can't be promoted
      403:
        description: Insufficient permissions, or the board isn't eligible
      404:
        description: Card or global board not found
      409:
        description: Card is already promoted
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        user_id = g.user.id
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return create_error_response("card_id is required", 400)

        card_id = data.get("card_id")
        is_valid, error = validate_integer(card_id, "card_id", min_value=1)
        if not is_valid:
            return create_error_response(error, 400)

        state = data.get("state", GLOBAL_STATE_NEW)
        if state not in GLOBAL_STORED_STATES:
            return create_error_response(
                f"state must be one of: {', '.join(GLOBAL_STORED_STATES)}", 400
            )

        global_board = get_accessible_global_board(db, user_id, global_board_id)
        if global_board is None:
            return create_error_response(GLOBAL_BOARD_NOT_FOUND, 404)

        card = _get_scoped_card(db, user_id, card_id)
        if card is None:
            return create_error_response(CARD_NOT_FOUND, 404)

        board = card.column.board
        if card.scheduled:
            return create_error_response("Schedule templates can't be promoted", 400)
        if card.archived or board.archived:
            return create_error_response("Archived cards can't be promoted", 400)
        if card.done:
            return create_error_response("Done cards can't be promoted", 400)

        eligible_ids = {b.id for b in get_eligible_global_boards(db, board.id, user_id)}
        if global_board.id not in eligible_ids:
            return create_error_response(
                "Cards on this board can't be promoted to this global board", 403
            )

        if get_card_promotion(db, card.id) is not None:
            return create_error_response("Card is already promoted", 409)

        promotion = GlobalBoardCard(
            global_board_id=global_board.id,
            card_id=card.id,
            state=state,
            order=_next_order(db, global_board.id, state),
            promoted_by_id=user_id,
            promoted_at=utc_now(),
        )
        db.add(promotion)
        try:
            db.commit()
        except IntegrityError:
            # Another request promoted it between the check above and here.
            db.rollback()
            return create_error_response("Card is already promoted", 409)
        db.refresh(promotion)
        _notify_global_board_changed(global_board.id)
        _notify_epic_card_changed(db, card, board.id)

        return jsonify({
            "success": True,
            "message": "Card promoted",
            "card": _serialize_global_card(card, promotion, card.column, board, True),
        }), 201
    except Exception as e:
        db.rollback()
        logger.error(f"Error promoting card to global board {global_board_id}: {str(e)}")
        return create_error_response("Failed to promote card", 500)
    finally:
        db.close()


@global_board_bp.route(
    "/api/global-boards/<int:global_board_id>/cards/<int:card_id>", methods=["DELETE"]
)
@require_permission('card.update')
def demote_card(global_board_id, card_id):
    """Demote a card, removing it from the global board.
    ---
    tags:
      - Global Boards
    security:
      - session: []
    parameters:
      - name: global_board_id
        in: path
        required: true
        type: integer
      - name: card_id
        in: path
        required: true
        type: integer
    responses:
      200:
        description: Card demoted
      403:
        description: Insufficient permissions
      404:
        description: Card, global board or promotion not found
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        user_id = g.user.id
        global_board = get_accessible_global_board(db, user_id, global_board_id)
        if global_board is None:
            return create_error_response(GLOBAL_BOARD_NOT_FOUND, 404)

        card = _get_scoped_card(db, user_id, card_id)
        promotion = get_card_promotion(db, card_id) if card is not None else None
        if promotion is None or promotion.global_board_id != global_board.id:
            return create_error_response("Card is not on this global board", 404)

        board_id = card.column.board_id
        db.delete(promotion)
        db.commit()
        _notify_global_board_changed(global_board.id)
        _notify_epic_card_changed(db, card, board_id)

        return jsonify({"success": True, "message": "Card demoted", "card_id": card_id}), 200
    except Exception as e:
        db.rollback()
        logger.error(f"Error demoting card {card_id} from global board {global_board_id}: {str(e)}")
        return create_error_response("Failed to demote card", 500)
    finally:
        db.close()


@global_board_bp.route(
    "/api/global-boards/<int:global_board_id>/cards/<int:card_id>", methods=["PATCH"]
)
@require_permission('card.update')
def move_global_card(global_board_id, card_id):
    """Move a promoted card to a state, after another card or to the top.
    ---
    tags:
      - Global Boards
    security:
      - session: []
    parameters:
      - name: global_board_id
        in: path
        required: true
        type: integer
      - name: card_id
        in: path
        required: true
        type: integer
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - state
          properties:
            state:
              type: string
              enum: [new, in_progress, waiting, done]
              description: Done ticks the card done. Moving out of done unticks it
            after_card_id:
              type: integer
              x-nullable: true
              description: >
                Place straight after this card in the target state. Null or missing
                places the card at the top. Ignored for done, which is newest first
    responses:
      200:
        description: Card moved
      400:
        description: Invalid fields
      403:
        description: Insufficient permissions
      404:
        description: Card, global board or promotion not found
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        user_id = g.user.id
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return create_error_response("state is required", 400)

        state = data.get("state")
        if state not in GLOBAL_STATES:
            return create_error_response(f"state must be one of: {', '.join(GLOBAL_STATES)}", 400)

        after_card_id = data.get("after_card_id")
        is_valid, error = validate_integer(after_card_id, "after_card_id", min_value=1, allow_none=True)
        if not is_valid:
            return create_error_response(error, 400)
        if after_card_id == card_id:
            return create_error_response("after_card_id can't be the card being moved", 400)

        global_board = get_accessible_global_board(db, user_id, global_board_id)
        if global_board is None:
            return create_error_response(GLOBAL_BOARD_NOT_FOUND, 404)

        card = _get_scoped_card(db, user_id, card_id)
        promotion = get_card_promotion(db, card_id) if card is not None else None
        if promotion is None or promotion.global_board_id != global_board.id:
            return create_error_response("Card is not on this global board", 404)

        now = utc_now()
        board_id = card.column.board_id
        was_done = bool(card.done)

        if state == GLOBAL_STATE_DONE:
            if not card.done:
                apply_card_done(db, card, True, now, board_id=board_id)
        else:
            after_promotion = None
            if after_card_id is not None:
                after_card = _get_scoped_card(db, user_id, after_card_id)
                after_promotion = (
                    get_card_promotion(db, after_card_id) if after_card is not None else None
                )
                if (
                    after_promotion is None
                    or after_promotion.global_board_id != global_board.id
                    or after_card.done
                    or after_promotion.state != state
                ):
                    return create_error_response(
                        "after_card_id must be a card in the target state", 400
                    )
            if card.done:
                apply_card_done(db, card, False, now, board_id=board_id)
            _place_card(db, promotion, state, after_promotion)

        db.commit()
        db.refresh(card)
        db.refresh(promotion)
        _notify_global_board_changed(global_board.id)
        if bool(card.done) != was_done:
            _notify_card_done_changed(db, card, board_id)
        else:
            _notify_epic_card_changed(db, card, board_id)

        return jsonify({
            "success": True,
            "message": "Card moved",
            "card": _serialize_global_card(
                card, promotion, card.column, card.column.board, True
            ),
        }), 200
    except Exception as e:
        db.rollback()
        logger.error(f"Error moving card {card_id} on global board {global_board_id}: {str(e)}")
        return create_error_response("Failed to move card", 500)
    finally:
        db.close()
