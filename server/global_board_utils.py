"""Shared rules for global boards (#663).

A global board shows cards promoted from agile boards in the states New, In
Progress, Waiting and Done. Done is not stored here: a promoted card with
``Card.done`` set shows as done and keeps its stored state, so unticking done
returns it to that state.

Every route asks these functions who can see a global board, which global
boards a board can promote to, and how done changes, so later visibility rules
and several global boards only change this module.
"""
from models import Board, GlobalBoard, GlobalBoardCard
from settings_schema import WORKING_STYLE_AGILE, get_board_working_style

GLOBAL_STATE_NEW = 'new'
GLOBAL_STATE_IN_PROGRESS = 'in_progress'
GLOBAL_STATE_WAITING = 'waiting'
GLOBAL_STATE_DONE = 'done'

# States a promotion can hold. Done comes from Card.done instead.
GLOBAL_STORED_STATES = (GLOBAL_STATE_NEW, GLOBAL_STATE_IN_PROGRESS, GLOBAL_STATE_WAITING)
GLOBAL_STATES = GLOBAL_STORED_STATES + (GLOBAL_STATE_DONE,)

VISIBILITY_EVERYONE = 'everyone'
GLOBAL_BOARD_VISIBILITIES = (VISIBILITY_EVERYONE,)

GLOBAL_BOARD_NAME_MAX_LENGTH = 100
DONE_VISIBLE_DAYS_MIN = 1
DONE_VISIBLE_DAYS_MAX = 3650


def can_access_global_board(user_id, global_board):
    """Return whether a user can see a global board.

    Args:
        user_id: ID of the user asking.
        global_board: GlobalBoard row, or None.

    Returns:
        True if the user may read it. Cards on it are still scoped per board.
    """
    if global_board is None or not user_id:
        return False
    return global_board.visibility == VISIBILITY_EVERYONE


def get_accessible_global_boards(db, user_id):
    """Return the global boards a user can see, in id order."""
    boards = db.query(GlobalBoard).order_by(GlobalBoard.id).all()
    return [board for board in boards if can_access_global_board(user_id, board)]


def get_accessible_global_board(db, user_id, global_board_id):
    """Return one global board if the user can see it, otherwise None."""
    board = db.query(GlobalBoard).filter(GlobalBoard.id == global_board_id).first()
    return board if can_access_global_board(user_id, board) else None


def _board_global_board_ids(db, board):
    """Return the ids of the global boards a board feeds, ignoring the user.

    In the MVP every agile board feeds every global board, which is the single
    instance board. Linking boards to particular global boards later only
    changes this function.
    """
    if board is None or get_board_working_style(db, board.id) != WORKING_STYLE_AGILE:
        return set()
    return {global_board_id for (global_board_id,) in db.query(GlobalBoard.id).all()}


def get_eligible_global_boards(db, board_id, user_id):
    """Return the global boards a board's cards can be promoted to by this user.

    This is the only place that decides eligibility. The promote route rejects a
    global board missing from this list, and the Promote button reads it.

    Args:
        db: Database session.
        board_id: Source (epic) board id.
        user_id: ID of the user promoting.

    Returns:
        List of GlobalBoard rows in id order.
    """
    board = db.query(Board).filter(Board.id == board_id).first()
    eligible_ids = _board_global_board_ids(db, board)
    if not eligible_ids:
        return []
    return [
        global_board
        for global_board in get_accessible_global_boards(db, user_id)
        if global_board.id in eligible_ids
    ]


def get_card_promotion(db, card_id):
    """Return a card's GlobalBoardCard row, or None if it isn't promoted."""
    return db.query(GlobalBoardCard).filter(GlobalBoardCard.card_id == card_id).first()


def apply_card_done(db, card, done, now, board_id=None):
    """Set a card's done flag, keeping done_datetime in step.

    Used by the done route and the global board, so both record the same thing.
    done_datetime is recorded on agile boards and for promoted cards on any
    board, because the global board's done window depends on it. It is cleared
    when a done card is unticked, so a stale time never lingers.

    Args:
        db: Database session.
        card: Card row to change.
        done: New done value.
        now: Timestamp to record.
        board_id: The card's board id, if the caller already has it.
    """
    was_done = bool(card.done)
    card.done = done
    card.updated_at = now

    if done:
        if board_id is None and card.column is not None:
            board_id = card.column.board_id
        is_agile = (
            board_id is not None
            and get_board_working_style(db, board_id) == WORKING_STYLE_AGILE
        )
        if is_agile or get_card_promotion(db, card.id) is not None:
            card.done_datetime = now
    elif was_done:
        card.done_datetime = None


def remove_ineligible_promotions(db, card_ids, target_board_id):
    """Demote cards that moved to a board that doesn't feed their global board.

    A card moved to a kanban board stays promoted, as cards do when their own
    board switches to kanban. Call before committing a cross-board move.

    Args:
        db: Database session.
        card_ids: IDs of the moved cards.
        target_board_id: Board the cards moved to.

    Returns:
        Number of promotions removed.
    """
    if not card_ids:
        return 0

    target_board = db.query(Board).filter(Board.id == target_board_id).first()
    if target_board is None:
        return 0
    if get_board_working_style(db, target_board.id) != WORKING_STYLE_AGILE:
        return 0

    eligible_ids = _board_global_board_ids(db, target_board)
    query = db.query(GlobalBoardCard).filter(GlobalBoardCard.card_id.in_(list(card_ids)))
    if eligible_ids:
        query = query.filter(GlobalBoardCard.global_board_id.notin_(eligible_ids))
    return query.delete(synchronize_session=False)

