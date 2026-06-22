"""Helpers for the year/month planner views.

Computes which days of a board are "free" or "busy" (i.e. have at least one
card scheduled on/through them), and the card data needed to render a month
grid. Naming here intentionally uses free/busy rather than success/error -
those are theme colour variables applied by the frontend, not a data concept.
"""
import calendar
from datetime import date, datetime, timedelta

from sqlalchemy import and_, or_

from datetime_helpers import serialize_datetime
from models import BoardColumn, Card, ScheduledCard
from schedule_utils import calculate_occurrences_in_range, get_template_duration


def _card_overlap_filter(range_start: datetime, range_end: datetime):
    """Card.start_date/end_date overlaps [range_start, range_end].

    A card with no end_date is treated as occupying just its start_date.
    """
    return and_(
        Card.start_date.isnot(None),
        Card.start_date <= range_end,
        or_(
            and_(Card.end_date.is_(None), Card.start_date >= range_start),
            and_(Card.end_date.isnot(None), Card.end_date >= range_start),
        ),
    )


def _busy_dates_from_cards(rows, range_start: date, range_end: date) -> set:
    busy_dates = set()
    for start_date, end_date in rows:
        span_start = max(start_date.date(), range_start)
        span_end = min((end_date or start_date).date(), range_end)
        current = span_start
        while current <= span_end:
            busy_dates.add(current)
            current += timedelta(days=1)
    return busy_dates


def _enabled_schedules_for_board(db, board_id):
    return (
        db.query(ScheduledCard)
        .join(Card, ScheduledCard.card_id == Card.id)
        .join(BoardColumn, Card.column_id == BoardColumn.id)
        .filter(
            BoardColumn.board_id == board_id,
            ScheduledCard.schedule_enabled.is_(True),
        )
        .all()
    )


def _busy_dates_from_schedules(db, board_id, range_start: datetime, range_end: datetime) -> set:
    busy_dates = set()
    for schedule in _enabled_schedules_for_board(db, board_id):
        duration = get_template_duration(schedule.template_card)
        occurrences = calculate_occurrences_in_range(
            schedule.run_every,
            schedule.unit,
            schedule.start_datetime,
            schedule.end_datetime,
            range_start,
            range_end,
            duration,
        )
        for occurrence in occurrences:
            span_start = max(occurrence["start"].date(), range_start.date())
            span_end = min(occurrence["end"].date(), range_end.date())
            current = span_start
            while current <= span_end:
                busy_dates.add(current)
                current += timedelta(days=1)
    return busy_dates


def get_year_planner_data(db, board_id: int, year: int, include_scheduled: bool) -> dict:
    """Free/busy/scheduled day status for every day of a calendar year, grouped by month.

    A day is "busy" if it has at least one real card on/through it, "scheduled"
    if it only has a projected recurring-schedule occurrence (no real card),
    and otherwise "free". busy_days takes precedence over scheduled_days when
    a day has both - the frontend applies that precedence when colouring.
    """
    range_start = datetime(year, 1, 1)
    range_end = datetime(year, 12, 31, 23, 59, 59)

    rows = (
        db.query(Card.start_date, Card.end_date)
        .join(BoardColumn, Card.column_id == BoardColumn.id)
        .filter(
            BoardColumn.board_id == board_id,
            Card.archived.is_(False),
            Card.scheduled.is_(False),
            _card_overlap_filter(range_start, range_end),
        )
        .all()
    )
    busy_dates = _busy_dates_from_cards(rows, range_start.date(), range_end.date())

    scheduled_dates = set()
    if include_scheduled:
        scheduled_dates = _busy_dates_from_schedules(db, board_id, range_start, range_end)

    months = []
    for month in range(1, 13):
        busy_days = sorted(d.day for d in busy_dates if d.year == year and d.month == month)
        scheduled_days = sorted(d.day for d in scheduled_dates if d.year == year and d.month == month)
        months.append({"month": month, "busy_days": busy_days, "scheduled_days": scheduled_days})

    return {"year": year, "months": months}


def get_month_planner_data(db, board_id: int, year: int, month: int, include_scheduled: bool) -> dict:
    """Real (and optionally projected virtual) cards overlapping a calendar month."""
    last_day = calendar.monthrange(year, month)[1]
    range_start = datetime(year, month, 1)
    range_end = datetime(year, month, last_day, 23, 59, 59)

    card_rows = (
        db.query(Card)
        .join(BoardColumn, Card.column_id == BoardColumn.id)
        .filter(
            BoardColumn.board_id == board_id,
            Card.archived.is_(False),
            Card.scheduled.is_(False),
            _card_overlap_filter(range_start, range_end),
        )
        .all()
    )

    cards = [
        {
            "id": card.id,
            "title": card.title,
            "column_id": card.column_id,
            "done": card.done,
            "start_date": serialize_datetime(card.start_date),
            "end_date": serialize_datetime(card.end_date),
        }
        for card in card_rows
    ]

    virtual = []
    if include_scheduled:
        for schedule in _enabled_schedules_for_board(db, board_id):
            duration = get_template_duration(schedule.template_card)
            occurrences = calculate_occurrences_in_range(
                schedule.run_every,
                schedule.unit,
                schedule.start_datetime,
                schedule.end_datetime,
                range_start,
                range_end,
                duration,
            )
            for occurrence in occurrences:
                virtual.append({
                    "is_virtual": True,
                    "schedule_id": schedule.id,
                    "template_card_id": schedule.card_id,
                    "title": schedule.template_card.title,
                    "start_date": serialize_datetime(occurrence["start"]),
                    "end_date": serialize_datetime(occurrence["end"]),
                })

    return {"year": year, "month": month, "cards": cards, "virtual": virtual}
