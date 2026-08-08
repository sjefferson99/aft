"""Column routes blueprint.

Extracted from app.py – all /api/boards/<id>/columns and /api/columns endpoints.
"""
from flask import Blueprint, jsonify, request
import logging
from database import SessionLocal
from datetime_helpers import serialize_datetime, utc_now
from models import Board, BoardColumn
from utils import (
    MAX_TITLE_LENGTH,
    create_error_response,
    create_success_response,
    get_current_user_id,
    get_request_socket_id,
    get_user_scoped_query,
    require_board_access,
    require_permission,
    sanitize_string,
    validate_integer,
    validate_string_length,
)

logger = logging.getLogger(__name__)

column_bp = Blueprint("column", __name__)

# Injected at startup via configure_column_routes()
_broadcast_event = None


def configure_column_routes(broadcast_event_fn):
    """Inject runtime dependencies into this module."""
    global _broadcast_event
    _broadcast_event = broadcast_event_fn


@column_bp.route("/api/boards/<int:board_id>/columns", methods=["GET"])
@require_board_access()
def get_board_columns(board_id):
    """Get all columns for a specific board (user must have access).
    ---
    tags:
      - Columns
    parameters:
      - name: board_id
        in: path
        type: integer
        required: true
        description: The ID of the board
    responses:
      200:
        description: List of columns for the board
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            columns:
              type: array
              items:
                type: object
                properties:
                  id:
                    type: integer
                    example: 1
                  board_id:
                    type: integer
                    example: 1
                  name:
                    type: string
                    example: "To Do"
                  order:
                    type: integer
                    example: 0
      401:
        description: Authentication required
      403:
        description: Access denied to this board
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
        # Access already validated by @require_board_access decorator
        columns = (
            db.query(BoardColumn)
            .filter(BoardColumn.board_id == board_id)
            .order_by(BoardColumn.order)
            .all()
        )
        return jsonify(
            {
                "success": True,
                "columns": [
                    {
                        "id": c.id,
                        "board_id": c.board_id,
                        "name": c.name,
                        "order": c.order,
                        "created_at": serialize_datetime(c.created_at),
                        "updated_at": serialize_datetime(c.updated_at)
                    }
                    for c in columns
                ],
            }
        )
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        db.close()


@column_bp.route("/api/boards/<int:board_id>/columns", methods=["POST"])
@require_board_access()
@require_permission('column.create')
def create_column(board_id):
    """Create a new column for a board with input validation.

    This endpoint creates a new column after validating:
    - Name is provided, is a string, and within length limits
    - Order (if provided) is a valid non-negative integer
    - Board exists

    ---
    tags:
      - Columns
    parameters:
      - name: board_id
        in: path
        type: integer
        required: true
        description: The ID of the board
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - name
          properties:
            name:
              type: string
              example: "To Do"
              description: The name of the column to create
            order:
              type: integer
              example: 0
              description: The order position of the column (optional, defaults to last)
    responses:
      201:
        description: Column created successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            column:
              type: object
              properties:
                id:
                  type: integer
                  example: 1
                board_id:
                  type: integer
                  example: 1
                name:
                  type: string
                  example: "To Do"
                order:
                  type: integer
                  example: 0
      400:
        description: Bad request - missing name
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            message:
              type: string
              example: "Name is required"
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
    db = SessionLocal()
    try:
        # Handle case where get_json() might raise an exception for empty body
        try:
            data = request.get_json()
        except Exception:
            data = None

        if not data or "name" not in data:
            return create_error_response("Name is required", 400)

        # Verify board exists
        board = db.query(Board).filter(Board.id == board_id).first()
        if not board:
            return create_error_response("Board not found", 404)

        # Validate and sanitize name
        name = data.get("name")
        if not isinstance(name, str):
            return create_error_response("Name must be a string", 400)

        name = sanitize_string(name)
        if not name:
            return create_error_response("Name cannot be empty", 400)

        is_valid, error = validate_string_length(name, MAX_TITLE_LENGTH, "Name")
        if not is_valid:
            return create_error_response(error, 400)

        if "order" in data:
            order = data["order"]
            is_valid, error = validate_integer(order, "Order", min_value=0)
            if not is_valid:
                return create_error_response(error, 400)
        else:
            max_order = (
                db.query(BoardColumn).filter(BoardColumn.board_id == board_id).count()
            )
            order = max_order

        now = utc_now()
        column = BoardColumn(board_id=board_id, name=name, order=order, updated_at=now)
        db.add(column)
        db.commit()
        db.refresh(column)

        result = {
            "id": column.id,
            "board_id": column.board_id,
            "name": column.name,
            "order": column.order,
            "created_at": serialize_datetime(column.created_at),
            "updated_at": serialize_datetime(column.updated_at)
        }

        # Broadcast column creation so other connected clients can refresh immediately.
        _broadcast_event('column_created', {
            'board_id': board_id,
            'column_id': column.id,
            'column_data': result
        }, board_id, get_request_socket_id())

        return create_success_response({"column": result}, status_code=201)

    except Exception as e:
        db.rollback()
        logger.error(f"Error creating column for board {board_id}: {str(e)}")
        return create_error_response("Failed to create column", 500)
    finally:
        db.close()


@column_bp.route("/api/columns/<int:column_id>", methods=["DELETE"])
@require_permission('column.delete')
def delete_column(column_id):
    """Delete a column by ID.
    ---
    tags:
      - Columns
    parameters:
      - name: column_id
        in: path
        type: integer
        required: true
        description: The ID of the column to delete
    responses:
      200:
        description: Column deleted successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            message:
              type: string
              example: "Column deleted successfully"
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
        column = db.query(BoardColumn).filter(BoardColumn.id == column_id).first()

        if not column:
            return jsonify({"success": False, "message": "Column not found"}), 404

        # Verify user owns the board this column belongs to
        board = get_user_scoped_query(db, Board, user_id).filter(Board.id == column.board_id).first()
        if not board:
            return jsonify({"success": False, "message": "Access denied"}), 403

        board_id = column.board_id

        db.delete(column)
        db.commit()

        # Broadcast column deletion so other clients can refresh immediately.
        _broadcast_event('column_deleted', {
            'board_id': board_id,
            'column_id': column_id
        }, board_id, get_request_socket_id())

        return jsonify({"success": True, "message": "Column deleted successfully"}), 200
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        db.close()


@column_bp.route("/api/columns/<int:column_id>", methods=["PATCH"])
@require_permission('column.update')
def update_column(column_id):
    """Update a column's name and/or order.
    ---
    tags:
      - Columns
    parameters:
      - name: column_id
        in: path
        type: integer
        required: true
        description: The ID of the column to update
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            name:
              type: string
              example: "In Progress"
              description: The new name for the column
            order:
              type: integer
              example: 1
              description: The new order position (columns >= this order will be incremented)
    responses:
      200:
        description: Column updated successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            column:
              type: object
              properties:
                id:
                  type: integer
                  example: 1
                board_id:
                  type: integer
                  example: 1
                name:
                  type: string
                  example: "In Progress"
                order:
                  type: integer
                  example: 0
      400:
        description: Bad request
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            message:
              type: string
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

        if not data:
            return create_error_response("No data provided", 400)

        user_id = get_current_user_id()
        column = db.query(BoardColumn).filter(BoardColumn.id == column_id).first()

        if not column:
            return create_error_response("Column not found", 404)

        # Verify user owns the board this column belongs to
        board = get_user_scoped_query(db, Board, user_id).filter(Board.id == column.board_id).first()
        if not board:
            return create_error_response("Access denied", 403)

        old_order = column.order
        board_id = column.board_id

        # Track if user changed the name (not just reordering)
        name_changed = False

        # Update and validate name if provided
        if "name" in data:
            name = data["name"]
            if not isinstance(name, str):
                return create_error_response("Name must be a string", 400)

            name = sanitize_string(name)
            if not name:
                return create_error_response("Name cannot be empty", 400)

            is_valid, error = validate_string_length(name, MAX_TITLE_LENGTH, "Name")
            if not is_valid:
                return create_error_response(error, 400)

            column.name = name
            name_changed = True

        # Handle order change if provided
        if "order" in data:
            new_order = data["order"]

            is_valid, error = validate_integer(new_order, "Order", min_value=0)
            if not is_valid:
                return create_error_response(error, 400)

            if new_order != old_order:
                if new_order < old_order:
                    # Moving left: increment columns between new and old position
                    columns_to_update = (
                        db.query(BoardColumn)
                        .filter(
                            BoardColumn.board_id == board_id,
                            BoardColumn.order >= new_order,
                            BoardColumn.order < old_order,
                        )
                        .all()
                    )
                    for col in columns_to_update:
                        col.order += 1
                else:
                    # Moving right: decrement columns between old and new position
                    columns_to_update = (
                        db.query(BoardColumn)
                        .filter(
                            BoardColumn.board_id == board_id,
                            BoardColumn.order > old_order,
                            BoardColumn.order <= new_order,
                        )
                        .all()
                    )
                    for col in columns_to_update:
                        col.order -= 1

                column.order = new_order

        # Set updated_at timestamp only if name changed (not just reordering)
        if name_changed:
            column.updated_at = utc_now()

        db.commit()
        db.refresh(column)
        result = {
            "id": column.id,
            "board_id": column.board_id,
            "name": column.name,
            "order": column.order,
            "created_at": serialize_datetime(column.created_at),
            "updated_at": serialize_datetime(column.updated_at)
        }

        # Broadcast column update event
        _broadcast_event('column_updated', {
            'board_id': board_id,
            'column_id': column.id,
            'column_data': result
        }, board_id, get_request_socket_id())

        return jsonify({"success": True, "column": result}), 200
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        db.close()
