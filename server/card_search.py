"""Search across boards (#593): find cards on every board the user can open.

Board search (``q`` on ``GET /api/boards/:id/cards``) stays scoped to one board
and view. This module searches every board the user can access, or a chosen set
of them, with the same query grammar and limits, and groups the matches by
board and then by the view each card appears in: task, done, archived or
scheduled.

Access matches ``can_access_board``: the board owner, anyone with a role on the
board, and administrators. Boards the user can't open never contribute a name
or a card to the response.
"""
import logging

from flask import Blueprint, g, jsonify, request
from sqlalchemy import func, or_

from board_routes import (
    TEXT_SEARCH_MAX_OR_GROUPS,
    TEXT_SEARCH_MAX_QUERY_LENGTH,
    TEXT_SEARCH_MAX_TERM_LENGTH,
    TEXT_SEARCH_MAX_TOTAL_TERMS,
    TEXT_SEARCH_MIN_QUERY_LENGTH,
    _build_text_search_predicate,
    _validate_and_parse_text_search_query,
)
from database import SessionLocal
from datetime_helpers import serialize_datetime
from models import Board, BoardColumn, BoardSetting, Card, UserRole
from permissions import has_permission
from settings_schema import (
    WORKING_STYLE_AGILE,
    normalize_working_style,
    parse_json_setting_value,
)
from utils import create_error_response, get_user_permissions, require_authentication

logger = logging.getLogger(__name__)

card_search_bp = Blueprint("card_search", __name__)

SEARCH_DEFAULT_LIMIT = 100
SEARCH_MAX_LIMIT = 200
SEARCH_MAX_BOARD_IDS = 100

QUERY_LIMITS_MESSAGE = (
    f"Query parameter q supports at most {TEXT_SEARCH_MAX_QUERY_LENGTH} characters, "
    f"{TEXT_SEARCH_MAX_OR_GROUPS} comma-separated groups, {TEXT_SEARCH_MAX_TOTAL_TERMS} terms "
    f"and {TEXT_SEARCH_MAX_TERM_LENGTH} characters per term"
)

VIEW_TASK = "task"
VIEW_DONE = "done"
VIEW_ARCHIVED = "archived"
VIEW_SCHEDULED = "scheduled"
VIEW_ORDER = (VIEW_TASK, VIEW_DONE, VIEW_ARCHIVED, VIEW_SCHEDULED)


def _parse_board_ids(raw_value):
    """Parse a comma-separated list of board ids.

    Returns:
        tuple: (list of ids or None when not given, error message or None)
    """
    if raw_value is None or str(raw_value).strip() == "":
        return None, None

    board_ids = []
    for part in str(raw_value).split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit() or len(part) > 10:
            return None, "board_ids must be a comma-separated list of board ids"
        board_id = int(part)
        if board_id <= 0:
            return None, "board_ids must be a comma-separated list of board ids"
        if board_id not in board_ids:
            board_ids.append(board_id)

    if not board_ids:
        return None, "board_ids must be a comma-separated list of board ids"
    if len(board_ids) > SEARCH_MAX_BOARD_IDS:
        return None, f"board_ids supports at most {SEARCH_MAX_BOARD_IDS} boards"
    return board_ids, None


def _parse_limit(raw_value):
    if raw_value is None or str(raw_value).strip() == "":
        return SEARCH_DEFAULT_LIMIT, None
    value = str(raw_value).strip()
    if not value.isdigit() or len(value) > 4:
        return None, f"limit must be a whole number from 1 to {SEARCH_MAX_LIMIT}"
    limit = int(value)
    if limit < 1 or limit > SEARCH_MAX_LIMIT:
        return None, f"limit must be a whole number from 1 to {SEARCH_MAX_LIMIT}"
    return limit, None


def _accessible_board_predicate(db, user_id):
    """Return a filter limiting boards to those the user can open, or None for admins."""
    if has_permission(get_user_permissions(user_id), "system.admin"):
        return None
    role_board_ids = db.query(UserRole.board_id).filter(
        UserRole.user_id == user_id,
        UserRole.board_id.isnot(None),
    )
    return or_(Board.owner_id == user_id, Board.id.in_(role_board_ids))


def _agile_board_ids(db, board_ids):
    """Return the ids of the given boards that use the agile working style."""
    if not board_ids:
        return set()
    rows = db.query(BoardSetting.board_id, BoardSetting.value).filter(
        BoardSetting.board_id.in_(board_ids),
        BoardSetting.key == "working_style",
    ).all()
    return {
        board_id
        for board_id, raw_value in rows
        if normalize_working_style(parse_json_setting_value(raw_value)) == WORKING_STYLE_AGILE
    }


def card_view(card_done, card_archived, card_scheduled, board_is_agile):
    """Return the board view a card appears in.

    Scheduled templates only show in the scheduled view, and archived cards
    only in the archived view. Done cards have their own view on agile boards
    and stay in the task view on kanban boards.
    """
    if card_scheduled:
        return VIEW_SCHEDULED
    if card_archived:
        return VIEW_ARCHIVED
    if card_done and board_is_agile:
        return VIEW_DONE
    return VIEW_TASK


@card_search_bp.route("/api/search/cards", methods=["GET"])
@require_authentication
def search_cards():
    """Search cards across every board the user can access.
    Matches are grouped by board, then by the view the card appears in (task, done,
    archived, scheduled). Only the most recently updated matches up to `limit` are
    returned; `total` is the full number of matches.
    ---
    tags:
      - Cards
    security:
      - session: []
    parameters:
      - name: q
        in: query
        type: string
        required: true
        description: >
          Search query, using the board search grammar and limits (at least 2 characters,
          max 200 chars, max 12 OR groups, max 24 total terms, max 80 chars per term).
          Spaces are AND, commas are OR, quoted phrases are exact matches, and repeated
          double quotes inside quoted phrases escape a literal quote. Unquoted #<digits>
          tokens match card id only.
      - name: board_ids
        in: query
        type: string
        required: false
        description: >
          Comma-separated board ids to search (max 100). Boards the user can't access
          are ignored. When omitted, every accessible board is searched.
      - name: include_archived_boards
        in: query
        type: string
        required: false
        enum: ['true', 'false']
        default: 'false'
        description: >
          Include archived boards when searching every board. Boards named in
          board_ids are always searched.
      - name: limit
        in: query
        type: integer
        required: false
        default: 100
        description: Maximum number of cards to return (1 to 200)
    responses:
      200:
        description: Matching cards grouped by board and view
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            total:
              type: integer
              example: 3
            returned:
              type: integer
              example: 3
            limit:
              type: integer
              example: 100
            truncated:
              type: boolean
              example: false
            boards:
              type: array
              items:
                type: object
                properties:
                  id:
                    type: integer
                  name:
                    type: string
                  archived:
                    type: boolean
                  views:
                    type: array
                    items:
                      type: object
                      properties:
                        view:
                          type: string
                          enum: [task, done, archived, scheduled]
                        cards:
                          type: array
                          items:
                            type: object
                            properties:
                              id:
                                type: integer
                              title:
                                type: string
                              column_id:
                                type: integer
                              column_name:
                                type: string
                              done:
                                type: boolean
                              archived:
                                type: boolean
                              scheduled:
                                type: boolean
                              updated_at:
                                type: string
                                x-nullable: true
      400:
        description: Missing or invalid query parameters
      401:
        description: Authentication required
      500:
        description: Server error
    """
    text_query, parsed_groups, query_error = _validate_and_parse_text_search_query(
        request.args.get("q")
    )
    if query_error:
        # A fixed message, so nothing derived from the request is echoed back.
        return create_error_response(QUERY_LIMITS_MESSAGE, 400)
    if not text_query or not parsed_groups:
        return create_error_response(
            f"Query parameter q must be at least {TEXT_SEARCH_MIN_QUERY_LENGTH} characters",
            400,
        )

    board_ids, board_ids_error = _parse_board_ids(request.args.get("board_ids"))
    if board_ids_error:
        return create_error_response(board_ids_error, 400)

    include_archived_param = request.args.get("include_archived_boards", "false").lower()
    if include_archived_param not in ("true", "false"):
        return create_error_response("include_archived_boards must be true or false", 400)
    include_archived_boards = include_archived_param == "true"

    limit, limit_error = _parse_limit(request.args.get("limit"))
    if limit_error:
        return create_error_response(limit_error, 400)

    predicate = _build_text_search_predicate(parsed_groups)
    if predicate is None:
        return create_error_response(
            f"Query parameter q must be at least {TEXT_SEARCH_MIN_QUERY_LENGTH} characters",
            400,
        )

    db = SessionLocal()
    try:
        user_id = g.user.id
        matches = (
            db.query(Card)
            .join(BoardColumn, Card.column_id == BoardColumn.id)
            .join(Board, BoardColumn.board_id == Board.id)
            .filter(predicate)
        )

        access_predicate = _accessible_board_predicate(db, user_id)
        if access_predicate is not None:
            matches = matches.filter(access_predicate)

        if board_ids is not None:
            matches = matches.filter(Board.id.in_(board_ids))
        elif not include_archived_boards:
            matches = matches.filter(Board.archived.is_(False))

        rows = (
            matches.with_entities(
                Card.id,
                Card.title,
                Card.done,
                Card.archived,
                Card.scheduled,
                Card.updated_at,
                BoardColumn.id,
                BoardColumn.name,
                Board.id,
                Board.name,
                Board.archived,
            )
            .order_by(Card.updated_at.desc(), Card.id.desc())
            .limit(limit)
            .all()
        )
        # Counting scans every match again, so only count when the cap was hit.
        if len(rows) < limit:
            total = len(rows)
        else:
            total = matches.with_entities(func.count(Card.id)).scalar() or 0

        agile_ids = _agile_board_ids(db, {row[8] for row in rows})

        boards = {}
        for (
            card_id, title, done, archived, scheduled, updated_at,
            column_id, column_name, board_id, board_name, board_archived,
        ) in rows:
            board_entry = boards.get(board_id)
            if board_entry is None:
                board_entry = {
                    "id": board_id,
                    "name": board_name,
                    "archived": bool(board_archived),
                    "views": {},
                }
                boards[board_id] = board_entry

            view = card_view(done, archived, scheduled, board_id in agile_ids)
            board_entry["views"].setdefault(view, []).append({
                "id": card_id,
                "title": title,
                "column_id": column_id,
                "column_name": column_name,
                "done": bool(done),
                "archived": bool(archived),
                "scheduled": bool(scheduled),
                "updated_at": serialize_datetime(updated_at),
            })

        board_list = sorted(
            boards.values(),
            key=lambda entry: ((entry["name"] or "").casefold(), entry["id"]),
        )
        for entry in board_list:
            entry["views"] = [
                {"view": view, "cards": entry["views"][view]}
                for view in VIEW_ORDER
                if view in entry["views"]
            ]

        return jsonify({
            "success": True,
            "total": total,
            "returned": len(rows),
            "limit": limit,
            "truncated": total > len(rows),
            "boards": board_list,
        })
    except Exception as e:
        logger.error(f"Error searching cards: {str(e)}")
        return create_error_response("Failed to search cards", 500)
    finally:
        db.close()
