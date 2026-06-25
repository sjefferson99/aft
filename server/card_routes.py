"""Card routes blueprint.

Extracted from app.py – all card-related endpoints:
  GET/POST/DELETE  /api/columns/<id>/cards
  POST             /api/columns/<id>/cards/move
  GET              /api/boards/<id>/cards
  GET/PATCH/DELETE /api/cards/<id>
  GET/PUT          /api/cards/<id>/assignees
  PATCH            /api/cards/<id>/archive
  PATCH            /api/cards/<id>/unarchive
  GET/PATCH        /api/cards/<id>/done
  POST             /api/cards/batch/archive
  POST             /api/cards/batch/unarchive
  POST             /api/columns/<id>/archive-after
  GET              /api/columns/<id>/cards/scheduled
"""
from flask import Blueprint, jsonify, request, g
import logging
from datetime import timedelta
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from database import SessionLocal
from datetime_helpers import parse_iso_datetime, serialize_datetime, utc_now
from models import Board, BoardColumn, Card, CardSecondaryAssignee, User
from settings_schema import WORKING_STYLE_AGILE, get_board_working_style
from utils import (
    MAX_DESCRIPTION_LENGTH,
    MAX_TITLE_LENGTH,
    create_error_response,
    create_success_response,
    get_current_user_id,
    get_user_permissions,
    get_user_scoped_query,
    require_board_access,
    require_permission,
    sanitize_string,
    validate_integer,
    validate_string_length,
)
from board_routes import (
    _apply_assignee_card_filters,
    _apply_text_search_filter,
    _build_board_owner_metadata,
    _get_board_assignee_users,
    _get_board_eligible_assignee_ids,
    _parse_assignee_ids_query_param,
    _validate_and_parse_text_search_query,
    _user_summary,
)

logger = logging.getLogger(__name__)

card_bp = Blueprint("card", __name__)

# Injected at startup via configure_card_routes()
_broadcast_event = None

DONE_COLUMN_NAME_SYNONYMS = {
    "done",
    "complete",
    "completed",
    "finished",
    "resolved",
    "closed",
    "shipped",
}


def configure_card_routes(broadcast_event_fn):
    """Inject runtime dependencies into this module."""
    global _broadcast_event
    _broadcast_event = broadcast_event_fn


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _get_fully_authorized_batch_cards(db, user_id, card_ids, *, order_by=None):
    unique_card_ids = list(dict.fromkeys(card_ids))
    query = get_user_scoped_query(db, Card, user_id).filter(Card.id.in_(unique_card_ids))

    if order_by is not None:
        query = query.order_by(*order_by)

    cards = query.all()
    authorized_ids = {card.id for card in cards}
    requested_ids = set(unique_card_ids)

    if authorized_ids != requested_ids:
        return None, unique_card_ids

    return cards, unique_card_ids


def _normalize_column_name(column_name):
    if not isinstance(column_name, str):
        return ""

    # Keep alphanumeric characters and spaces only so labels like "Done!" normalize to "done".
    cleaned = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in column_name)
    return " ".join(cleaned.strip().lower().split())


def _is_done_like_column_name(column_name):
    normalized = _normalize_column_name(column_name)
    return normalized in DONE_COLUMN_NAME_SYNONYMS


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@card_bp.route("/api/columns/<int:column_id>/cards", methods=["GET"])
@require_permission('card.view')
def get_column_cards(column_id):
    """Get all cards for a specific column.
    ---
    tags:
      - Cards
    parameters:
      - name: column_id
        in: path
        type: integer
        required: true
        description: The ID of the column
      - name: archived
        in: query
        type: string
        required: false
        description: Filter by archived status - 'true' for archived, 'false' for unarchived, 'both' for all (default is 'false')
        enum: ['true', 'false', 'both']
        default: 'false'
    responses:
      200:
        description: List of cards for the column
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            cards:
              type: array
              items:
                type: object
                properties:
                  id:
                    type: integer
                    example: 1
                  column_id:
                    type: integer
                    example: 1
                  title:
                    type: string
                    example: "Task title"
                  description:
                    type: string
                    example: "Task description"
                  order:
                    type: integer
                    example: 0
      500:
        description: Server error
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            message:
              type: string
    """
    try:
        db = SessionLocal()

        user_id = g.user.id
        # Get archived filter from query parameter (default to false - unarchived only)
        archived_param = request.args.get('archived', 'false').lower()

        # Always filter out scheduled template cards (scheduled=True) from task views
        cards_query = get_user_scoped_query(db, Card, user_id).filter(Card.column_id == column_id).filter(Card.scheduled.is_(False))

        # Apply archived filter
        if archived_param == 'true':
            cards_query = cards_query.filter(Card.archived.is_(True))
        elif archived_param == 'false':
            cards_query = cards_query.filter(Card.archived.is_(False))
        # If 'both', don't add archived filter

        cards = cards_query.order_by(Card.order).all()

        # Serialize cards before closing session to access relationships
        cards_data = [
            {
                "id": c.id,
                "column_id": c.column_id,
                "title": c.title,
                "description": c.description,
                "order": c.order,
                "archived": c.archived,
                "done": c.done,
                "done_datetime": serialize_datetime(c.done_datetime),
                "scheduled": c.scheduled,
                "schedule": c.schedule,
                "created_at": serialize_datetime(c.created_at),
                "updated_at": serialize_datetime(c.updated_at),
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
                    for item in c.checklist_items
                ]
            }
            for c in cards
        ]

        db.close()
        return jsonify(
            {
                "success": True,
                "cards": cards_data
            }
        )
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@card_bp.route("/api/boards/<int:board_id>/cards", methods=["GET"])
@require_board_access()
def get_board_cards(board_id):
    """Get all cards for a board with nested structure (board -> columns -> cards).
    ---
    tags:
      - Cards
    parameters:
      - name: board_id
        in: path
        type: integer
        required: true
        description: The ID of the board
      - name: archived
        in: query
        type: string
        required: false
        description: Filter by archived status - 'true' for archived, 'false' for unarchived, 'both' for all (default is 'false')
        enum: ['true', 'false', 'both']
        default: 'false'
      - name: include_owner_candidates
        in: query
        type: string
        required: false
        description: Include owner reassignment candidate users when true
        enum: ['true', 'false']
        default: 'false'
      - name: q
        in: query
        type: string
        required: false
        description: >
          Optional text search query (max 200 chars, max 12 OR groups, max 24 total terms,
          max 80 chars per term). Spaces are AND, commas are OR, quoted phrases are exact
          matches, and repeated double quotes inside quoted phrases escape a literal quote.
          Unquoted #<digits> tokens match card id only.
    responses:
      200:
        description: Nested structure of board with columns and cards
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            board:
              type: object
              properties:
                id:
                  type: integer
                  example: 1
                name:
                  type: string
                  example: "My Board"
                columns:
                  type: array
                  items:
                    type: object
                    properties:
                      id:
                        type: integer
                        example: 1
                      name:
                        type: string
                        example: "To Do"
                      order:
                        type: integer
                        example: 0
                      cards:
                        type: array
                        items:
                          type: object
                          properties:
                            id:
                              type: integer
                              example: 1
                            title:
                              type: string
                              example: "Task title"
                            description:
                              type: string
                              example: "Task description"
                            order:
                              type: integer
                              example: 0
      404:
        description: Board not found
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            message:
              type: string
              example: "Board not found"
      500:
        description: Server error
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            message:
              type: string
    """
    try:
        db = SessionLocal()

        # Access already validated by @require_board_access decorator
        # Get archived filter from query parameter (default to false - unarchived only)
        archived_param = request.args.get('archived', 'false').lower()

        selected_assignee_ids = _parse_assignee_ids_query_param(request.args.get('assignee_ids'))
        include_unassigned = request.args.get('include_unassigned', 'false').lower() == 'true'
        include_secondary_assignees = request.args.get('include_secondary_assignees', 'false').lower() == 'true'
        include_owner_candidates = request.args.get('include_owner_candidates', 'false').lower() == 'true'
        text_query, parsed_text_query, text_query_error = _validate_and_parse_text_search_query(
          request.args.get('q')
        )
        if text_query_error:
          db.close()
          return create_error_response(text_query_error, 400)

        # Get board
        board = db.query(Board).filter(Board.id == board_id).first()
        if not board:
            db.close()
            return jsonify({"success": False, "message": "Board not found"}), 404

        # Get columns for board
        columns = (
            db.query(BoardColumn)
            .filter(BoardColumn.board_id == board_id)
            .order_by(BoardColumn.order)
            .all()
        )

        # Build nested structure
        result = {
          "id": board.id,
          "name": board.name,
          "is_public": bool(board.is_public),
          "public_slug": board.public_slug,
          "archived": bool(board.archived),
          "columns": [],
        }
        result.update(_build_board_owner_metadata(board, g.user.id, db, include_candidates=include_owner_candidates))
        eligible_users = _get_board_assignee_users(db, board_id)
        result["assignee_filter_users"] = [_user_summary(u) for u in eligible_users]

        for column in columns:
            # Get cards for this column with archived filter
            # Always filter out scheduled template cards (scheduled=True) from task views
            cards_query = db.query(Card).filter(Card.column_id == column.id).filter(Card.scheduled.is_(False))
            cards_query = cards_query.options(selectinload(Card.assigned_to))

            cards_query = _apply_assignee_card_filters(
                cards_query,
                selected_assignee_ids,
                include_unassigned,
                include_secondary_assignees,
            )

            cards_query = _apply_text_search_filter(cards_query, text_query, parsed_groups=parsed_text_query)

            # Apply archived filter
            if archived_param == 'true':
                cards_query = cards_query.filter(Card.archived.is_(True))
            elif archived_param == 'false':
                cards_query = cards_query.filter(Card.archived.is_(False))
            # If 'both', don't add archived filter

            cards = cards_query.order_by(Card.order).all()

            # Serialize cards with checklist items and comments while session is active
            cards_data = [
                {
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
                    "comments": [
                        {
                            "id": comment.id,
                            "card_id": comment.card_id,
                            "comment": comment.comment,
                            "order": comment.order,
                            "created_at": serialize_datetime(comment.created_at)
                        }
                        for comment in card.comments
                    ]
                }
                for card in cards
            ]

            column_data = {
                "id": column.id,
                "name": column.name,
                "order": column.order,
                "created_at": serialize_datetime(column.created_at),
                "updated_at": serialize_datetime(column.updated_at),
                "cards": cards_data,
            }
            result["columns"].append(column_data)

        # Check if user has edit permissions for this board
        user_permissions = get_user_permissions(g.user.id, board_id)
        edit_permissions = ['card.create', 'card.edit', 'card.update', 'card.delete', 'card.archive', 'board.edit']
        can_edit = any(perm in user_permissions for perm in edit_permissions)
        result["can_edit"] = can_edit

        db.close()
        return jsonify({"success": True, "board": result})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@card_bp.route("/api/columns/<int:column_id>/cards", methods=["POST"])
@require_permission('card.create')
def create_card(column_id):
    """Create a new card in a column with input validation.

    This endpoint creates a new card after validating:
    - Title is provided, is a string, and within length limits
    - Description (if provided) is a string and within length limits
    - Order (if provided) is a valid non-negative integer
    - Column exists
    ---
    tags:
      - Cards
    parameters:
      - name: column_id
        in: path
        type: integer
        required: true
        description: The ID of the column
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - title
          properties:
            title:
              type: string
              example: "New task"
              description: The title of the card
            description:
              type: string
              example: "Task details"
              description: The description of the card (optional)
            order:
              type: integer
              example: 0
              description: The order position (optional, defaults to end)
            scheduled:
              type: boolean
              example: false
              description: Whether this is a template card (optional, defaults to false)
            start_date:
              type: string
              example: "2026-06-20T09:00:00Z"
              description: ISO-8601 start datetime (optional)
            end_date:
              type: string
              example: "2026-06-20T10:00:00Z"
              description: ISO-8601 end datetime (optional)
    responses:
      201:
        description: Card created successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            card:
              type: object
              properties:
                id:
                  type: integer
                  example: 1
                column_id:
                  type: integer
                  example: 1
                title:
                  type: string
                  example: "New task"
                description:
                  type: string
                  example: "Task details"
                order:
                  type: integer
                  example: 0
      400:
        description: Bad request - missing title
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            message:
              type: string
              example: "Title is required"
      404:
        description: Column not found
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            message:
              type: string
              example: "Column not found"
      500:
        description: Server error
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            message:
              type: string
    """
    db = SessionLocal()
    try:
        # Handle case where get_json() might raise an exception for empty body
        try:
            data = request.get_json()
        except Exception:
            data = None

        if not data or "title" not in data:
            return create_error_response("Title is required", 400)

        user_id = g.user.id

        # Verify column exists and user has access to its board
        column = get_user_scoped_query(db, BoardColumn, user_id).filter(BoardColumn.id == column_id).first()
        if not column:
            return create_error_response("Column not found or access denied", 404)

        # Validate and sanitize title
        title = data.get("title")
        if not isinstance(title, str):
            return create_error_response("Title must be a string", 400)

        title = sanitize_string(title)
        if not title:
            return create_error_response("Title cannot be empty", 400)

        is_valid, error = validate_string_length(title, MAX_TITLE_LENGTH, "Title")
        if not is_valid:
            return create_error_response(error, 400)

        # Validate and sanitize description if provided
        description = data.get("description", "")
        if description is not None:
            if not isinstance(description, str):
                return create_error_response("Description must be a string", 400)

            description = sanitize_string(description)
            is_valid, error = validate_string_length(
                description, MAX_DESCRIPTION_LENGTH, "Description"
            )
            if not is_valid:
                return create_error_response(error, 400)

        # Validate order if provided
        if "order" in data:
            order = data["order"]
            is_valid, error = validate_integer(order, "Order", min_value=0)
            if not is_valid:
                return create_error_response(error, 400)

            # Increment order of existing cards >= this order
            existing_cards = (
                db.query(Card)
                .filter(Card.column_id == column_id, Card.order >= order)
                .all()
            )
            for card_to_update in existing_cards:
                card_to_update.order += 1
        else:
            # Add at the end
            order = db.query(Card).filter(Card.column_id == column_id).count()

        # Validate scheduled parameter if provided
        scheduled = data.get("scheduled", False)
        if scheduled is not None and not isinstance(scheduled, bool):
            return create_error_response("Scheduled must be a boolean", 400)

        # Validate schedule parameter if provided
        schedule = data.get("schedule")
        if schedule is not None:
            if not isinstance(schedule, int):
                return create_error_response("Schedule must be an integer", 400)

        # Validate start_date/end_date if provided (e.g. the planner month view
        # pre-dating a new card from a clicked day)
        start_date = None
        if "start_date" in data and data["start_date"] is not None:
            start_date = parse_iso_datetime(data["start_date"])
            if start_date is None:
                return create_error_response("Start date must be a valid ISO-8601 datetime", 400)

        end_date = None
        if "end_date" in data and data["end_date"] is not None:
            end_date = parse_iso_datetime(data["end_date"])
            if end_date is None:
                return create_error_response("End date must be a valid ISO-8601 datetime", 400)

        if start_date and end_date and end_date < start_date:
            return create_error_response("End date cannot be before start date", 400)

        # Create card
        now = utc_now()
        card = Card(
            column_id=column_id,
            title=title,
            description=description,
            order=order,
            scheduled=scheduled,
            schedule=schedule,
            start_date=start_date,
            end_date=end_date,
            updated_at=now,
            created_by_id=g.user.id,
            assigned_to_id=None,
        )
        db.add(card)
        db.commit()
        db.refresh(card)

        result = {
            "id": card.id,
            "column_id": card.column_id,
            "title": card.title,
            "description": card.description,
            "order": card.order,
            "scheduled": card.scheduled,
            "schedule": card.schedule,
            "archived": card.archived,
            "done": card.done,
            "done_datetime": serialize_datetime(card.done_datetime),
            "start_date": serialize_datetime(card.start_date),
            "end_date": serialize_datetime(card.end_date),
            "created_at": serialize_datetime(card.created_at),
            "updated_at": serialize_datetime(card.updated_at)
        }

        # Get board_id for WebSocket broadcast
        board_id = column.board_id
        if board_id is not None:
            _broadcast_event('card_created', {
                'board_id': board_id,
                'column_id': column_id,
                'card_id': card.id,
                'card_data': result
            }, board_id)
        else:
            logger.warning(f"Skipping card_created broadcast for card {card.id}: column {column_id} has no board_id")

        return create_success_response({"card": result}, status_code=201)

    except Exception as e:
        db.rollback()
        logger.error(f"Error creating card in column {column_id}: {str(e)}")
        return create_error_response("Failed to create card", 500)
    finally:
        db.close()


@card_bp.route("/api/columns/<int:column_id>/cards", methods=["DELETE"])
@require_permission('card.delete')
def delete_all_cards_in_column(column_id):
    """Delete all cards in a column.
    ---
    tags:
      - Cards
    parameters:
      - name: column_id
        in: path
        type: integer
        required: true
        description: The ID of the column whose cards should be deleted
    responses:
      200:
        description: All cards deleted successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            message:
              type: string
              example: "Deleted 5 cards"
            deleted_count:
              type: integer
              example: 5
      404:
        description: Column not found
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            message:
              type: string
              example: "Column not found"
      500:
        description: Server error
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            message:
              type: string
    """
    db = SessionLocal()
    try:
        user_id = get_current_user_id()

        # Verify column exists
        column = db.query(BoardColumn).filter(BoardColumn.id == column_id).first()
        if not column:
            return jsonify({"success": False, "message": "Column not found"}), 404

        # Verify user owns the board this column belongs to
        board = get_user_scoped_query(db, Board, user_id).filter(Board.id == column.board_id).first()
        if not board:
            return jsonify({"success": False, "message": "Access denied"}), 403

        # Delete all cards in the column
        deleted_count = (
            db.query(Card)
            .filter(Card.column_id == column_id)
            .delete(synchronize_session=False)
        )
        db.commit()

        return (
            jsonify(
                {
                    "success": True,
                    "message": f"Deleted {deleted_count} cards",
                    "deleted_count": deleted_count,
                }
            ),
            200,
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting cards from column {column_id}: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        db.close()


@card_bp.route("/api/columns/<int:source_column_id>/cards/move", methods=["POST"])
@require_permission('card.edit')
def move_all_cards_in_column(source_column_id):
    """Move all cards from one column to another in a single transaction.
    ---
    tags:
      - Cards
    parameters:
      - name: source_column_id
        in: path
        type: integer
        required: true
        description: The ID of the source column
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - target_column_id
            - position
          properties:
            target_column_id:
              type: integer
              description: The ID of the target column
              example: 2
            position:
              type: string
              enum: [top, bottom]
              description: Where to place cards in target column
              example: "bottom"
            include_archived:
              type: boolean
              description: Whether to include archived cards in the move
              example: false
              default: false
    responses:
      200:
        description: All cards moved successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            message:
              type: string
              example: "Moved 5 cards"
            moved_count:
              type: integer
              example: 5
      400:
        description: Invalid request
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            message:
              type: string
              example: "Invalid position value"
      404:
        description: Column not found
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            message:
              type: string
              example: "Source column not found"
      500:
        description: Server error
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            message:
              type: string
    """
    db = SessionLocal()
    try:
        user_id = get_current_user_id()

        data = request.get_json()
        target_column_id = data.get("target_column_id")
        position = data.get("position", "bottom")
        include_archived = data.get("include_archived", False)

        # Validate inputs
        if not target_column_id:
            return jsonify({"success": False, "message": "target_column_id is required"}), 400

        if position not in ["top", "bottom"]:
            return jsonify({"success": False, "message": "Invalid position value. Must be 'top' or 'bottom'"}), 400

        # Verify source column exists
        source_column = db.query(BoardColumn).filter(BoardColumn.id == source_column_id).first()
        if not source_column:
            return jsonify({"success": False, "message": "Source column not found"}), 404

        # Verify user owns the board this source column belongs to
        board = get_user_scoped_query(db, Board, user_id).filter(Board.id == source_column.board_id).first()
        if not board:
            return jsonify({"success": False, "message": "Access denied to source board"}), 403

        # Verify target column exists
        target_column = db.query(BoardColumn).filter(BoardColumn.id == target_column_id).first()
        if not target_column:
            return jsonify({"success": False, "message": "Target column not found"}), 404

        # Verify user owns the board this target column belongs to
        target_board = get_user_scoped_query(db, Board, user_id).filter(Board.id == target_column.board_id).first()
        if not target_board:
            return jsonify({"success": False, "message": "Access denied to target board"}), 403

        # Get cards from source column, optionally filtering out archived cards
        source_query = db.query(Card).filter(Card.column_id == source_column_id)
        if not include_archived:
            source_query = source_query.filter(Card.archived.is_(False))
        source_cards = source_query.order_by(Card.order).all()

        if not source_cards:
            return jsonify({"success": True, "message": "No cards to move", "moved_count": 0}), 200

        # Get cards in target column to calculate new order values
        target_cards = (
            db.query(Card)
            .filter(Card.column_id == target_column_id)
            .order_by(Card.order)
            .all()
        )

        # Calculate new order values based on position
        target_is_done_like = _is_done_like_column_name(target_column.name)
        if position == "top":
            # Move existing target cards down to make room
            for i, card in enumerate(target_cards):
                card.order = i + len(source_cards)

            # Place source cards at top (maintain original order)
            for i, card in enumerate(source_cards):
                card.column_id = target_column_id
                card.order = i
                if target_is_done_like:
                    card.done_datetime = utc_now()
        else:  # bottom
            # Target cards keep their order
            # Source cards go after target cards
            start_order = len(target_cards)
            for i, card in enumerate(source_cards):
                card.column_id = target_column_id
                card.order = start_order + i
                if target_is_done_like:
                    card.done_datetime = utc_now()

        db.commit()

        # Broadcast column reorder/move event to both affected boards
        if source_column.board_id:
            _broadcast_event('cards_moved', {
                'board_id': source_column.board_id,
                'source_column_id': source_column_id,
                'target_column_id': target_column_id,
                'moved_count': len(source_cards),
                'position': position
            }, source_column.board_id)

        return (
            jsonify(
                {
                    "success": True,
                    "message": f"Moved {len(source_cards)} cards",
                    "moved_count": len(source_cards),
                }
            ),
            200,
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Error moving cards from column {source_column_id}: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        db.close()


@card_bp.route("/api/cards/<int:card_id>", methods=["GET"])
@require_permission('card.view')
def get_card(card_id):
    """Get a single card with its checklist items (user must have access).
    ---
    tags:
      - Cards
    parameters:
      - name: card_id
        in: path
        type: integer
        required: true
        description: The ID of the card to retrieve
    responses:
      200:
        description: Card data retrieved successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            card:
              type: object
              properties:
                id:
                  type: integer
                title:
                  type: string
                description:
                  type: string
                column_id:
                  type: integer
                order:
                  type: integer
                start_date:
                  type: string
                  format: date-time
                  example: "2026-06-20T09:00:00Z"
                end_date:
                  type: string
                  format: date-time
                  example: "2026-06-21T17:00:00Z"
                checklist_items:
                  type: array
                  items:
                    type: object
      401:
        description: Authentication required
      403:
        description: Permission denied
      404:
        description: Card not found
    """
    db = SessionLocal()
    try:
        user_id = g.user.id
        card = get_user_scoped_query(db, Card, user_id).filter(Card.id == card_id).first()
        if not card:
            return jsonify({"success": False, "message": "Card not found"}), 404

        # Serialize card with checklist items and comments
        card_data = {
            "id": card.id,
            "title": card.title,
            "description": card.description,
            "column_id": card.column_id,
            "order": card.order,
            "archived": card.archived,
            "done": card.done,
            "done_datetime": serialize_datetime(card.done_datetime),
            "scheduled": card.scheduled,
            "schedule": card.schedule,
            "start_date": serialize_datetime(card.start_date),
            "end_date": serialize_datetime(card.end_date),
            "created_at": serialize_datetime(card.created_at),
            "updated_at": serialize_datetime(card.updated_at),
            "checklist_items": [
                {
                    "id": item.id,
                    "name": item.name,
                    "checked": item.checked,
                    "order": item.order,
                    "created_at": serialize_datetime(item.created_at),
                    "updated_at": serialize_datetime(item.updated_at)
                }
                for item in sorted(card.checklist_items, key=lambda x: x.order)
            ],
            "comments": [
                {
                    "id": comment.id,
                    "card_id": comment.card_id,
                    "comment": comment.comment,
                    "order": comment.order,
                    "created_at": serialize_datetime(comment.created_at)
                }
                for comment in card.comments
            ]
        }

        return jsonify({"success": True, "card": card_data})
    except Exception as e:
        logger.error(f"Error getting card {card_id}: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        db.close()


@card_bp.route("/api/cards/<int:card_id>", methods=["PATCH"])
@require_permission('card.update')
def update_card(card_id):
    """Update a card's title, description, column, and/or order.
    ---
    tags:
      - Cards
    security:
      - session: []
    parameters:
      - name: card_id
        in: path
        type: integer
        required: true
        description: The ID of the card to update
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            title:
              type: string
              example: "Updated task title"
              description: The new title for the card
            description:
              type: string
              example: "Updated task description"
              description: The new description for the card
            column_id:
              type: integer
              example: 2
              description: The new column ID if moving the card. May target a column on a different board provided the user has access to that board.
            order:
              type: integer
              example: 1
              description: The new order position (cards >= this order will be incremented). Use instead of position for same-board moves where the order is known.
            position:
              type: string
              enum: [top, bottom]
              example: "bottom"
              description: Place the card at the top or bottom of the target column. Computed server-side from the target column's existing cards. Use instead of order when moving to a different board.
            start_date:
              type: string
              format: date-time
              example: "2026-06-20T09:00:00Z"
              description: ISO-8601 UTC start date/time, or null to clear it
            end_date:
              type: string
              format: date-time
              example: "2026-06-21T17:00:00Z"
              description: ISO-8601 UTC end date/time, or null to clear it. Must not be before start_date.
    responses:
      200:
        description: Card updated successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            card:
              type: object
              properties:
                id:
                  type: integer
                  example: 1
                column_id:
                  type: integer
                  example: 1
                title:
                  type: string
                  example: "Updated task title"
                description:
                  type: string
                  example: "Updated task description"
                order:
                  type: integer
                  example: 0
                start_date:
                  type: string
                  format: date-time
                  example: "2026-06-20T09:00:00Z"
                end_date:
                  type: string
                  format: date-time
                  example: "2026-06-21T17:00:00Z"
      400:
        description: Invalid date format or end_date before start_date
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            message:
              type: string
      403:
        description: Access denied to target board
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            message:
              type: string
              example: "Access denied to target board"
      404:
        description: Card or target column not found
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            message:
              type: string
              example: "Card not found"
      500:
        description: Server error
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            message:
              type: string
    """
    db = SessionLocal()
    try:
        # Handle case where get_json() might raise an exception for empty body
        try:
            data = request.get_json()
        except Exception:
            data = None

        if not data:
            return create_error_response("No data provided", 400)

        user_id = g.user.id

        # Verify card exists and user has access to its board
        card = get_user_scoped_query(db, Card, user_id).filter(Card.id == card_id).first()

        if not card:
            return create_error_response("Card not found or access denied", 404)

        old_column_id = card.column_id
        old_order = card.order

        # Track if user made content changes (not just reordering within same column)
        user_content_changed = False

        # Update and validate title if provided
        if "title" in data:
            title = data["title"]
            if not isinstance(title, str):
                return create_error_response("Title must be a string", 400)

            title = sanitize_string(title)
            if not title:
                return create_error_response("Title cannot be empty", 400)

            is_valid, error = validate_string_length(title, MAX_TITLE_LENGTH, "Title")
            if not is_valid:
                return create_error_response(error, 400)

            card.title = title
            user_content_changed = True

        # Update and validate description if provided
        if "description" in data:
            description = data["description"]
            if description is not None:
                if not isinstance(description, str):
                    return create_error_response("Description must be a string", 400)

                description = sanitize_string(description)
                is_valid, error = validate_string_length(
                    description, MAX_DESCRIPTION_LENGTH, "Description"
                )
                if not is_valid:
                    return create_error_response(error, 400)

            card.description = description
            user_content_changed = True

        # Update archived status if provided
        if "archived" in data:
            archived = data["archived"]
            if not isinstance(archived, bool):
                return create_error_response("Archived must be a boolean", 400)
            card.archived = archived
            user_content_changed = True

        # Update and validate start_date/end_date if provided
        new_start_date = card.start_date
        new_end_date = card.end_date

        if "start_date" in data:
            if data["start_date"] is None:
                new_start_date = None
            else:
                new_start_date = parse_iso_datetime(data["start_date"])
                if new_start_date is None:
                    return create_error_response("Start date must be a valid ISO-8601 datetime", 400)
            user_content_changed = True

        if "end_date" in data:
            if data["end_date"] is None:
                new_end_date = None
            else:
                new_end_date = parse_iso_datetime(data["end_date"])
                if new_end_date is None:
                    return create_error_response("End date must be a valid ISO-8601 datetime", 400)
            user_content_changed = True

        if new_start_date and new_end_date and new_end_date < new_start_date:
            return create_error_response("End date cannot be before start date", 400)

        card.start_date = new_start_date
        card.end_date = new_end_date

        # Handle column and order changes
        target_column = None
        if "column_id" in data or "order" in data:
            new_column_id = data.get("column_id", card.column_id)
            new_order = data.get("order", card.order)

            # Validate column_id if provided
            if "column_id" in data:
                is_valid, error = validate_integer(
                    new_column_id, "Column ID", min_value=1
                )
                if not is_valid:
                    return create_error_response(error, 400)

            # Validate order if provided
            if "order" in data:
                is_valid, error = validate_integer(new_order, "Order", min_value=0)
                if not is_valid:
                    return create_error_response(error, 400)

            # Verify new column exists if changing columns
            if new_column_id != old_column_id:
                target_column = (
                    db.query(BoardColumn)
                    .filter(BoardColumn.id == new_column_id)
                    .first()
                )
                if not target_column:
                    return create_error_response("Target column not found", 404)

                # Verify user has access to target board when moving cross-board
                source_board_id = db.query(BoardColumn.board_id).filter(
                    BoardColumn.id == old_column_id
                ).scalar()
                if source_board_id and target_column.board_id != source_board_id:
                    target_board = get_user_scoped_query(db, Board, user_id).filter(
                        Board.id == target_column.board_id
                    ).first()
                    if not target_board:
                        return create_error_response("Access denied to target board", 403)

                # Support position parameter as alternative to explicit order
                if "position" in data:
                    position_val = data["position"]
                    if position_val not in ["top", "bottom"]:
                        return create_error_response("Position must be 'top' or 'bottom'", 400)
                    min_order, max_order = db.query(
                        func.min(Card.order),
                        func.max(Card.order),
                    ).filter(
                        Card.column_id == new_column_id,
                        Card.archived.is_(False),
                    ).one()
                    if min_order is None:
                        new_order = 0
                    elif position_val == "top":
                        new_order = int(min_order)
                    else:
                        new_order = int(max_order) + 1

                # Moving to different column is a state change - update timestamp
                user_content_changed = True

            # If moving to a different column
            if new_column_id != old_column_id:
                # Decrement order of cards after old position in old column (excluding archived)
                db.query(Card).filter(
                    Card.column_id == old_column_id,
                    Card.order > old_order,
                    Card.archived == False
                ).update({Card.order: Card.order - 1})

                # Increment order of cards >= new position in new column (excluding archived)
                db.query(Card).filter(
                    Card.column_id == new_column_id,
                    Card.order >= new_order,
                    Card.archived == False
                ).update({Card.order: Card.order + 1})

                card.column_id = new_column_id
                card.order = new_order
                if target_column and _is_done_like_column_name(target_column.name):
                    card.done_datetime = utc_now()

            # If reordering within the same column
            elif new_order != old_order:
                if new_order < old_order:
                    # Moving up: increment cards between new and old position (excluding archived)
                    db.query(Card).filter(
                        Card.column_id == old_column_id,
                        Card.order >= new_order,
                        Card.order < old_order,
                        Card.archived == False
                    ).update({Card.order: Card.order + 1})
                else:
                    # Moving down: decrement cards between old and new position (excluding archived)
                    db.query(Card).filter(
                        Card.column_id == old_column_id,
                        Card.order > old_order,
                        Card.order <= new_order,
                        Card.archived == False
                    ).update({Card.order: Card.order - 1})

                card.order = new_order

        # Set updated_at timestamp if user made content changes
        if user_content_changed:
            card.updated_at = utc_now()

        db.commit()
        db.refresh(card)

        result = {
            "id": card.id,
            "column_id": card.column_id,
            "title": card.title,
            "description": card.description,
            "order": card.order,
            "done": card.done,
            "done_datetime": serialize_datetime(card.done_datetime),
            "archived": card.archived,
            "start_date": serialize_datetime(card.start_date),
            "end_date": serialize_datetime(card.end_date),
            "created_at": serialize_datetime(card.created_at),
            "updated_at": serialize_datetime(card.updated_at)
        }

        # Get board_id for WebSocket broadcast
        column = db.query(BoardColumn).filter(BoardColumn.id == card.column_id).first()
        if column:
            _broadcast_event('card_updated', {
                'board_id': column.board_id,
                'card_id': card.id,
                'column_id': card.column_id,
                'card_data': result,
                'moved': old_column_id != card.column_id or old_order != card.order
            }, column.board_id, getattr(request, "sid", None))

        return create_success_response({"card": result})

    except Exception as e:
        db.rollback()
        logger.error(f"Error updating card {card_id}: {str(e)}")
        return create_error_response("Failed to update card", 500)
    finally:
        db.close()


@card_bp.route("/api/cards/<int:card_id>", methods=["DELETE"])
@require_permission('card.delete')
def delete_card(card_id):
    """Delete a card by ID.
    ---
    tags:
      - Cards
    parameters:
      - name: card_id
        in: path
        type: integer
        required: true
        description: The ID of the card to delete
    responses:
      200:
        description: Card deleted successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            message:
              type: string
              example: "Card deleted successfully"
      404:
        description: Card not found
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            message:
              type: string
              example: "Card not found"
      500:
        description: Server error
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            message:
              type: string
    """
    try:
        db = SessionLocal()

        user_id = g.user.id

        # Verify card exists and user has access to its board
        card = get_user_scoped_query(db, Card, user_id).filter(Card.id == card_id).first()

        if not card:
            db.close()
            return jsonify({"success": False, "message": "Card not found or access denied"}), 404

        # Get board_id for WebSocket broadcast before deleting
        column = db.query(BoardColumn).filter(BoardColumn.id == card.column_id).first()
        board_id = column.board_id if column else None

        db.delete(card)
        db.commit()
        db.close()

        # Broadcast card deletion
        if board_id:
            _broadcast_event('card_deleted', {
                'board_id': board_id,
                'card_id': card_id,
                'column_id': card.column_id
            }, board_id)
        else:
            logger.warning(f"⚠️  Failed to broadcast card_deleted for card {card_id}: column or board_id not found")

        return jsonify({"success": True, "message": "Card deleted successfully"}), 200
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting card {card_id}: {str(e)}")
        logger.exception(e)
        return jsonify({"success": False, "message": str(e)}), 500


@card_bp.route("/api/cards/<int:card_id>/assignees", methods=["GET"])
@require_permission('card.view')
def get_card_assignees(card_id):
    """Get primary assignee, secondary assignees, and available users for a card.
    ---
    tags:
      - Cards
    parameters:
      - name: card_id
        in: path
        type: integer
        required: true
        description: The ID of the card
    responses:
      200:
        description: Assignee info retrieved successfully
      404:
        description: Card not found
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        user_id = g.user.id
        card = get_user_scoped_query(db, Card, user_id).filter(Card.id == card_id).first()
        if not card:
            return create_error_response("Card not found or access denied", 404)

        # Resolve board_id
        column = db.query(BoardColumn).filter(BoardColumn.id == card.column_id).first()
        board_id = column.board_id if column else None

        # Primary assignee
        primary_assignee = _user_summary(card.assigned_to) if card.assigned_to else None

        # Secondary assignees
        secondary_assignees = [_user_summary(sa.user) for sa in card.secondary_assignees]

        # Build list of users with access to the card's board (for selection)
        available_users = [_user_summary(u) for u in _get_board_assignee_users(db, board_id)]

        return create_success_response({
            "primary_assignee": primary_assignee,
            "secondary_assignees": secondary_assignees,
            "available_users": available_users,
        })
    except Exception as e:
        logger.error(f"Error getting card assignees for card {card_id}: {str(e)}")
        return create_error_response("Failed to get card assignees", 500)
    finally:
        db.close()


@card_bp.route("/api/cards/<int:card_id>/assignees", methods=["PUT"])
@require_permission('card.update')
def update_card_assignees(card_id):
    """Set the primary assignee and secondary assignees of a card.
    ---
    tags:
      - Cards
    parameters:
      - name: card_id
        in: path
        type: integer
        required: true
        description: The ID of the card
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            assigned_to_id:
              type: integer
              nullable: true
              description: User ID of the primary assignee, or null to clear
            secondary_assignee_ids:
              type: array
              items:
                type: integer
              description: Full list of user IDs to set as secondary assignees
    responses:
      200:
        description: Assignees updated successfully
      400:
        description: Invalid request data
      404:
        description: Card or user not found
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        try:
            data = request.get_json()
        except Exception:
            data = None
        if data is None:
            return create_error_response("No data provided", 400)

        user_id = g.user.id
        card = get_user_scoped_query(db, Card, user_id).filter(Card.id == card_id).first()
        if not card:
            return create_error_response("Card not found or access denied", 404)

        column = db.query(BoardColumn).filter(BoardColumn.id == card.column_id).first()
        board_id = column.board_id if column else None

        eligible_assignee_ids = _get_board_eligible_assignee_ids(db, board_id)

        # Validate and set primary assignee
        if "assigned_to_id" in data:
            new_assigned_to_id = data["assigned_to_id"]
            if new_assigned_to_id is not None:
                if not isinstance(new_assigned_to_id, int) or new_assigned_to_id < 1:
                    return create_error_response("assigned_to_id must be a positive integer or null", 400)
                assignee_user = db.query(User).filter(User.id == new_assigned_to_id, User.is_active.is_(True)).first()
                if not assignee_user:
                    return create_error_response("Assigned user not found", 404)
                if new_assigned_to_id not in eligible_assignee_ids:
                    return create_error_response("Assigned user does not have access to this board", 400)
            card.assigned_to_id = new_assigned_to_id

        # Validate and replace secondary assignees
        if "secondary_assignee_ids" in data:
            secondary_assignee_ids = data["secondary_assignee_ids"]
            if not isinstance(secondary_assignee_ids, list):
                return create_error_response("secondary_assignee_ids must be a list", 400)
            for uid in secondary_assignee_ids:
                if not isinstance(uid, int) or uid < 1:
                    return create_error_response("Each secondary_assignee_id must be a positive integer", 400)
            if secondary_assignee_ids:
                valid_users = db.query(User.id).filter(
                    User.id.in_(secondary_assignee_ids),
                    User.is_active.is_(True)
                ).all()
                valid_ids = {row.id for row in valid_users}
                invalid = set(secondary_assignee_ids) - valid_ids
                if invalid:
                    return create_error_response(f"User IDs not found or inactive: {sorted(invalid)}", 400)

            ineligible = set(secondary_assignee_ids) - eligible_assignee_ids
            if ineligible:
                return create_error_response(
                    f"User IDs do not have access to this board: {sorted(ineligible)}",
                    400,
                )

            # Remove all existing secondary assignees and replace
            db.query(CardSecondaryAssignee).filter(CardSecondaryAssignee.card_id == card_id).delete()
            primary_assignee_id = card.assigned_to_id
            unique_secondary_ids = {uid for uid in secondary_assignee_ids if uid != primary_assignee_id}
            for uid in unique_secondary_ids:
                db.add(CardSecondaryAssignee(card_id=card_id, user_id=uid))

        db.commit()
        db.refresh(card)

        primary_assignee = None
        if card.assigned_to:
            primary_assignee = {
                "id": card.assigned_to.id,
                "display_name": card.assigned_to.display_name,
                "username": card.assigned_to.username,
                "profile_colour": card.assigned_to.profile_colour,
            }
        secondary_assignees = [
            {
                "id": sa.user.id,
                "display_name": sa.user.display_name,
                "username": sa.user.username,
                "profile_colour": sa.user.profile_colour,
            }
            for sa in card.secondary_assignees
        ]

        return create_success_response({
            "primary_assignee": primary_assignee,
            "secondary_assignees": secondary_assignees,
        })
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating card assignees for card {card_id}: {str(e)}")
        return create_error_response("Failed to update card assignees", 500)
    finally:
        db.close()


@card_bp.route("/api/cards/<int:card_id>/archive", methods=["PATCH"])
@require_permission('card.archive')
def archive_card(card_id):
    """Archive a card by ID.
    ---
    tags:
      - Cards
    parameters:
      - name: card_id
        in: path
        type: integer
        required: true
        description: The ID of the card to archive
    responses:
      200:
        description: Card archived successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            message:
              type: string
              example: "Card archived successfully"
      404:
        description: Card not found
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        user_id = g.user.id

        # Verify card exists and user has access to its board
        card = get_user_scoped_query(db, Card, user_id).filter(Card.id == card_id).first()

        if not card:
            return jsonify({"success": False, "message": "Card not found or access denied"}), 404

        board_id = card.column.board_id if card.column else None
        card.archived = True

        # Set updated_at timestamp
        card.updated_at = utc_now()

        db.commit()

        # Refresh and serialize the card
        db.refresh(card)
        card_dict = {
            "id": card.id,
            "column_id": card.column_id,
            "title": card.title,
            "description": card.description,
            "order": card.order,
            "archived": card.archived,
            "done": card.done,
            "done_datetime": serialize_datetime(card.done_datetime),
            "created_at": serialize_datetime(card.created_at),
            "updated_at": serialize_datetime(card.updated_at)
        }

        # Broadcast card archived event
        if board_id:
            _broadcast_event('card_archived', {
                'board_id': board_id,
                'card_id': card.id,
                'column_id': card.column_id,
                'card_data': card_dict
            }, board_id)

        return jsonify({"success": True, "message": "Card archived successfully", "card": card_dict}), 200
    except Exception as e:
        db.rollback()
        logger.error(f"Error archiving card {card_id}: {str(e)}")
        return jsonify({"success": False, "message": "Failed to archive card"}), 500
    finally:
        db.close()


@card_bp.route("/api/cards/<int:card_id>/unarchive", methods=["PATCH"])
@require_permission('card.archive')
def unarchive_card(card_id):
    """Unarchive a card by ID.
    ---
    tags:
      - Cards
    parameters:
      - name: card_id
        in: path
        type: integer
        required: true
        description: The ID of the card to unarchive
    responses:
      200:
        description: Card unarchived successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            message:
              type: string
              example: "Card unarchived successfully"
      404:
        description: Card not found
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        user_id = g.user.id

        # Verify card exists and user has access to its board
        card = get_user_scoped_query(db, Card, user_id).filter(Card.id == card_id).first()

        if not card:
            return jsonify({"success": False, "message": "Card not found or access denied"}), 404

        # Get the card's current order and column
        card_order = card.order
        column_id = card.column_id

        # Unarchive the card first
        card.archived = False

        # Set updated_at timestamp
        card.updated_at = utc_now()

        # Increment order of all active cards at this position and above
        # This ensures the unarchived card is inserted at its order position
        db.query(Card).filter(
            Card.column_id == column_id,
            Card.order >= card_order,
            Card.id != card_id,
            Card.archived == False
        ).update({Card.order: Card.order + 1}, synchronize_session=False)

        db.commit()

        # Refresh and serialize the card
        db.refresh(card)
        card_dict = {
            "id": card.id,
            "column_id": card.column_id,
            "title": card.title,
            "description": card.description,
            "order": card.order,
            "archived": card.archived,
            "done": card.done,
            "done_datetime": serialize_datetime(card.done_datetime),
            "created_at": serialize_datetime(card.created_at),
            "updated_at": serialize_datetime(card.updated_at)
        }

        # Get board_id for broadcast
        board_id = card.column.board_id if card.column else None
        if board_id:
            _broadcast_event('card_unarchived', {
                'board_id': board_id,
                'card_id': card.id,
                'column_id': card.column_id,
                'card_data': card_dict
            }, board_id)

        return jsonify({"success": True, "message": "Card unarchived successfully", "card": card_dict}), 200
    except Exception as e:
        db.rollback()
        logger.error(f"Error unarchiving card {card_id}: {str(e)}")
        return jsonify({"success": False, "message": "Failed to unarchive card"}), 500
    finally:
        db.close()


@card_bp.route("/api/cards/<int:card_id>/done", methods=["GET"])
@require_permission('card.view')
def get_card_done_status(card_id):
    """Get the done status of a card (user must have access).
    ---
    tags:
      - Cards
    parameters:
      - name: card_id
        in: path
        type: integer
        required: true
        description: The ID of the card
    responses:
      200:
        description: Card done status retrieved successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            card_id:
              type: integer
              example: 1
            done:
              type: boolean
              example: false
      401:
        description: Authentication required
      403:
        description: Permission denied
      404:
        description: Card not found
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        user_id = g.user.id
        card = get_user_scoped_query(db, Card, user_id).filter(Card.id == card_id).first()

        if not card:
            return jsonify({"success": False, "message": "Card not found"}), 404

        return jsonify({
            "success": True,
            "card_id": card.id,
            "done": card.done,
            "done_datetime": serialize_datetime(card.done_datetime)
        }), 200
    except Exception as e:
        logger.error(f"Error getting card done status {card_id}: {str(e)}")
        return jsonify({"success": False, "message": "Failed to get card done status"}), 500
    finally:
        db.close()


@card_bp.route("/api/cards/<int:card_id>/done", methods=["PATCH"])
@require_permission('card.update')
def update_card_done_status(card_id):
    """Update the done status of a card.
    ---
    tags:
      - Cards
    parameters:
      - name: card_id
        in: path
        type: integer
        required: true
        description: The ID of the card
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - done
          properties:
            done:
              type: boolean
              example: true
              description: The new done status
    responses:
      200:
        description: Card done status updated successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            message:
              type: string
              example: "Card done status updated successfully"
            card_id:
              type: integer
              example: 1
            done:
              type: boolean
              example: true
      400:
        description: Invalid request
      404:
        description: Card not found
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        data = request.get_json()

        if data is None or "done" not in data:
            return jsonify({"success": False, "message": "done status is required"}), 400

        done_status = data.get("done")
        if not isinstance(done_status, bool):
            return jsonify({"success": False, "message": "done must be a boolean"}), 400

        user_id = g.user.id

        # Verify card exists and user has access to its board
        card = get_user_scoped_query(db, Card, user_id).filter(Card.id == card_id).first()

        if not card:
            return jsonify({"success": False, "message": "Card not found or access denied"}), 404

        board_id = card.column.board_id if card.column else None
        card.done = done_status

        # Set updated_at timestamp
        now = utc_now()
        card.updated_at = now

        if (
          done_status
          and board_id is not None
          and get_board_working_style(db, board_id, fallback_user_id=user_id) == WORKING_STYLE_AGILE
        ):
          card.done_datetime = now

        db.commit()

        # Refresh card
        db.refresh(card)
        card_dict = {
            "id": card.id,
            "column_id": card.column_id,
            "title": card.title,
            "description": card.description,
            "order": card.order,
            "archived": card.archived,
            "done": card.done,
            "done_datetime": serialize_datetime(card.done_datetime)
        }

        # Broadcast card done status change event
        if board_id:
            _broadcast_event('card_done_status_changed', {
                'board_id': board_id,
                'card_id': card.id,
                'column_id': card.column_id,
                'done': done_status,
                'card_data': card_dict
            }, board_id)

        return jsonify({
            "success": True,
            "message": "Card done status updated successfully",
            "card_id": card.id,
            "done": card.done,
            "done_datetime": serialize_datetime(card.done_datetime)
        }), 200
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating card done status {card_id}: {str(e)}")
        return jsonify({"success": False, "message": "Failed to update card done status"}), 500
    finally:
        db.close()


@card_bp.route("/api/cards/batch/archive", methods=["POST"])
@require_permission('card.archive', require_board_context=False)
def batch_archive_cards():
    """Archive multiple cards in a single transaction.
    ---
    tags:
      - Cards
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - card_ids
          properties:
            card_ids:
              type: array
              items:
                type: integer
              description: List of card IDs to archive
              example: [1, 2, 3]
    responses:
      200:
        description: Cards archived successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            message:
              type: string
              example: "Archived 3 cards"
            archived_count:
              type: integer
              example: 3
      400:
        description: Invalid request
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            message:
              type: string
              example: "card_ids is required"
      500:
        description: Server error
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            message:
              type: string
    """
    db = SessionLocal()
    try:
        data = request.get_json(silent=True) or {}
        card_ids = data.get("card_ids", [])

        if not card_ids:
            return jsonify({"success": False, "message": "card_ids is required"}), 400

        if not isinstance(card_ids, list):
            return jsonify({"success": False, "message": "card_ids must be an array"}), 400

        user_id = g.user.id
        scoped_cards, scoped_card_ids = _get_fully_authorized_batch_cards(db, user_id, card_ids)

        if scoped_cards is None:
            return jsonify({
                "success": False,
                "message": "One or more selected cards were not found or are no longer accessible. No cards were archived."
            }), 404

        # Archive all authorized cards only after the full request passes validation.
        archived_count = (
            get_user_scoped_query(db, Card, user_id)
            .filter(Card.id.in_(scoped_card_ids))
            .update({Card.archived: True}, synchronize_session=False)
        )

        db.commit()

        return jsonify({
            "success": True,
            "message": f"Archived {archived_count} cards",
            "archived_count": archived_count
        }), 200
    except Exception as e:
        db.rollback()
        logger.error(f"Error batch archiving cards: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        db.close()


@card_bp.route("/api/cards/batch/unarchive", methods=["POST"])
@require_permission('card.archive', require_board_context=False)
def batch_unarchive_cards():
    """Unarchive multiple cards in a single transaction.
    ---
    tags:
      - Cards
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - card_ids
          properties:
            card_ids:
              type: array
              items:
                type: integer
              description: List of card IDs to unarchive
              example: [1, 2, 3]
    responses:
      200:
        description: Cards unarchived successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            message:
              type: string
              example: "Unarchived 3 cards"
            unarchived_count:
              type: integer
              example: 3
      400:
        description: Invalid request
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            message:
              type: string
              example: "card_ids is required"
      500:
        description: Server error
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            message:
              type: string
    """
    db = SessionLocal()
    try:
        data = request.get_json(silent=True) or {}
        card_ids = data.get("card_ids", [])

        if not card_ids:
            return jsonify({"success": False, "message": "card_ids is required"}), 400

        if not isinstance(card_ids, list):
            return jsonify({"success": False, "message": "card_ids must be an array"}), 400

        user_id = g.user.id
        cards_to_unarchive, _ = _get_fully_authorized_batch_cards(
            db,
            user_id,
            card_ids,
            order_by=(Card.column_id, Card.order)
        )

        if cards_to_unarchive is None:
            return jsonify({
                "success": False,
                "message": "One or more selected cards were not found or are no longer accessible. No cards were unarchived."
            }), 404

        if not cards_to_unarchive:
            return jsonify({"success": True, "message": "No cards found to unarchive", "unarchived_count": 0}), 200

        # Group cards by column for efficient order management
        cards_by_column = {}
        for card in cards_to_unarchive:
            if card.column_id not in cards_by_column:
                cards_by_column[card.column_id] = []
            cards_by_column[card.column_id].append(card)

        # Process each column separately to handle order conflicts
        for column_id, column_cards in cards_by_column.items():
            # Sort cards by their order
            column_cards.sort(key=lambda c: c.order)

            # For each card being unarchived, shift active cards to make room
            for card in column_cards:
                card_order = card.order

                # Increment order of all active cards at this position and above
                # This ensures the unarchived card can be inserted at its order position
                db.query(Card).filter(
                    Card.column_id == column_id,
                    Card.order >= card_order,
                    Card.id != card.id,
                    Card.archived.is_(False)
                ).update({Card.order: Card.order + 1}, synchronize_session=False)

                # Unarchive the card
                card.archived = False

                # Set updated_at timestamp
                card.updated_at = utc_now()

        db.commit()

        return jsonify({
            "success": True,
            "message": f"Unarchived {len(cards_to_unarchive)} cards",
            "unarchived_count": len(cards_to_unarchive)
        }), 200
    except Exception as e:
        db.rollback()
        logger.error(f"Error batch unarchiving cards: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        db.close()


@card_bp.route("/api/columns/<int:column_id>/archive-after", methods=["POST"])
@require_permission('card.archive')
def archive_cards_after_period(column_id):
    """Archive cards in a column that haven't been updated within a specified time period.
    ---
    tags:
      - Cards
    parameters:
      - name: column_id
        in: path
        type: integer
        required: true
        description: ID of the column
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - quantity
            - period
          properties:
            quantity:
              type: integer
              description: Numeric value for the time period
              example: 7
            period:
              type: string
              description: Time unit (minutes, hours, days, weeks)
              enum: [minutes, hours, days, weeks]
              example: days
            dry_run:
              type: boolean
              description: If true, only return preview data without archiving
              example: true
    responses:
      200:
        description: Cards archived successfully or preview returned
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            message:
              type: string
              example: "Archived 5 cards"
            archived_count:
              type: integer
              example: 5
            affected_count:
              type: integer
              description: Number of cards that would be archived (dry run only)
              example: 5
            most_recent_card:
              type: object
              description: Details of the most recent card to be archived (dry run only)
              properties:
                id:
                  type: integer
                title:
                  type: string
                updated_at:
                  type: string
                created_at:
                  type: string
      400:
        description: Invalid request
      404:
        description: Column not found
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        # Validate column exists
        column = db.query(BoardColumn).filter(BoardColumn.id == column_id).first()
        if not column:
            return jsonify({"success": False, "message": "Column not found"}), 404

        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "Request body is required"}), 400

        quantity = data.get("quantity")
        period = data.get("period")
        dry_run = data.get("dry_run", False)

        # Validate inputs
        if quantity is None:
            return jsonify({"success": False, "message": "quantity is required"}), 400

        if not isinstance(quantity, int) or quantity < 1:
            return jsonify({"success": False, "message": "quantity must be a positive integer"}), 400

        if not period:
            return jsonify({"success": False, "message": "period is required"}), 400
        if period not in ["minutes", "hours", "days", "weeks"]:
            return jsonify({"success": False, "message": "period must be one of: minutes, hours, days, weeks"}), 400

        # Calculate the cutoff datetime
        now = utc_now()
        if period == "minutes":
            cutoff = now - timedelta(minutes=quantity)
        elif period == "hours":
            cutoff = now - timedelta(hours=quantity)
        elif period == "days":
            cutoff = now - timedelta(days=quantity)
        elif period == "weeks":
            cutoff = now - timedelta(weeks=quantity)

        # Find cards that meet the criteria:
        # - In the specified column
        # - Not already archived
        # - updated_at (or created_at if updated_at is null) is older than cutoff
        query = db.query(Card).filter(
            Card.column_id == column_id,
            Card.archived == False
        )

        # Use COALESCE to handle null updated_at by falling back to created_at
        query = query.filter(
            func.coalesce(Card.updated_at, Card.created_at) < cutoff
        )

        if dry_run:
            # For dry run, get the count and the most recent card
            affected_cards = query.all()
            affected_count = len(affected_cards)

            if affected_count > 0:
                # Sort by updated_at (or created_at) descending to get most recent
                most_recent = max(
                    affected_cards,
                    key=lambda c: c.updated_at or c.created_at
                )

                return jsonify({
                    "success": True,
                    "affected_count": affected_count,
                    "most_recent_card": {
                        "id": most_recent.id,
                        "title": most_recent.title,
                        "updated_at": serialize_datetime(most_recent.updated_at),
                        "created_at": serialize_datetime(most_recent.created_at)
                    }
                }), 200
            else:
                return jsonify({
                    "success": True,
                    "affected_count": 0,
                    "most_recent_card": None
                }), 200
        else:
            # Actually archive the cards
            archived_count = query.update({Card.archived: True}, synchronize_session=False)
            db.commit()

            return jsonify({
                "success": True,
                "message": f"Archived {archived_count} cards",
                "archived_count": archived_count
            }), 200

    except Exception as e:
        db.rollback()
        logger.error(f"Error archiving cards after period: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        db.close()


# Scheduled Cards API endpoints
@card_bp.route("/api/columns/<int:column_id>/cards/scheduled", methods=["GET"])
@require_permission('card.view')
def get_scheduled_cards(column_id):
    """Get all scheduled template cards for a specific column (user must have access).
    ---
    tags:
      - Scheduled Cards
    parameters:
      - name: column_id
        in: path
        type: integer
        required: true
        description: The ID of the column
    responses:
      200:
        description: List of scheduled template cards for the column
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            cards:
              type: array
      401:
        description: Authentication required
      403:
        description: Permission denied
      500:
        description: Server error
    """
    try:
        db = SessionLocal()

        user_id = g.user.id
        # Get only scheduled template cards (scheduled=True)
        cards = (
            get_user_scoped_query(db, Card, user_id)
            .filter(Card.column_id == column_id)
            .filter(Card.scheduled.is_(True))
            .order_by(Card.order)
            .all()
        )

        cards_data = [
            {
                "id": c.id,
                "column_id": c.column_id,
                "title": c.title,
                "description": c.description,
                "order": c.order,
                "scheduled": c.scheduled,
                "schedule": c.schedule,
                "checklist_items": [
                    {
                        "id": item.id,
                        "card_id": item.card_id,
                        "name": item.name,
                        "checked": item.checked,
                        "order": item.order
                    }
                    for item in c.checklist_items
                ]
            }
            for c in cards
        ]

        db.close()
        return jsonify({"success": True, "cards": cards_data})
    except Exception as e:
        logger.error(f"Error getting scheduled cards: {str(e)}")
        return jsonify({"success": False, "message": "Failed to get scheduled cards"}), 500
