"""Board sharing (#285): owners and administrators share a board with other users.

Sharing uses the board-specific system roles: Viewer is ``board_viewer`` and
Editor is ``board_editor``. Anyone who can view a board can see who owns it and
who it is shared with; only the owner and administrators can change that.

Removing someone's access also unassigns them from the board's cards, unless
they can still see the board (as its owner or an administrator).
"""
import logging

from flask import Blueprint, g, request
from sqlalchemy.exc import IntegrityError

from database import SessionLocal
from models import Board, BoardColumn, Card, CardSecondaryAssignee, Role, User, UserRole
from notification_utils import create_notification
from permissions import has_permission
from utils import (
    create_error_response,
    create_success_response,
    get_request_socket_id,
    get_user_permissions,
    require_board_access,
    require_permission,
)

logger = logging.getLogger(__name__)

board_sharing_bp = Blueprint("board_sharing", __name__)

# Share access levels and the system roles that grant them.
ACCESS_ROLES = {
    "viewer": "board_viewer",
    "editor": "board_editor",
}
ROLE_ACCESS = {role: access for access, role in ACCESS_ROLES.items()}

# Injected at startup via configure_board_sharing_routes()
_broadcast_event = None


def configure_board_sharing_routes(broadcast_event_fn):
    """Inject runtime dependencies into this module."""
    global _broadcast_event
    _broadcast_event = broadcast_event_fn


def _user_summary(user):
    return {
        "id": user.id,
        "display_name": user.display_name,
        "username": user.username,
        "profile_colour": user.profile_colour,
    }


def _is_admin(user_id):
    return has_permission(get_user_permissions(user_id), "system.admin")


def can_share_board(board, user_id):
    """Return whether a user may change who a board is shared with.

    Args:
        board: Board row.
        user_id: ID of the user asking.

    Returns:
        True for the board owner and administrators.
    """
    return board.owner_id == user_id or _is_admin(user_id)


def _get_access_role(db, access):
    role = db.query(Role).filter(Role.name == ACCESS_ROLES[access]).first()
    if not role:
        raise ValueError(f"Required role '{ACCESS_ROLES[access]}' not found")
    return role


def get_board_members(db, board):
    """Return the people a board is shared with, owner excluded.

    Each entry has the user summary, an ``access`` of ``editor``, ``viewer``
    or ``custom`` (only roles an administrator assigned) and the role names.
    Inactive users are left out, as they can't sign in.
    """
    rows = (
        db.query(UserRole.user_id, Role.name)
        .join(Role, UserRole.role_id == Role.id)
        .filter(UserRole.board_id == board.id)
        .all()
    )
    roles_by_user = {}
    for user_id, role_name in rows:
        if user_id == board.owner_id:
            continue
        roles_by_user.setdefault(user_id, []).append(role_name)

    if not roles_by_user:
        return []

    users = (
        db.query(User)
        .filter(User.id.in_(roles_by_user.keys()), User.is_active.is_(True))
        .all()
    )
    members = []
    for user in users:
        role_names = sorted(roles_by_user[user.id])
        if "board_editor" in role_names:
            access = "editor"
        elif "board_viewer" in role_names:
            access = "viewer"
        else:
            access = "custom"
        members.append({
            "user": _user_summary(user),
            "access": access,
            "roles": role_names,
        })

    members.sort(key=lambda m: (
        (m["user"]["display_name"] or m["user"]["username"] or "").lower(),
        (m["user"]["username"] or "").lower(),
    ))
    return members


def _get_share_candidates(db, board, members):
    excluded = {m["user"]["id"] for m in members}
    if board.owner_id:
        excluded.add(board.owner_id)
    query = db.query(User).filter(User.is_active.is_(True), User.is_approved.is_(True))
    if excluded:
        query = query.filter(User.id.notin_(excluded))
    users = query.all()
    users.sort(key=lambda u: (
        (u.display_name or u.username or "").lower(),
        (u.username or "").lower(),
    ))
    return [_user_summary(u) for u in users]


def build_members_payload(db, board, user_id, include_candidates=False):
    """Build the sharing details for a board as the given user sees them."""
    can_share = can_share_board(board, user_id)
    members = get_board_members(db, board)
    payload = {
        "board_id": board.id,
        "owner": _user_summary(board.owner) if board.owner else None,
        "members": members,
        "can_share": can_share,
    }
    if include_candidates and can_share:
        payload["available_users"] = _get_share_candidates(db, board, members)
    return payload


def set_board_access(db, board_id, user_id, access):
    """Give a user exactly one share access level on a board.

    Replaces any board roles they had there. Doesn't commit.

    Returns:
        True if the user had no access to the board through a role before.
    """
    role = _get_access_role(db, access)
    existing = db.query(UserRole).filter(
        UserRole.board_id == board_id,
        UserRole.user_id == user_id,
    ).all()
    is_new = not existing
    kept = False
    for assignment in existing:
        if assignment.role_id == role.id and not kept:
            kept = True
            continue
        db.delete(assignment)
    if not kept:
        db.flush()
        db.add(UserRole(user_id=user_id, role_id=role.id, board_id=board_id))
    db.flush()
    return is_new


def unassign_user_from_board_cards(db, board_id, user_id):
    """Unassign a user from every card on a board, archived ones included.

    Doesn't commit.

    Returns:
        The number of cards changed.
    """
    card_ids = db.query(Card.id).join(BoardColumn, Card.column_id == BoardColumn.id).filter(
        BoardColumn.board_id == board_id
    )
    changed = set()

    primary_ids = [
        card_id for (card_id,) in db.query(Card.id).filter(
            Card.id.in_(card_ids), Card.assigned_to_id == user_id
        ).all()
    ]
    if primary_ids:
        db.query(Card).filter(Card.id.in_(primary_ids)).update(
            {Card.assigned_to_id: None}, synchronize_session=False
        )
        changed.update(primary_ids)

    secondary_ids = [
        card_id for (card_id,) in db.query(CardSecondaryAssignee.card_id).filter(
            CardSecondaryAssignee.card_id.in_(card_ids),
            CardSecondaryAssignee.user_id == user_id,
        ).all()
    ]
    if secondary_ids:
        db.query(CardSecondaryAssignee).filter(
            CardSecondaryAssignee.card_id.in_(secondary_ids),
            CardSecondaryAssignee.user_id == user_id,
        ).delete(synchronize_session=False)
        changed.update(secondary_ids)

    return len(changed)


def remove_board_access(db, board, user_id):
    """Remove all of a user's board roles on a board. Doesn't commit.

    If that leaves them unable to see the board, they are also unassigned from
    its cards.

    Returns:
        Tuple of (whether any role was removed, number of cards unassigned).
    """
    removed = db.query(UserRole).filter(
        UserRole.board_id == board.id,
        UserRole.user_id == user_id,
    ).delete(synchronize_session=False)

    unassigned = 0
    if board.owner_id != user_id and not _is_admin(user_id):
        unassigned = unassign_user_from_board_cards(db, board.id, user_id)
    return removed > 0, unassigned


def broadcast_members_changed(board_id):
    """Tell open copies of the board that its members changed.

    The event carries no member data: clients refetch what they may see.
    """
    if _broadcast_event:
        _broadcast_event(
            "board_members_changed",
            {"board_id": board_id},
            board_id,
            get_request_socket_id(),
        )


def _display_name(user):
    return user.display_name or user.username or "Someone"


def _notify_shared(board, recipient_id, sharer, access):
    create_notification(
        subject=f"{_display_name(sharer)} shared a board with you",
        message=(
            f"You can now {'edit' if access == 'editor' else 'view'} "
            f"the board \"{board.name}\"."
        ),
        action_title="Open board",
        action_url=f"/board.html?id={board.id}",
        user_id=recipient_id,
    )


@board_sharing_bp.route("/api/boards/<int:board_id>/members", methods=["GET"])
@require_board_access()
@require_permission("board.view")
def get_board_sharing(board_id):
    """Get the board owner and the people the board is shared with.

    Anyone who can view the board can see this. Owners and administrators
    also get the users they can share with, when include_candidates is true.
    ---
    tags:
      - Boards
    security:
      - session: []
    parameters:
      - name: board_id
        in: path
        type: integer
        required: true
        description: The ID of the board
      - name: include_candidates
        in: query
        type: boolean
        required: false
        description: Include users the board can be shared with (owners and administrators only)
    responses:
      200:
        description: Sharing details
        schema:
          type: object
          properties:
            success:
              type: boolean
            owner:
              type: object
            members:
              type: array
              items:
                type: object
                properties:
                  user:
                    type: object
                  access:
                    type: string
                    enum: [viewer, editor, custom]
                  roles:
                    type: array
                    items:
                      type: string
            can_share:
              type: boolean
            available_users:
              type: array
              items:
                type: object
      403:
        description: No access to this board
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        board = db.query(Board).filter(Board.id == board_id).first()
        if not board:
            return create_error_response("Access denied to this board", 403)
        include_candidates = request.args.get("include_candidates", "false").lower() == "true"
        return create_success_response(
            build_members_payload(db, board, g.user.id, include_candidates=include_candidates)
        )
    except Exception as e:
        logger.error(f"Error loading members for board {board_id}: {str(e)}")
        return create_error_response("Failed to load board sharing", 500)
    finally:
        db.close()


@board_sharing_bp.route("/api/boards/<int:board_id>/members/<int:user_id>", methods=["PUT"])
@require_board_access()
def share_board_with_user(board_id, user_id):
    """Share a board with a user, or change their access.

    Only the board owner and administrators can share. The user is notified
    when the board is first shared with them.
    ---
    tags:
      - Boards
    security:
      - session: []
    parameters:
      - name: board_id
        in: path
        type: integer
        required: true
        description: The ID of the board
      - name: user_id
        in: path
        type: integer
        required: true
        description: The user to share with
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - access
          properties:
            access:
              type: string
              enum: [viewer, editor]
    responses:
      200:
        description: Board shared; returns the updated sharing details
      400:
        description: Invalid access level, or the user is the owner or yourself
      403:
        description: Only the board owner or an administrator can share
      404:
        description: User not found
      500:
        description: Server error
    """
    data = request.get_json(silent=True) or {}
    access = data.get("access")
    if not isinstance(access, str) or access not in ACCESS_ROLES:
        return create_error_response("access must be 'viewer' or 'editor'", 400)

    db = SessionLocal()
    try:
        board = db.query(Board).filter(Board.id == board_id).first()
        if not board:
            return create_error_response("Access denied to this board", 403)
        if not can_share_board(board, g.user.id):
            return create_error_response(
                "Only the board owner or an administrator can share this board", 403
            )
        if user_id == g.user.id:
            return create_error_response("You can't change your own access", 400)
        if user_id == board.owner_id:
            return create_error_response("The board owner already has full access", 400)

        user = db.query(User).filter(
            User.id == user_id,
            User.is_active.is_(True),
            User.is_approved.is_(True),
        ).first()
        if not user:
            return create_error_response("User not found", 404)

        is_new = set_board_access(db, board.id, user.id, access)
        db.commit()

        logger.info(
            "Board %s shared with user %s as %s by user %s",
            board.id, user.id, access, g.user.id,
        )
        if is_new:
            _notify_shared(board, user.id, g.user, access)
        broadcast_members_changed(board.id)

        return create_success_response(
            build_members_payload(db, board, g.user.id, include_candidates=True),
            message=f"Board shared with {_display_name(user)}",
        )
    except IntegrityError:
        db.rollback()
        return create_error_response("The board's sharing changed at the same time. Please try again.", 409)
    except Exception as e:
        db.rollback()
        logger.error(f"Error sharing board {board_id} with user {user_id}: {str(e)}")
        return create_error_response("Failed to share board", 500)
    finally:
        db.close()


@board_sharing_bp.route("/api/boards/<int:board_id>/members/<int:user_id>", methods=["DELETE"])
@require_board_access()
def unshare_board_with_user(board_id, user_id):
    """Stop sharing a board with a user.

    Only the board owner and administrators can do this. The user is also
    unassigned from the board's cards, unless they can still see the board.
    ---
    tags:
      - Boards
    security:
      - session: []
    parameters:
      - name: board_id
        in: path
        type: integer
        required: true
        description: The ID of the board
      - name: user_id
        in: path
        type: integer
        required: true
        description: The user to remove
    responses:
      200:
        description: Access removed; returns the updated sharing details
      400:
        description: The user is the owner or yourself
      403:
        description: Only the board owner or an administrator can change sharing
      404:
        description: The board isn't shared with this user
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        board = db.query(Board).filter(Board.id == board_id).first()
        if not board:
            return create_error_response("Access denied to this board", 403)
        if not can_share_board(board, g.user.id):
            return create_error_response(
                "Only the board owner or an administrator can change who this board is shared with",
                403,
            )
        if user_id == g.user.id:
            return create_error_response("You can't change your own access", 400)
        if user_id == board.owner_id:
            return create_error_response("The board owner can't be removed", 400)

        removed, unassigned = remove_board_access(db, board, user_id)
        if not removed:
            db.rollback()
            return create_error_response("This board isn't shared with that user", 404)
        db.commit()

        logger.info(
            "Board %s no longer shared with user %s (removed by user %s, %s cards unassigned)",
            board.id, user_id, g.user.id, unassigned,
        )
        broadcast_members_changed(board.id)

        payload = build_members_payload(db, board, g.user.id, include_candidates=True)
        payload["cards_unassigned"] = unassigned
        return create_success_response(payload, message="Access removed")
    except Exception as e:
        db.rollback()
        logger.error(f"Error removing user {user_id} from board {board_id}: {str(e)}")
        return create_error_response("Failed to remove access", 500)
    finally:
        db.close()
