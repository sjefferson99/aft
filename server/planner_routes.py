"""Planner routes blueprint.

Read-only endpoints backing the year/month planner views:
  GET /api/boards/<id>/planner/year/<year>
  GET /api/boards/<id>/planner/month/<year>/<month>
"""
from flask import Blueprint, jsonify, request

from database import SessionLocal
from planner_utils import get_month_planner_data, get_year_planner_data
from utils import create_error_response, require_board_access, require_permission

planner_bp = Blueprint("planner", __name__)


def _include_scheduled_param() -> bool:
    return request.args.get("include_scheduled", "false").lower() == "true"


@planner_bp.route("/api/boards/<int:board_id>/planner/year/<int:year>", methods=["GET"])
@require_board_access()
@require_permission('board.view')
def get_board_planner_year(board_id, year):
    """Free/busy day status for every day of a calendar year.
    ---
    tags:
      - Planner
    parameters:
      - name: board_id
        in: path
        required: true
        type: integer
      - name: year
        in: path
        required: true
        type: integer
      - name: include_scheduled
        in: query
        required: false
        type: string
        enum: ['true', 'false']
        default: 'false'
        description: Also project future recurring-schedule occurrences into the busy days
    responses:
      200:
        description: Year planner data
      403:
        description: Insufficient permissions
    """
    db = SessionLocal()
    try:
        data = get_year_planner_data(db, board_id, year, _include_scheduled_param())
        return jsonify({"success": True, **data}), 200
    finally:
        db.close()


@planner_bp.route("/api/boards/<int:board_id>/planner/month/<int:year>/<int:month>", methods=["GET"])
@require_board_access()
@require_permission('board.view')
def get_board_planner_month(board_id, year, month):
    """Cards (and optionally projected schedule occurrences) overlapping a calendar month.
    ---
    tags:
      - Planner
    parameters:
      - name: board_id
        in: path
        required: true
        type: integer
      - name: year
        in: path
        required: true
        type: integer
      - name: month
        in: path
        required: true
        type: integer
      - name: include_scheduled
        in: query
        required: false
        type: string
        enum: ['true', 'false']
        default: 'false'
        description: Also include projected future occurrences of recurring schedules
    responses:
      200:
        description: Month planner data
      400:
        description: Invalid month
      403:
        description: Insufficient permissions
    """
    if month < 1 or month > 12:
        return create_error_response("Month must be between 1 and 12", 400)

    db = SessionLocal()
    try:
        data = get_month_planner_data(db, board_id, year, month, _include_scheduled_param())
        return jsonify({"success": True, **data}), 200
    finally:
        db.close()
