"""Schedule, checklist item, and comment route handlers."""

from flask import Blueprint, g, jsonify, request
from sqlalchemy import func
from datetime import datetime, timedelta
from typing import Any

from database import SessionLocal
from datetime_helpers import parse_iso_datetime, serialize_datetime, utc_now
from models import BoardColumn, Card, ChecklistItem, Comment, ScheduledCard
from utils import (
    MAX_COMMENT_LENGTH,
    create_error_response,
    create_success_response,
    get_request_socket_id,
    get_user_scoped_query,
    require_permission,
    sanitize_string,
    validate_integer,
    validate_string_length,
)

schedule_bp = Blueprint("schedule", __name__)

_broadcast_event = None


def configure_schedule_routes(broadcast_event_fn):
    global _broadcast_event
    _broadcast_event = broadcast_event_fn


def broadcast_event(event_name, data, board_id, skip_sid=None):
    if _broadcast_event:
        _broadcast_event(event_name, data, board_id, skip_sid)


MAX_REGENERATION_RANGE_DAYS = 90
MAX_REGENERATION_RANGE_DURATION = timedelta(days=MAX_REGENERATION_RANGE_DAYS)


def _parse_regeneration_range(payload: Any) -> tuple[datetime, datetime] | tuple[None, None]:
    """Parse and validate regeneration range payload."""
    if not isinstance(payload, dict):
        return None, None

    if not payload:
        return None, None

    start_datetime = parse_iso_datetime(payload.get('start_datetime'))
    end_datetime = parse_iso_datetime(payload.get('end_datetime'))
    if start_datetime is None or end_datetime is None:
        return None, None

    if end_datetime < start_datetime:
        return None, None

    if (end_datetime - start_datetime) > MAX_REGENERATION_RANGE_DURATION:
        return None, None

    return start_datetime, end_datetime


# ---------------------------------------------------------------------------
# Schedule endpoints
# ---------------------------------------------------------------------------


@schedule_bp.route("/api/schedules", methods=["POST"])
@require_permission('schedule.create')
def create_schedule():
    """Create a new schedule for a card.
    ---
    tags:
      - Scheduled Cards
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - card_id
            - run_every
            - unit
            - start_datetime
          properties:
            card_id:
              type: integer
            run_every:
              type: integer
            unit:
              type: string
              enum: [minute, hour, day, week, month, year]
            start_datetime:
              type: string
              format: date-time
            end_datetime:
              type: string
              format: date-time
            schedule_enabled:
              type: boolean
            allow_duplicates:
              type: boolean
            keep_source_card:
              type: boolean
    responses:
      201:
        description: Schedule created successfully
      400:
        description: Invalid input
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"success": False, "message": "Request body is required"}), 400

        # Validate required fields
        required_fields = ['card_id', 'run_every', 'unit', 'start_datetime']
        for field in required_fields:
            if field not in data:
                return jsonify({"success": False, "message": f"{field} is required"}), 400

        card_id = data['card_id']
        run_every = data['run_every']
        unit = data['unit']

        # Validate unit
        if unit not in ['minute', 'hour', 'day', 'week', 'month', 'year']:
            return jsonify({"success": False, "message": "Invalid unit"}), 400

        # Validate run_every
        if not isinstance(run_every, int) or run_every < 1:
            return jsonify({"success": False, "message": "run_every must be a positive integer"}), 400

        # Check if card exists
        card = db.query(Card).filter(Card.id == card_id).first()
        if not card:
            return jsonify({"success": False, "message": "Card not found"}), 404

        # Check if card already has a schedule reference
        if card.schedule is not None:
            return jsonify({"success": False, "message": "Card is already scheduled"}), 400

        # Parse datetimes using helper that normalizes timezone-aware input to naive UTC.
        try:
            start_datetime = parse_iso_datetime(data.get('start_datetime'))
            if start_datetime is None:
                raise ValueError('Invalid start_datetime format')

            end_datetime = None
            if 'end_datetime' in data and data['end_datetime']:
                end_datetime = parse_iso_datetime(data.get('end_datetime'))
                if end_datetime is None:
                    raise ValueError('Invalid end_datetime format')
        except (ValueError, TypeError) as e:
            return jsonify({"success": False, "message": f"Invalid datetime format: {str(e)}"}), 400

        # Capture board context for websocket broadcasts after commit.
        board_id = None
        column = db.query(BoardColumn).filter(BoardColumn.id == card.column_id).first()
        if column:
            board_id = column.board_id

        created_template_card = None
        updated_source_card = None
        deleted_source_card_id = None
        deleted_source_column_id = None

        # Check if card is already a template (scheduled=True)
        # If so, just create the schedule and link it - don't create a duplicate template
        if card.scheduled:
            # This card is already a template, just create and link the schedule
            schedule = ScheduledCard(
                card_id=card.id,
                run_every=run_every,
                unit=unit,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                schedule_enabled=data.get('schedule_enabled', True),
                allow_duplicates=data.get('allow_duplicates', False)
            )

            db.add(schedule)
            db.flush()

            # Update card's schedule reference
            card.schedule = schedule.id
            updated_source_card = card
        else:
            # Create a NEW card as the template (hidden from task views)
            template_card = Card(
                column_id=card.column_id,
                title=card.title,
                description=card.description,
                order=card.order,
                archived=False,
                scheduled=True,  # This marks it as a template (hidden from task views)
                schedule=None
            )
            db.add(template_card)
            db.flush()  # Get the new card ID

            # Copy checklist items to template
            for item in card.checklist_items:
                new_item = ChecklistItem(
                    card_id=template_card.id,
                    name=item.name,
                    checked=item.checked,
                    order=item.order
                )
                db.add(new_item)

            # Create schedule
            schedule = ScheduledCard(
                card_id=template_card.id,
                run_every=run_every,
                unit=unit,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                schedule_enabled=data.get('schedule_enabled', True),
                allow_duplicates=data.get('allow_duplicates', False)
            )

            db.add(schedule)
            db.flush()

            # Update template card's schedule reference
            template_card.schedule = schedule.id
            created_template_card = template_card

            # Handle keep_source_card parameter
            keep_source_card = data.get('keep_source_card', True)
            if keep_source_card:
                # Update ORIGINAL card's schedule reference (but keep scheduled=False so it stays visible)
                card.schedule = schedule.id
                updated_source_card = card
            else:
                # Delete the original card
                deleted_source_card_id = card.id
                deleted_source_column_id = card.column_id
                db.delete(card)

        db.commit()

        # Calculate next runs for response
        from schedule_utils import calculate_next_runs

        next_runs = calculate_next_runs(
            run_every=run_every,
            unit=unit,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            max_results=4
        )

        # Broadcast related card changes so other clients update without page refresh.
        if board_id is not None:
            socket_id = get_request_socket_id()
            if created_template_card is not None:
                broadcast_event('card_created', {
                    'board_id': board_id,
                    'column_id': created_template_card.column_id,
                    'card_id': created_template_card.id,
                    'card_data': {
                        'id': created_template_card.id,
                        'column_id': created_template_card.column_id,
                        'title': created_template_card.title,
                        'description': created_template_card.description,
                        'order': created_template_card.order,
                        'scheduled': created_template_card.scheduled,
                        'schedule': created_template_card.schedule,
                        'archived': created_template_card.archived,
                        'done': created_template_card.done,
                        'created_at': serialize_datetime(created_template_card.created_at),
                        'updated_at': serialize_datetime(created_template_card.updated_at)
                    }
                }, board_id, socket_id)

            if updated_source_card is not None:
                broadcast_event('card_updated', {
                    'board_id': board_id,
                    'card_id': updated_source_card.id,
                    'updated_fields': {
                        'schedule': updated_source_card.schedule
                    }
                }, board_id, socket_id)

            if deleted_source_card_id is not None:
                broadcast_event('card_deleted', {
                    'board_id': board_id,
                    'card_id': deleted_source_card_id,
                    'column_id': deleted_source_column_id
                }, board_id, socket_id)
        else:
            import logging
            logging.getLogger(__name__).warning(
                f"Skipping schedule-related broadcasts for schedule {schedule.id}: card {card_id} column has no board_id"
            )

        return jsonify({
            "success": True,
            "message": "Schedule created successfully",
            "schedule": {
                "id": schedule.id,
                "card_id": schedule.card_id,
                "run_every": schedule.run_every,
                "unit": schedule.unit,
                "start_datetime": serialize_datetime(schedule.start_datetime),
                "end_datetime": serialize_datetime(schedule.end_datetime),
                "schedule_enabled": schedule.schedule_enabled,
                "allow_duplicates": schedule.allow_duplicates,
                "next_runs": next_runs
            }
        }), 201

    except Exception as e:
        db.rollback()
        import logging
        logging.getLogger(__name__).error(f"Error creating schedule: {str(e)}")
        return jsonify({"success": False, "message": "Failed to create schedule"}), 500
    finally:
        db.close()


@schedule_bp.route("/api/schedules/regenerate/preview", methods=["POST"])
@require_permission('system.admin')
def preview_schedule_regeneration():
    """Preview scheduled cards that would be generated for a custom date range.
    ---
    tags:
      - Scheduled Cards
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - start_datetime
            - end_datetime
          properties:
            start_datetime:
              type: string
              format: date-time
            end_datetime:
              type: string
              format: date-time
    responses:
      200:
        description: Preview calculated successfully
      400:
        description: Invalid request body or datetime values
      500:
        description: Server error
    """
    data = request.get_json(silent=True)
    start_datetime, end_datetime = _parse_regeneration_range(data)
    if start_datetime is None or end_datetime is None:
        return jsonify({
            "success": False,
        "message": f"Valid start_datetime and end_datetime are required, end_datetime must be on or after start_datetime, and range must be <= {MAX_REGENERATION_RANGE_DAYS} days"
        }), 400

    try:
        from card_scheduler import get_scheduler as get_card_scheduler

        scheduler = get_card_scheduler()
        result = scheduler.regenerate_for_range(
            range_start=start_datetime,
            range_end=end_datetime,
            preview_only=True,
        )

        return jsonify({
            "success": True,
            "preview": result,
        })
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error previewing schedule regeneration: {str(e)}")
        return jsonify({"success": False, "message": "Failed to preview schedule regeneration"}), 500


@schedule_bp.route("/api/schedules/regenerate", methods=["POST"])
@require_permission('system.admin')
def regenerate_scheduled_cards():
    """Generate scheduled cards for a custom date range.
    ---
    tags:
      - Scheduled Cards
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - start_datetime
            - end_datetime
          properties:
            start_datetime:
              type: string
              format: date-time
            end_datetime:
              type: string
              format: date-time
    responses:
      200:
        description: Cards generated successfully
      400:
        description: Invalid request body or datetime values
      500:
        description: Server error
    """
    data = request.get_json(silent=True)
    start_datetime, end_datetime = _parse_regeneration_range(data)
    if start_datetime is None or end_datetime is None:
        return jsonify({
            "success": False,
        "message": f"Valid start_datetime and end_datetime are required, end_datetime must be on or after start_datetime, and range must be <= {MAX_REGENERATION_RANGE_DAYS} days"
        }), 400

    try:
        from card_scheduler import get_scheduler as get_card_scheduler

        scheduler = get_card_scheduler()
        result = scheduler.regenerate_for_range(
            range_start=start_datetime,
            range_end=end_datetime,
            preview_only=False,
        )

        return jsonify({
            "success": True,
            "message": "Scheduled cards generated successfully",
            "result": result,
        })
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error regenerating scheduled cards: {str(e)}")
        return jsonify({"success": False, "message": "Failed to regenerate scheduled cards"}), 500


@schedule_bp.route("/api/schedules/<int:schedule_id>", methods=["GET"])
@require_permission('schedule.view')
def get_schedule(schedule_id):
    """Get a schedule by ID with next run times.
    ---
    tags:
      - Scheduled Cards
    parameters:
      - name: schedule_id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: Schedule details
      404:
        description: Schedule not found
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        schedule = db.query(ScheduledCard).filter(ScheduledCard.id == schedule_id).first()

        if not schedule:
            return jsonify({"success": False, "message": "Schedule not found"}), 404

        # Calculate next runs
        from schedule_utils import calculate_next_runs

        next_runs = calculate_next_runs(
            run_every=schedule.run_every,
            unit=schedule.unit,
            start_datetime=schedule.start_datetime,
            end_datetime=schedule.end_datetime,
            max_results=4
        )

        return jsonify({
            "success": True,
            "schedule": {
                "id": schedule.id,
                "card_id": schedule.card_id,
                "run_every": schedule.run_every,
                "unit": schedule.unit,
                "start_datetime": serialize_datetime(schedule.start_datetime),
                "end_datetime": serialize_datetime(schedule.end_datetime),
                "schedule_enabled": schedule.schedule_enabled,
                "allow_duplicates": schedule.allow_duplicates,
                "next_runs": next_runs
            }
        })

    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error getting schedule: {str(e)}")
        return jsonify({"success": False, "message": "Failed to get schedule"}), 500
    finally:
        db.close()


@schedule_bp.route("/api/schedules/<int:schedule_id>", methods=["PUT"])
@require_permission('schedule.edit')
def update_schedule(schedule_id):
    """Update a schedule.
    ---
    tags:
      - Scheduled Cards
    parameters:
      - name: schedule_id
        in: path
        type: integer
        required: true
      - name: body
        in: body
        required: true
        schema:
          type: object
    responses:
      200:
        description: Schedule updated successfully
      404:
        description: Schedule not found
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        schedule = db.query(ScheduledCard).filter(ScheduledCard.id == schedule_id).first()

        if not schedule:
            return jsonify({"success": False, "message": "Schedule not found"}), 404

        data = request.get_json(silent=True)
        if not data:
            return jsonify({"success": False, "message": "Request body is required"}), 400

        # Update fields if provided
        if 'run_every' in data:
            if not isinstance(data['run_every'], int) or data['run_every'] < 1:
                return jsonify({"success": False, "message": "run_every must be a positive integer"}), 400
            schedule.run_every = data['run_every']

        if 'unit' in data:
            if data['unit'] not in ['minute', 'hour', 'day', 'week', 'month', 'year']:
                return jsonify({"success": False, "message": "Invalid unit"}), 400
            schedule.unit = data['unit']

        if 'start_datetime' in data:
            parsed_dt = parse_iso_datetime(data.get('start_datetime'))
            if parsed_dt is None:
                return jsonify({"success": False, "message": "Invalid start_datetime format"}), 400
            schedule.start_datetime = parsed_dt

        if 'end_datetime' in data:
            if data['end_datetime']:
                parsed_dt = parse_iso_datetime(data.get('end_datetime'))
                if parsed_dt is None:
                    return jsonify({"success": False, "message": "Invalid end_datetime format"}), 400
                schedule.end_datetime = parsed_dt
            else:
                schedule.end_datetime = None

        if 'schedule_enabled' in data:
            schedule.schedule_enabled = bool(data['schedule_enabled'])

        if 'allow_duplicates' in data:
            schedule.allow_duplicates = bool(data['allow_duplicates'])

        db.commit()

        # Calculate next runs for response
        from schedule_utils import calculate_next_runs

        next_runs = calculate_next_runs(
            run_every=schedule.run_every,
            unit=schedule.unit,
            start_datetime=schedule.start_datetime,
            end_datetime=schedule.end_datetime,
            max_results=4
        )

        return jsonify({
            "success": True,
            "message": "Schedule updated successfully",
            "schedule": {
                "id": schedule.id,
                "card_id": schedule.card_id,
                "run_every": schedule.run_every,
                "unit": schedule.unit,
                "start_datetime": serialize_datetime(schedule.start_datetime),
                "end_datetime": serialize_datetime(schedule.end_datetime),
                "schedule_enabled": schedule.schedule_enabled,
                "allow_duplicates": schedule.allow_duplicates,
                "next_runs": next_runs
            }
        })

    except Exception as e:
        db.rollback()
        import logging
        logging.getLogger(__name__).error(f"Error updating schedule: {str(e)}")
        return jsonify({"success": False, "message": "Failed to update schedule"}), 500
    finally:
        db.close()


@schedule_bp.route("/api/schedules/<int:schedule_id>", methods=["DELETE"])
@require_permission('schedule.delete')
def delete_schedule(schedule_id):
    """Delete a schedule and update related cards.
    ---
    tags:
      - Scheduled Cards
    parameters:
      - name: schedule_id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: Schedule deleted successfully
      404:
        description: Schedule not found
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        schedule = db.query(ScheduledCard).filter(ScheduledCard.id == schedule_id).first()

        if not schedule:
            return jsonify({"success": False, "message": "Schedule not found"}), 404

        template_card_id = schedule.card_id

        # Gather board context and cards impacted so we can broadcast after commit.
        impacted_card_ids = []
        template_card_column_id = None
        board_id = None

        template_card = db.query(Card).filter(Card.id == template_card_id).first()
        if template_card:
            template_card_column_id = template_card.column_id
            template_column = db.query(BoardColumn).filter(BoardColumn.id == template_card.column_id).first()
            if template_column:
                board_id = template_column.board_id

        # Clear schedule reference from all cards that reference this schedule
        # (including the original source card and any spawned cards)
        created_cards = db.query(Card).filter(Card.schedule == schedule_id).all()
        impacted_card_ids = [c.id for c in created_cards if c.id != template_card_id]
        for card in created_cards:
            card.schedule = None

        # Delete the schedule FIRST (to avoid foreign key constraint)
        db.delete(schedule)
        db.flush()

        # Then delete the template card (the hidden duplicate)
        template_card = db.query(Card).filter(Card.id == template_card_id).first()
        if template_card:
            db.delete(template_card)

        db.commit()

        # Broadcast card changes so clients in normal/scheduled views stay in sync.
        if board_id is not None:
            socket_id = get_request_socket_id()
            for impacted_card_id in impacted_card_ids:
                broadcast_event('card_updated', {
                    'board_id': board_id,
                    'card_id': impacted_card_id,
                    'updated_fields': {
                        'schedule': None
                    }
                }, board_id, socket_id)

            if template_card_column_id is not None:
                broadcast_event('card_deleted', {
                    'board_id': board_id,
                    'card_id': template_card_id,
                    'column_id': template_card_column_id
                }, board_id, socket_id)
        else:
            import logging
            logging.getLogger(__name__).warning(
                f"Skipping schedule deletion broadcasts for schedule {schedule_id}: template card board_id not found"
            )

        return jsonify({
            "success": True,
            "message": "Schedule deleted successfully"
        })

    except Exception as e:
        db.rollback()
        import logging
        logging.getLogger(__name__).error(f"Error deleting schedule: {str(e)}")
        return jsonify({"success": False, "message": "Failed to delete schedule"}), 500
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Checklist item endpoints
# ---------------------------------------------------------------------------


@schedule_bp.route("/api/cards/<int:card_id>/checklist-items", methods=["POST"])
@require_permission('card.update')
def create_checklist_item(card_id):
    """Create a new checklist item for a card.
    ---
    tags:
      - Checklist Items
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
            - name
          properties:
            name:
              type: string
              example: "Review documentation"
              description: The name of the checklist item
            checked:
              type: boolean
              example: false
              description: Whether the item is checked
            order:
              type: integer
              example: 0
              description: The order position
    responses:
      201:
        description: Checklist item created successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            checklist_item:
              type: object
              properties:
                id:
                  type: integer
                card_id:
                  type: integer
                name:
                  type: string
                checked:
                  type: boolean
                order:
                  type: integer
      400:
        description: Bad request - missing name
      404:
        description: Card not found
      500:
        description: Server error
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

        # Verify card exists
        card = db.query(Card).filter(Card.id == card_id).first()
        if not card:
            return create_error_response("Card not found", 404)

        # Validate name
        name = data.get("name")
        if not isinstance(name, str):
            return create_error_response("Name must be a string", 400)

        # Sanitize and validate length
        name = sanitize_string(name)
        if not name:
            return create_error_response("Name cannot be empty", 400)

        is_valid, error = validate_string_length(name, 500, "Name")
        if not is_valid:
            return create_error_response(error, 400)

        # Validate checked if provided
        checked = data.get("checked", False)
        if not isinstance(checked, bool):
            return create_error_response("Checked must be a boolean", 400)

        # Validate order if provided
        if "order" in data:
            order = data["order"]
            is_valid, error = validate_integer(order, "Order", min_value=0)
            if not is_valid:
                return create_error_response(error, 400)

            # Increment order of existing items >= this order to make room
            existing_items = (
                db.query(ChecklistItem)
                .filter(ChecklistItem.card_id == card_id, ChecklistItem.order >= order)
                .all()
            )
            for item_to_update in existing_items:
                item_to_update.order += 1
        else:
            # Add at the end
            order = db.query(ChecklistItem).filter(ChecklistItem.card_id == card_id).count()

        # Create checklist item
        now = utc_now()
        checklist_item = ChecklistItem(
            card_id=card_id,
            name=name,
            checked=checked,
            order=order,
            updated_at=now
        )

        db.add(checklist_item)

        # Update parent card's updated_at timestamp
        card.updated_at = utc_now()

        db.commit()
        db.refresh(checklist_item)

        # Get board_id for WebSocket broadcast
        column = db.query(BoardColumn).filter(BoardColumn.id == card.column_id).first()
        if column:
            broadcast_event('checklist_item_added', {
                'board_id': column.board_id,
                'card_id': card_id,
                'item_id': checklist_item.id,
                'item_data': {
                    'id': checklist_item.id,
                    'name': checklist_item.name,
                    'checked': checklist_item.checked,
                    'order': checklist_item.order,
                    'created_at': serialize_datetime(checklist_item.created_at),
                    'updated_at': serialize_datetime(checklist_item.updated_at)
                }
            }, column.board_id, get_request_socket_id())

        return jsonify({
            "success": True,
            "checklist_item": {
                "id": checklist_item.id,
                "card_id": checklist_item.card_id,
                "name": checklist_item.name,
                "checked": checklist_item.checked,
                "order": checklist_item.order,
                "created_at": serialize_datetime(checklist_item.created_at),
                "updated_at": serialize_datetime(checklist_item.updated_at)
            }
        }), 201

    except Exception as e:
        db.rollback()
        import logging
        logging.getLogger(__name__).error(f"Error creating checklist item for card {card_id}: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        db.close()


@schedule_bp.route("/api/checklist-items/<int:item_id>", methods=["PATCH"])
@require_permission('card.update')
def update_checklist_item(item_id):
    """Update a checklist item's name, checked status, and/or order.
    ---
    tags:
      - Checklist Items
    parameters:
      - name: item_id
        in: path
        type: integer
        required: true
        description: The ID of the checklist item to update
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            name:
              type: string
              example: "Updated item name"
            checked:
              type: boolean
              example: true
            order:
              type: integer
              example: 1
    responses:
      200:
        description: Checklist item updated successfully
      400:
        description: Bad request - no data provided or validation error
      404:
        description: Checklist item not found
      500:
        description: Server error
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

        checklist_item = db.query(ChecklistItem).filter(ChecklistItem.id == item_id).first()

        if not checklist_item:
            return create_error_response("Checklist item not found", 404)

        # Track if user made content changes (not just reordering)
        content_changed = False

        # Update name if provided
        if "name" in data:
            name = data["name"]
            if not isinstance(name, str):
                return create_error_response("Name must be a string", 400)

            name = sanitize_string(name)
            if not name:
                return create_error_response("Name cannot be empty", 400)

            is_valid, error = validate_string_length(name, 500, "Name")
            if not is_valid:
                return create_error_response(error, 400)

            checklist_item.name = name
            content_changed = True

        # Update checked if provided
        if "checked" in data:
            checked = data["checked"]
            if not isinstance(checked, bool):
                return create_error_response("Checked must be a boolean", 400)
            checklist_item.checked = checked
            content_changed = True

        # Update order if provided
        if "order" in data:
            order = data["order"]
            is_valid, error = validate_integer(order, "Order", allow_none=False, min_value=0)
            if not is_valid:
                return create_error_response(error, 400)
            checklist_item.order = order

        # Set updated_at timestamp for checklist item only if content changed (not just reordering)
        if content_changed:
            checklist_item.updated_at = utc_now()

        # Update parent card's updated_at timestamp for any checklist change (including reordering)
        card = db.query(Card).filter(Card.id == checklist_item.card_id).first()
        if card:
            card.updated_at = utc_now()

        db.commit()
        db.refresh(checklist_item)

        result = {
            "id": checklist_item.id,
            "card_id": checklist_item.card_id,
            "name": checklist_item.name,
            "checked": checklist_item.checked,
            "order": checklist_item.order,
            "created_at": serialize_datetime(checklist_item.created_at),
            "updated_at": serialize_datetime(checklist_item.updated_at)
        }

        # Get board_id for broadcast
        card = db.query(Card).filter(Card.id == checklist_item.card_id).first()
        if card and card.column:
            board_id = card.column.board_id
            broadcast_event('checklist_item_updated', {
                'board_id': board_id,
                'card_id': checklist_item.card_id,
                'item_id': checklist_item.id,
                'item_data': result
            }, board_id, get_request_socket_id())

        return jsonify({
            "success": True,
            "checklist_item": result
        }), 200

    except Exception as e:
        db.rollback()
        import logging
        logging.getLogger(__name__).error(f"Error updating checklist item {item_id}: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        db.close()


@schedule_bp.route("/api/checklist-items/<int:item_id>", methods=["DELETE"])
@require_permission('card.update')
def delete_checklist_item(item_id):
    """Delete a checklist item by ID.
    ---
    tags:
      - Checklist Items
    parameters:
      - name: item_id
        in: path
        type: integer
        required: true
        description: The ID of the checklist item to delete
    responses:
      200:
        description: Checklist item deleted successfully
      404:
        description: Checklist item not found
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        checklist_item = db.query(ChecklistItem).filter(ChecklistItem.id == item_id).first()

        if not checklist_item:
            return create_error_response("Checklist item not found", 404)

        # Get card_id before deleting
        card_id = checklist_item.card_id

        db.delete(checklist_item)

        # Update parent card's updated_at timestamp
        card = db.query(Card).filter(Card.id == card_id).first()
        if card:
            card.updated_at = utc_now()

        db.commit()

        return jsonify({"success": True, "message": "Checklist item deleted successfully"}), 200

    except Exception as e:
        db.rollback()
        import logging
        logging.getLogger(__name__).error(f"Error deleting checklist item {item_id}: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Comment endpoints
# ---------------------------------------------------------------------------


@schedule_bp.route("/api/cards/<int:card_id>/comments", methods=["GET"])
@require_permission('card.view')
def get_card_comments(card_id):
    """Get all comments for a card (user must have access).
    ---
    tags:
      - Comments
    parameters:
      - name: card_id
        in: path
        type: integer
        required: true
        description: The ID of the card
    responses:
      200:
        description: List of comments for the card
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            comments:
              type: array
              items:
                type: object
                properties:
                  id:
                    type: integer
                  card_id:
                    type: integer
                  comment:
                    type: string
                  order:
                    type: integer
                  created_at:
                    type: string
                    format: date-time
      401:
        description: Authentication required
      403:
        description: Permission denied
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        user_id = g.user.id
        comments = (
            get_user_scoped_query(db, Comment, user_id)
            .filter(Comment.card_id == card_id)
            .order_by(Comment.order.desc())  # Newest first
            .all()
        )

        return jsonify(
            {
                "success": True,
                "comments": [
                    {
                        "id": c.id,
                        "card_id": c.card_id,
                        "comment": c.comment,
                        "order": c.order,
                        "created_at": serialize_datetime(c.created_at),
                    }
                    for c in comments
                ],
            }
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error getting comments for card {card_id}: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        db.close()


@schedule_bp.route("/api/cards/<int:card_id>/comments", methods=["POST"])
@require_permission('card.update')
def create_comment(card_id):
    """Create a new comment for a card.
    ---
    tags:
      - Comments
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
            - comment
          properties:
            comment:
              type: string
              example: "This is a journal entry for the card"
              description: The comment text
    responses:
      201:
        description: Comment created successfully
      400:
        description: Bad request - missing comment or validation error
      404:
        description: Card not found
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        # Handle case where get_json() might raise an exception for empty body
        try:
            data = request.get_json()
        except Exception:
            data = None

        if not data or "comment" not in data:
            return create_error_response("Comment text is required", 400)

        # Verify card exists
        card = db.query(Card).filter(Card.id == card_id).first()
        if not card:
            return create_error_response("Card not found", 404)

        # Validate and sanitize comment
        comment_text = data.get("comment")
        if not isinstance(comment_text, str):
            return create_error_response("Comment must be a string", 400)

        comment_text = sanitize_string(comment_text)
        if not comment_text:
            return create_error_response("Comment cannot be empty", 400)

        is_valid, error = validate_string_length(
            comment_text, MAX_COMMENT_LENGTH, "Comment"
        )
        if not is_valid:
            return create_error_response(error, 400)

        # Get next order number (max + 1) with row-level locking to prevent race conditions
        # FOR UPDATE locks the row until the transaction commits, ensuring sequential order assignment
        max_order = (
            db.query(func.max(Comment.order))
            .filter(Comment.card_id == card_id)
            .with_for_update()
            .scalar()
        )
        next_order = (max_order + 1) if max_order is not None else 0

        # Create comment
        comment = Comment(
            card_id=card_id,
            comment=comment_text,
            order=next_order
        )
        db.add(comment)

        # Update parent card's updated_at timestamp
        card.updated_at = utc_now()

        db.commit()
        db.refresh(comment)

        result = {
            "id": comment.id,
            "card_id": comment.card_id,
            "comment": comment.comment,
            "order": comment.order,
            "created_at": serialize_datetime(comment.created_at),
        }

        return create_success_response({"comment": result}, status_code=201)

    except Exception as e:
        db.rollback()
        import logging
        logging.getLogger(__name__).error(f"Error creating comment for card {card_id}: {str(e)}")
        return create_error_response("Failed to create comment", 500)
    finally:
        db.close()


@schedule_bp.route("/api/comments/<int:comment_id>", methods=["DELETE"])
@require_permission('card.update')
def delete_comment(comment_id):
    """Delete a comment by ID.

    Note: The order field is preserved in the database to maintain conversation history.
    Deleted comments leave gaps in the order sequence.
    ---
    tags:
      - Comments
    parameters:
      - name: comment_id
        in: path
        type: integer
        required: true
        description: The ID of the comment to delete
    responses:
      200:
        description: Comment deleted successfully
      404:
        description: Comment not found
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        comment = db.query(Comment).filter(Comment.id == comment_id).first()

        if not comment:
            return create_error_response("Comment not found", 404)

        # Get card_id before deleting
        card_id = comment.card_id

        db.delete(comment)

        # Update parent card's updated_at timestamp
        card = db.query(Card).filter(Card.id == card_id).first()
        if card:
            card.updated_at = utc_now()

        db.commit()

        return jsonify({"success": True, "message": "Comment deleted successfully"}), 200

    except Exception as e:
        db.rollback()
        import logging
        logging.getLogger(__name__).error(f"Error deleting comment {comment_id}: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        db.close()
