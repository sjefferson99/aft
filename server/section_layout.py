"""Board layout helpers for the sections layout (#297).

A board shows its columns either side by side (``columns``, the default) or
as sections stacked in lanes (``sections``). The layout is a board setting.
Each column's lane and position in the sections layout are stored on the
column, separate from its column order.
"""
import json

from models import BoardSetting

BOARD_LAYOUT_KEY = 'board_layout'
BOARD_LAYOUT_COLUMNS = 'columns'
BOARD_LAYOUT_SECTIONS = 'sections'
BOARD_LAYOUT_ALLOWED_VALUES = (BOARD_LAYOUT_COLUMNS, BOARD_LAYOUT_SECTIONS)

# There's no limit on lanes. Stored lanes are renumbered without gaps on
# every save, so a lane number is never more than the number of columns; this
# only keeps values inside the database's integer column.
MAX_SECTION_POSITION = 2 ** 31 - 1


def parse_board_layout(raw_value):
    """Parse a stored board layout value, falling back to columns.

    Args:
        raw_value: The JSON-encoded setting value, or None.

    Returns:
        ``'columns'`` or ``'sections'``.
    """
    try:
        value = json.loads(raw_value) if raw_value is not None else None
    except (TypeError, ValueError):
        value = raw_value
    return value if value in BOARD_LAYOUT_ALLOWED_VALUES else BOARD_LAYOUT_COLUMNS


def get_board_layout(db, board_id):
    """Return the layout of a board.

    Args:
        db: Database session.
        board_id: Board ID.

    Returns:
        ``'columns'`` or ``'sections'``.
    """
    setting = db.query(BoardSetting.value).filter(
        BoardSetting.board_id == board_id,
        BoardSetting.key == BOARD_LAYOUT_KEY,
    ).first()
    return parse_board_layout(setting[0] if setting else None)


def is_valid_section_position(value):
    """Return True if value is a usable stored lane or section order."""
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= MAX_SECTION_POSITION
    )


def compact_section_lanes(lanes):
    """Renumber lanes 0, 1, 2... in the same order, closing any gaps.

    An emptied lane closes up, and a huge lane number can't make clients draw
    empty lanes up to it.

    Args:
        lanes: Lane numbers, one per section, in any order.

    Returns:
        Dict mapping each lane number given to its compacted number.

    Example:
        >>> compact_section_lanes([5, 0, 5, 9])
        {0: 0, 5: 1, 9: 2}
    """
    return {lane: index for index, lane in enumerate(sorted(set(lanes)))}


def section_layout_fields(column):
    """Return the section layout fields for a serialized column."""
    return {
        "section_lane": column.section_lane,
        "section_order": column.section_order,
    }
