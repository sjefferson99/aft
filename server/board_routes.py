"""Board routes blueprint.

Extracted from app.py – all /api/boards endpoints plus the board-level
helper functions that are also consumed by the card routes still in app.py.
"""
from flask import Blueprint, jsonify, request, send_file, g
import io
import json
import logging
import os
import re
import secrets
import string
import threading
import time
from sqlalchemy import and_, exists, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from database import SessionLocal
from models import (
    Board,
    BoardColumn,
    BoardSetting,
    Card,
    CardSecondaryAssignee,
    ChecklistItem,
    Comment,
    Role,
    ScheduledCard,
    Setting,
    User,
    UserRole,
)
from utils import (
    MAX_COMMENT_LENGTH,
    MAX_DESCRIPTION_LENGTH,
    MAX_TITLE_LENGTH,
    create_error_response,
    create_success_response,
    get_current_user_id,
    get_user_permissions,
    get_user_scoped_query,
    require_authentication,
    require_board_access,
    require_permission,
    sanitize_string,
    validate_string_length,
)
from board_import_handlers import ImportHandlerFactory
from datetime_helpers import parse_iso_datetime, serialize_datetime, utc_now
from security_validators import validate_json_import_payload_size
from settings_schema import get_user_default_working_style
from theme_defaults import get_instance_default_theme
from permissions import has_permission

logger = logging.getLogger(__name__)

board_bp = Blueprint("board", __name__)

# Injected at startup via configure_board_routes()
_APP_VERSION = "unknown"

# Board import/export constants
MAX_BOARD_IMPORT_FILE_SIZE_MB = 25
BOARD_EXPORT_FORMAT = "aft-board"
PUBLIC_SLUG_LENGTH = 12
PUBLIC_SLUG_ALPHABET = string.ascii_lowercase + string.digits
PUBLIC_SLUG_PATTERN = re.compile(rf"^[a-z0-9]{{{PUBLIC_SLUG_LENGTH}}}$")
PUBLIC_BOARD_RATE_LIMIT_PER_MINUTE = max(
    1,
    int(os.getenv("PUBLIC_BOARD_RATE_LIMIT_PER_MINUTE", "120")),
)
PUBLIC_BOARD_RATE_LIMIT_WINDOW_SECONDS = 60

_public_rate_limit_store = {
    "buckets": {},
    "lock": threading.Lock(),
}
_public_rate_limit_redis = None
_public_rate_limit_redis_init = False

CARD_ID_SEARCH_TOKEN_PATTERN = re.compile(r"^#[1-9][0-9]*$")
TEXT_SEARCH_MIN_QUERY_LENGTH = 2
TEXT_SEARCH_MAX_QUERY_LENGTH = 200
TEXT_SEARCH_MAX_OR_GROUPS = 12
TEXT_SEARCH_MAX_TOTAL_TERMS = 24
TEXT_SEARCH_MAX_TERM_LENGTH = 80


def configure_board_routes(app_version):
    """Inject runtime configuration into this module."""
    global _APP_VERSION
    _APP_VERSION = app_version


def _generate_public_slug(db, length=PUBLIC_SLUG_LENGTH, max_attempts=32):
    """Generate a unique public slug for board sharing URLs."""
    for _ in range(max_attempts):
        slug = "".join(secrets.choice(PUBLIC_SLUG_ALPHABET) for _ in range(length))
        existing = db.query(Board.id).filter(Board.public_slug == slug).first()
        if not existing:
            return slug

    raise RuntimeError("Failed to generate unique public slug")


def _extract_client_ip():
    # Avoid trusting spoofable forwarding headers unless trusted proxies are configured.
    return request.remote_addr or "unknown"


def _get_public_rate_limit_redis_client():
    global _public_rate_limit_redis_init
    global _public_rate_limit_redis

    if _public_rate_limit_redis_init:
        return _public_rate_limit_redis

    _public_rate_limit_redis_init = True
    try:
        import redis

        redis_url = os.getenv("REDIS_URL")
        if not redis_url:
            _public_rate_limit_redis = None
            return None

        candidate = redis.from_url(redis_url)
        candidate.ping()
        _public_rate_limit_redis = candidate
        logger.info("Public board rate limiter: Redis backend enabled")
    except Exception as error:
        _public_rate_limit_redis = None
        logger.warning("Public board rate limiter falling back to in-memory store: %s", error)

    return _public_rate_limit_redis


def _check_public_endpoint_rate_limit():
    """Apply per-client fixed-window throttle for anonymous public board reads."""
    client_ip = _extract_client_ip()
    now_epoch = int(time.time())
    window_id = now_epoch // PUBLIC_BOARD_RATE_LIMIT_WINDOW_SECONDS
    redis_client = _get_public_rate_limit_redis_client()

    if redis_client:
        key = f"aft:rl:public_board:{client_ip}:{window_id}"
        try:
            current_count = redis_client.incr(key)
            if current_count == 1:
                redis_client.expire(key, PUBLIC_BOARD_RATE_LIMIT_WINDOW_SECONDS + 5)

            if current_count > PUBLIC_BOARD_RATE_LIMIT_PER_MINUTE:
                retry_after = PUBLIC_BOARD_RATE_LIMIT_WINDOW_SECONDS - (now_epoch % PUBLIC_BOARD_RATE_LIMIT_WINDOW_SECONDS)
                return True, max(1, retry_after)

            return False, 0
        except Exception as error:
            logger.warning("Public board Redis rate-limit check failed, using in-memory fallback: %s", error)

    key = (client_ip, window_id)
    with _public_rate_limit_store["lock"]:
        buckets = _public_rate_limit_store["buckets"]
        buckets[key] = buckets.get(key, 0) + 1

        # Drop stale windows so fallback memory stays bounded.
        stale_cutoff = window_id - 2
        stale_keys = [bucket_key for bucket_key in buckets if bucket_key[1] < stale_cutoff]
        for stale_key in stale_keys:
            buckets.pop(stale_key, None)

        current_count = buckets[key]

    if current_count > PUBLIC_BOARD_RATE_LIMIT_PER_MINUTE:
        retry_after = PUBLIC_BOARD_RATE_LIMIT_WINDOW_SECONDS - (now_epoch % PUBLIC_BOARD_RATE_LIMIT_WINDOW_SECONDS)
        return True, max(1, retry_after)

    return False, 0


def _parse_board_working_style(setting_value):
    """Parse working style setting value with a safe default."""
    if not setting_value:
        return "kanban"

    try:
        parsed = json.loads(setting_value)
        if isinstance(parsed, str) and parsed.strip():
            return parsed.strip().lower()
    except (TypeError, json.JSONDecodeError):
        pass

    if isinstance(setting_value, str) and setting_value.strip():
        return setting_value.strip().lower()

    return "kanban"


# ---------------------------------------------------------------------------
# Shared assignee-filter helpers (also re-exported for card routes in app.py)
# ---------------------------------------------------------------------------


def _user_summary(user):
    return {
        "id": user.id,
        "display_name": user.display_name,
        "username": user.username,
        "profile_colour": user.profile_colour,
    }


def _parse_assignee_ids_query_param(raw_value):
    if not raw_value:
        return []

    selected_ids = []
    for part in str(raw_value).split(','):
        candidate = part.strip()
        if not candidate:
            continue
        if not candidate.isdigit():
            continue
        parsed = int(candidate)
        if parsed > 0:
            selected_ids.append(parsed)

    # Preserve order while deduplicating
    return list(dict.fromkeys(selected_ids))


def _get_board_eligible_assignee_ids(db, board_id, board=None):
    if not board_id:
        return set()

    eligible_ids = set()
    if board is None:
        board = db.query(Board).filter(Board.id == board_id).first()
    if board and board.owner and getattr(board.owner, "is_active", True):
        eligible_ids.add(board.owner.id)

    view_perms = {'card.view', 'card.update', 'card.edit', 'card.create'}

    board_roles = (
        db.query(UserRole, Role)
        .join(Role, UserRole.role_id == Role.id)
        .filter(UserRole.board_id == board_id)
        .all()
    )
    for ur, role in board_roles:
        role_perms = set(json.loads(role.permissions))
        if role_perms & view_perms:
            eligible_ids.add(ur.user_id)

    global_roles = (
        db.query(UserRole, Role)
        .join(Role, UserRole.role_id == Role.id)
        .filter(UserRole.board_id.is_(None))
        .all()
    )
    for ur, role in global_roles:
        role_perms = set(json.loads(role.permissions))
        if 'system.admin' in role_perms:
            eligible_ids.add(ur.user_id)

    return eligible_ids


def _get_board_assignee_users(db, board_id, board=None):
    eligible_ids = _get_board_eligible_assignee_ids(db, board_id, board=board)
    if not eligible_ids:
        return []

    return (
        db.query(User)
        .filter(User.id.in_(eligible_ids), User.is_active.is_(True))
        .order_by(User.username)
        .all()
    )


def _get_board_reassignment_users(db):
    return (
        db.query(User)
        .filter(User.is_active.is_(True), User.is_approved.is_(True))
        .order_by(
            func.lower(func.coalesce(User.display_name, User.username, User.email)),
            func.lower(User.username),
        )
        .all()
    )


def _can_reassign_board(board, user_id):
    user_permissions = get_user_permissions(user_id)
    return board.owner_id == user_id or has_permission(user_permissions, "system.admin")


def _build_board_owner_response(board, can_reassign, available_users=None):
    return {
        "board": {
            "id": board.id,
            "name": board.name,
            "archived": bool(board.archived),
            "owner_id": board.owner_id,
        },
        "current_owner": _user_summary(board.owner) if board.owner else None,
        "can_reassign": can_reassign,
        "available_users": available_users or [],
    }


def _build_board_owner_metadata(board, user_id, db, include_candidates=False):
    can_reassign = _can_reassign_board(board, user_id)
    available_users = None
    if include_candidates and can_reassign:
        available_users = [_user_summary(user) for user in _get_board_reassignment_users(db)]

    metadata = {
        "owner_id": board.owner_id,
        "owner": _user_summary(board.owner) if board.owner else None,
        "can_reassign_owner": can_reassign,
    }
    if include_candidates:
        metadata["available_owner_users"] = available_users or []
    return metadata


def _ensure_board_editor_role_assignment(db, user_id, board_id):
    board_editor_role = db.query(Role).filter(Role.name == "board_editor").first()
    if not board_editor_role:
        raise ValueError("Required role 'board_editor' not found")

    existing_assignment = db.query(UserRole).filter(
        UserRole.user_id == user_id,
        UserRole.role_id == board_editor_role.id,
        UserRole.board_id == board_id,
    ).first()

    if existing_assignment:
        return False

    try:
        with db.begin_nested():
            db.add(UserRole(user_id=user_id, role_id=board_editor_role.id, board_id=board_id))
            db.flush()
        return True
    except IntegrityError:
        # Another concurrent request may have assigned this role first.
        return False


def _apply_assignee_card_filters(cards_query, selected_assignee_ids, include_unassigned, include_secondary_assignees):
    selected_ids = [int(uid) for uid in selected_assignee_ids if isinstance(uid, int) and uid > 0]
    has_selected_users = len(selected_ids) > 0

    if not has_selected_users and not include_unassigned:
        return cards_query

    filters = []

    if has_selected_users:
        filters.append(Card.assigned_to_id.in_(selected_ids))
        if include_secondary_assignees:
            secondary_card_ids = (
                cards_query.session.query(CardSecondaryAssignee.card_id)
                .filter(CardSecondaryAssignee.user_id.in_(selected_ids))
            )
            filters.append(Card.id.in_(secondary_card_ids))

    if include_unassigned:
        filters.append(Card.assigned_to_id.is_(None))

    return cards_query.filter(or_(*filters))


def _append_text_search_term(terms, term_text, was_quoted):
    normalized = term_text if was_quoted else term_text.strip()
    if not normalized:
        return

    if not was_quoted and CARD_ID_SEARCH_TOKEN_PATTERN.fullmatch(normalized):
        terms.append({"kind": "id", "value": int(normalized[1:])})
        return

    terms.append({"kind": "text", "value": normalized})


def _parse_text_search_query(raw_query):
    if raw_query is None:
        return []

    query = str(raw_query).strip()
    if len(query) < TEXT_SEARCH_MIN_QUERY_LENGTH:
        return []

    groups = []
    current_group = []
    current_chars = []
    current_was_quoted = False
    in_quotes = False
    index = 0

    while index < len(query):
        char = query[index]

        if in_quotes:
            if char == '"':
                # Two double-quotes inside a quoted phrase represent a literal quote.
                if index + 1 < len(query) and query[index + 1] == '"':
                    current_chars.append('"')
                    index += 2
                    continue
                in_quotes = False
                current_was_quoted = True
                index += 1
                continue

            current_chars.append(char)
            index += 1
            continue

        if char == '"' and not current_chars:
            in_quotes = True
            current_was_quoted = True
            index += 1
            continue

        if char == ',':
            _append_text_search_term(
                current_group,
                ''.join(current_chars),
                current_was_quoted,
            )
            current_chars = []
            current_was_quoted = False

            if current_group:
                groups.append(current_group)
                current_group = []

            index += 1
            continue

        if char.isspace():
            _append_text_search_term(
                current_group,
                ''.join(current_chars),
                current_was_quoted,
            )
            current_chars = []
            current_was_quoted = False
            index += 1
            continue

        current_chars.append(char)
        index += 1

    _append_text_search_term(
        current_group,
        ''.join(current_chars),
        current_was_quoted,
    )
    if current_group:
        groups.append(current_group)

    return groups


def _escape_like_query_value(value):
    return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def _build_text_search_predicate(parsed_groups):
    if not parsed_groups:
        return None

    or_group_predicates = []
    for group in parsed_groups:
        and_term_predicates = []
        for term in group:
            if term.get("kind") == "id":
                and_term_predicates.append(Card.id == term["value"])
                continue

            raw_value = term.get("value", "")
            if not raw_value:
                continue

            like_value = f"%{_escape_like_query_value(raw_value)}%"
            checklist_match = exists().where(
                and_(
                    ChecklistItem.card_id == Card.id,
                    ChecklistItem.name.ilike(like_value, escape='\\'),
                )
            )
            and_term_predicates.append(
                or_(
                    Card.title.ilike(like_value, escape='\\'),
                    Card.description.ilike(like_value, escape='\\'),
                    checklist_match,
                )
            )

        if and_term_predicates:
            or_group_predicates.append(and_(*and_term_predicates))

    if not or_group_predicates:
        return None

    return or_(*or_group_predicates)


def _normalize_text_search_query(raw_query):
    if raw_query is None:
        return None

    return str(raw_query).strip()


def _validate_and_parse_text_search_query(raw_query):
    normalized_query = _normalize_text_search_query(raw_query)
    if normalized_query is None or normalized_query == "":
        return normalized_query, [], None

    if len(normalized_query) > TEXT_SEARCH_MAX_QUERY_LENGTH:
        return None, None, (
            f"Query parameter q must be at most {TEXT_SEARCH_MAX_QUERY_LENGTH} characters"
        )

    parsed_groups = _parse_text_search_query(normalized_query)
    if not parsed_groups:
        return normalized_query, [], None

    if len(parsed_groups) > TEXT_SEARCH_MAX_OR_GROUPS:
        return None, None, (
            f"Query parameter q supports at most {TEXT_SEARCH_MAX_OR_GROUPS} comma-separated groups"
        )

    total_terms = 0
    for group in parsed_groups:
        total_terms += len(group)
        if total_terms > TEXT_SEARCH_MAX_TOTAL_TERMS:
            return None, None, (
                f"Query parameter q supports at most {TEXT_SEARCH_MAX_TOTAL_TERMS} terms"
            )

        for term in group:
            term_value = str(term.get("value", ""))
            if len(term_value) > TEXT_SEARCH_MAX_TERM_LENGTH:
                return None, None, (
                    f"Each term in q must be at most {TEXT_SEARCH_MAX_TERM_LENGTH} characters"
                )

    return normalized_query, parsed_groups, None


def _apply_text_search_filter(cards_query, raw_query, parsed_groups=None):
    parsed_groups = parsed_groups if parsed_groups is not None else _parse_text_search_query(raw_query)
    predicate = _build_text_search_predicate(parsed_groups)
    if predicate is None:
        return cards_query

    return cards_query.filter(predicate)


# ---------------------------------------------------------------------------
# Import helper functions (only used by import_board_from_export)
# ---------------------------------------------------------------------------


def sanitize_import_text(value, field_name, max_length, allow_none=False):
    """Sanitize and validate imported text fields for safe persistence."""
    if value is None:
        if allow_none:
            return None
        raise ValueError(f"{field_name} is required")

    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")

    cleaned = sanitize_string(value)
    if "\x00" in cleaned:
        raise ValueError(f"{field_name} contains invalid null characters")

    is_valid, error = validate_string_length(cleaned, max_length, field_name)
    if not is_valid:
        raise ValueError(error)

    return cleaned


def coerce_bool(value, default=False):
    """Coerce value to boolean with a safe default."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return default


def user_can_import_boards(user_id, db):
    """Check whether a user can import boards.

    Import is allowed for users with global board.create/board.edit permissions,
    or users who hold at least one board-scoped role that grants board.edit.
    """
    user_permissions = get_user_permissions(user_id)
    if "system.admin" in user_permissions or "board.create" in user_permissions or "board.edit" in user_permissions:
        return True

    board_roles = (
        db.query(UserRole, Role)
        .join(Role, UserRole.role_id == Role.id)
        .filter(UserRole.user_id == user_id, UserRole.board_id.isnot(None))
        .all()
    )
    for _, role in board_roles:
        try:
            role_permissions = set(json.loads(role.permissions))
        except (TypeError, json.JSONDecodeError):
            continue
        if "board.edit" in role_permissions:
            return True
    return False


def build_import_name(db, source_name, strategy):
    """Resolve imported board name according to duplicate handling strategy."""
    existing = db.query(Board.id).filter(func.lower(Board.name) == source_name.lower()).first()
    if not existing:
        return source_name, False

    if strategy != "append_suffix":
        return source_name, True

    base_name = f"{source_name} (imported)"
    candidate = base_name
    counter = 2
    while db.query(Board.id).filter(func.lower(Board.name) == candidate.lower()).first():
        candidate = f"{base_name} {counter}"
        counter += 1

    return candidate, True


# ---------------------------------------------------------------------------
# Board routes
# ---------------------------------------------------------------------------


@board_bp.route("/api/boards", methods=["GET"])
@require_authentication
def get_boards():
    """Get all boards accessible by the current user (owned or shared via roles).
    
    Accessible by users with board.view OR board.create permission.
    Users with board.create can see empty boards list and create new boards.
    ---
    tags:
      - Boards
    responses:
      200:
        description: List of all boards accessible by the user
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            boards:
              type: array
              items:
                type: object
                properties:
                  id:
                    type: integer
                    example: 1
                  name:
                    type: string
                    example: "My Board"
      401:
        description: Authentication required
      403:
        description: Permission denied
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
        user_id = g.user.id
        archived_param = request.args.get('archived', 'both').lower()
        if archived_param not in {'true', 'false', 'both'}:
            return create_error_response("archived must be one of true, false, both", 400)
        
        user_perms = get_user_permissions(user_id)

        # Allow board list access when user has global board permissions OR
        # any board-specific assignment (e.g., board_viewer/board_editor).
        can_view_boards = has_permission(user_perms, 'board.view')
        can_create_boards = has_permission(user_perms, 'board.create')
        has_global_board_perm = can_view_boards or can_create_boards
        has_board_assignment = db.query(UserRole.id).filter(
          UserRole.user_id == user_id,
          UserRole.board_id.isnot(None)
        ).first() is not None

        if not has_global_board_perm and not has_board_assignment:
            return jsonify(
                {
                    "success": False,
                    "error": "boards_access_denied",
                    "message": "You do not have access to any existing boards and you do not have permission to create a new board. Ask an administrator to grant board.view access or the board_creator role.",
                    "details": {
                        "can_create_board": False,
                        "has_board_access": False,
                    },
                }
            ), 403
        
        if has_permission(user_perms, 'system.admin'):
            # Admins see all boards in the system
            boards_query = db.query(Board)
        else:
            # Regular users: Get boards owned by user OR where user has a role assignment
            owned_boards = db.query(Board).filter(Board.owner_id == user_id)
            role_boards = db.query(Board).join(UserRole).filter(UserRole.user_id == user_id)
            
            # Combine both queries and remove duplicates
            boards_query = owned_boards.union(role_boards)

        if archived_param == 'true':
            boards_query = boards_query.filter(Board.archived.is_(True))
        elif archived_param == 'false':
            boards_query = boards_query.filter(Board.archived.is_(False))

        boards = boards_query.order_by(Board.name).all()
        
        # Build board list with per-board permissions
        boards_data = []
        for b in boards:
            # Get board-specific permissions for this user
            board_permissions = get_user_permissions(user_id, board_id=b.id)
            can_delete = 'board.delete' in board_permissions
            can_edit = 'board.edit' in board_permissions
            can_export = 'board.view' in board_permissions
            
            boards_data.append({
                "id": b.id, 
                "name": b.name, 
                "description": b.description,
                "is_public": bool(b.is_public),
                "public_slug": b.public_slug,
                "archived": bool(b.archived),
                "created_at": serialize_datetime(b.created_at),
                "updated_at": serialize_datetime(b.updated_at),
                "can_delete": can_delete,
                "can_edit": can_edit,
                "can_export": can_export,
            })
        
        return jsonify(
            {
                "success": True,
                "boards": boards_data,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        db.close()


@board_bp.route("/api/boards", methods=["POST"])
@require_permission('board.create')
def create_board():
    """Create a new board with input validation.

    This endpoint creates a new board after validating:
    - Name is provided and is a string
    - Name does not exceed maximum length
    - Description (if provided) does not exceed maximum length

    ---
    tags:
      - Boards
    parameters:
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
              example: "My New Board"
              description: The name of the board to create
    responses:
      201:
        description: Board created successfully
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
                  example: "My New Board"
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

        # Validate name
        name = data.get("name")
        if not isinstance(name, str):
            return create_error_response("Name must be a string", 400)

        # Sanitize and validate length
        name = sanitize_string(name)
        if not name:  # Empty after sanitization
            return create_error_response("Name cannot be empty", 400)

        is_valid, error = validate_string_length(name, MAX_TITLE_LENGTH, "Name")
        if not is_valid:
            return create_error_response(error, 400)

        # Validate description if provided
        description = data.get("description")
        if description is not None:
            if not isinstance(description, str):
                return create_error_response("Description must be a string", 400)

            description = sanitize_string(description)
            is_valid, error = validate_string_length(
                description, MAX_DESCRIPTION_LENGTH, "Description"
            )
            if not is_valid:
                return create_error_response(error, 400)

        # Create board
        now = utc_now()
        user_id = get_current_user_id()
        board = Board(name=name, description=description, owner_id=user_id, updated_at=now)
        db.add(board)

        # Create a board-level working style using the user's current default.
        db.flush()
        working_style = get_user_default_working_style(db, user_id)
        db.add(
          BoardSetting(
            board_id=board.id,
            key='working_style',
            value=json.dumps(working_style),
          )
        )

        db.commit()
        db.refresh(board)

        result = {
            "id": board.id, 
            "name": board.name, 
            "description": board.description,
            "is_public": bool(board.is_public),
            "public_slug": board.public_slug,
            "archived": bool(board.archived),
            "created_at": serialize_datetime(board.created_at),
            "updated_at": serialize_datetime(board.updated_at)
        }
        return create_success_response({"board": result}, status_code=201)

    except Exception as e:
        db.rollback()
        logger.error(f"Error creating board: {str(e)}")
        return create_error_response("Failed to create board", 500)
    finally:
        db.close()


@board_bp.route("/api/boards/<int:board_id>/export", methods=["GET"])
@require_board_access()
@require_permission('board.view')
def export_board(board_id):
    """Export a board and all its data as a JSON file.
    ---
    tags:
      - Boards
    security:
      - session: []
    parameters:
      - name: board_id
        in: path
        required: true
        type: integer
    responses:
      200:
        description: JSON file download containing the full board export
      403:
        description: Insufficient permissions
      404:
        description: Board not found
      500:
        description: Export failed
    """
    db = SessionLocal()
    try:
        board = db.query(Board).filter(Board.id == board_id).first()
        if not board:
            return create_error_response("Board not found", 404)

        columns = (
            db.query(BoardColumn)
            .filter(BoardColumn.board_id == board_id)
            .order_by(BoardColumn.order)
            .all()
        )
        column_ids = [column.id for column in columns]

        cards = []
        if column_ids:
            cards = (
                db.query(Card)
                .options(
                    selectinload(Card.checklist_items),
                    selectinload(Card.comments),
                    selectinload(Card.secondary_assignees),
                )
                .filter(Card.column_id.in_(column_ids))
                .order_by(Card.column_id, Card.order, Card.id)
                .all()
            )

        card_ids = [card.id for card in cards]
        board_settings = (
            db.query(BoardSetting)
            .filter(BoardSetting.board_id == board_id)
            .order_by(BoardSetting.id)
            .all()
        )

        scheduled_cards = []
        if card_ids:
            scheduled_cards = (
                db.query(ScheduledCard)
                .filter(ScheduledCard.card_id.in_(card_ids))
                .order_by(ScheduledCard.id)
                .all()
            )

        export_payload = {
            "export": {
                "format": BOARD_EXPORT_FORMAT,
                "format_version": "1.0",
                "app_version": _APP_VERSION,
                "exported_at": serialize_datetime(utc_now()),
                "exported_by_user_id": g.user.id,
                "source_board_id": board.id,
                "features_exported": [
                    "board",
                    "board_settings",
                    "columns",
                    "cards",
                    "card_secondary_assignees",
                    "checklists",
                    "comments",
                    "scheduled_cards",
                ],
            },
            "board": {
                "id": board.id,
                "name": board.name,
                "description": board.description,
                "archived": bool(board.archived),
                "owner_id": board.owner_id,
                "created_at": serialize_datetime(board.created_at),
                "updated_at": serialize_datetime(board.updated_at),
            },
            "board_settings": [
                {
                    "id": setting.id,
                    "board_id": setting.board_id,
                    "key": setting.key,
                    "value": setting.value,
                }
                for setting in board_settings
            ],
            "columns": [
                {
                    "id": column.id,
                    "board_id": column.board_id,
                    "name": column.name,
                    "order": column.order,
                    "created_at": serialize_datetime(column.created_at),
                    "updated_at": serialize_datetime(column.updated_at),
                }
                for column in columns
            ],
            "cards": [
                {
                    "id": card.id,
                    "column_id": card.column_id,
                    "title": card.title,
                    "description": card.description,
                    "order": card.order,
                    "archived": card.archived,
                    "scheduled": card.scheduled,
                    "schedule": card.schedule,
                    "done": card.done,
                    "done_datetime": serialize_datetime(card.done_datetime),
                    "created_by_id": card.created_by_id,
                    "assigned_to_id": card.assigned_to_id,
                    "created_at": serialize_datetime(card.created_at),
                    "updated_at": serialize_datetime(card.updated_at),
                }
                for card in cards
            ],
            "card_secondary_assignees": [
                {
                    "id": secondary.id,
                    "card_id": secondary.card_id,
                    "user_id": secondary.user_id,
                    "created_at": serialize_datetime(secondary.created_at),
                }
                for card in cards
                for secondary in card.secondary_assignees
            ],
            "checklists": [
                {
                    "id": item.id,
                    "card_id": item.card_id,
                    "name": item.name,
                    "checked": item.checked,
                    "order": item.order,
                    "created_at": serialize_datetime(item.created_at),
                    "updated_at": serialize_datetime(item.updated_at),
                }
                for card in cards
                for item in card.checklist_items
            ],
            "comments": [
                {
                    "id": comment.id,
                    "card_id": comment.card_id,
                    "comment": comment.comment,
                    "order": comment.order,
                    "created_at": serialize_datetime(comment.created_at),
                }
                for card in cards
                for comment in card.comments
            ],
            "scheduled_cards": [
                {
                    "id": schedule.id,
                    "card_id": schedule.card_id,
                    "run_every": schedule.run_every,
                    "unit": schedule.unit,
                    "start_datetime": serialize_datetime(schedule.start_datetime),
                    "end_datetime": serialize_datetime(schedule.end_datetime),
                    "schedule_enabled": schedule.schedule_enabled,
                    "allow_duplicates": schedule.allow_duplicates,
                }
                for schedule in scheduled_cards
            ],
        }

        board_slug = re.sub(r"[^A-Za-z0-9_-]+", "_", board.name or "board").strip("_") or "board"
        timestamp = utc_now().strftime("%Y%m%d_%H%M%S")
        filename = f"aft_board_{board_slug}_{timestamp}.json"
        file_content = json.dumps(export_payload, ensure_ascii=True, indent=2)

        return send_file(
            io.BytesIO(file_content.encode("utf-8")),
            mimetype="application/json",
            as_attachment=True,
            download_name=filename,
        )
    except Exception as e:
        logger.error(f"Error exporting board {board_id}: {str(e)}")
        return create_error_response("Failed to export board", 500)
    finally:
        db.close()


@board_bp.route("/api/boards/import", methods=["POST"])
@require_authentication
def import_board_from_export():
    """Import a board from an AFT JSON export file.
    ---
    tags:
      - Boards
    security:
      - session: []
    consumes:
      - multipart/form-data
    parameters:
      - name: file
        in: formData
        required: true
        type: file
        description: AFT-formatted JSON export file
    responses:
        201:
            description: Board imported successfully
        400:
            description: Invalid file, format or validation error
        403:
            description: Insufficient permissions
        500:
            description: Import failed
    """
    db = SessionLocal()
    try:
        user_id = g.user.id
        if not user_can_import_boards(user_id, db):
            return create_error_response(
                "Permission denied: importing boards requires board editor access",
                403,
            )

        if "file" not in request.files:
            return create_error_response("No file uploaded", 400)

        file_obj = request.files["file"]
        if file_obj.filename == "":
            return create_error_response("No file selected", 400)

        payload_bytes = file_obj.read()
        if not payload_bytes:
            return create_error_response("Import file is empty", 400)

        try:
            payload_text = payload_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return create_error_response("Import file must be valid UTF-8 JSON", 400)

        is_valid_size, size_error = validate_json_import_payload_size(
            payload_text,
            max_size_mb=MAX_BOARD_IMPORT_FILE_SIZE_MB,
        )
        if not is_valid_size:
            return create_error_response(size_error, 400)

        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            return create_error_response("Import file is not valid JSON", 400)

        handler = ImportHandlerFactory.get_handler(payload)
        if not handler:
            return create_error_response(
                "Unsupported import format. AFT-formatted JSON exports and Trello JSON exports are supported.",
                400,
            )

        validation_result = handler.validate(payload)
        if not validation_result.is_valid:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Import validation failed",
                        "errors": validation_result.errors,
                    }
                ),
                400,
            )

        include_archived_cards = (
            request.form.get("include_archived_cards", "false").lower() == "true"
        )
        include_archived_lists = (
            request.form.get("include_archived_lists", "false").lower() == "true"
        )

        # Member mapping: JSON object {trelloMemberId: aftUserId}
        try:
            raw_member_map = json.loads(request.form.get("member_map", "{}") or "{}")
            if not isinstance(raw_member_map, dict):
                raw_member_map = {}
        except (json.JSONDecodeError, ValueError):
            raw_member_map = {}
        candidate_user_ids = [v for v in raw_member_map.values() if isinstance(v, int) and v > 0]
        if candidate_user_ids:
            valid_ids = {
                row[0] for row in db.query(User.id)
                .filter(
                    User.id.in_(candidate_user_ids),
                    User.is_active.is_(True),
                    User.is_approved.is_(True),
                )
                .all()
            }
        else:
            valid_ids = set()
        member_map = {
            k: v for k, v in raw_member_map.items()
            if isinstance(k, str) and isinstance(v, int) and v in valid_ids
        }

        parse_options = {
            "include_archived_cards": include_archived_cards,
            "include_archived_lists": include_archived_lists,
            "member_map": member_map,
        }
        import_data = handler.parse(payload, parse_options)
        board_data = import_data["board"]

        duplicate_strategy = (request.form.get("duplicate_strategy") or "cancel").strip().lower()
        if duplicate_strategy not in {"cancel", "append_suffix"}:
            return create_error_response(
                "duplicate_strategy must be one of: cancel, append_suffix",
                400,
            )

        source_board_name = sanitize_import_text(
            board_data.get("name"),
            "Board name",
            MAX_TITLE_LENGTH,
            allow_none=False,
        )
        resolved_board_name, had_name_conflict = build_import_name(
            db,
            source_board_name,
            duplicate_strategy,
        )

        if had_name_conflict and duplicate_strategy == "cancel":
            suggested_name, _ = build_import_name(db, source_board_name, "append_suffix")
            return (
                jsonify(
                    {
                        "success": False,
                        "message": (
                            "A board with this name already exists. Overwriting is not supported. "
                            "Delete the existing board first, or import with an automatic suffix."
                        ),
                        "requires_confirmation": True,
                        "conflict_type": "board_name_exists",
                        "board_name": source_board_name,
                        "suggested_board_name": suggested_name,
                    }
                ),
                409,
            )

        board_description = sanitize_import_text(
            board_data.get("description"),
            "Board description",
            MAX_DESCRIPTION_LENGTH,
            allow_none=True,
        )

        # User identity differs between instances. For safety, assignee mapping is
        # intentionally disabled until explicit user-mapping support is added.
        ignored_primary_assignees_count = sum(
            1
            for card in import_data["cards"]
            if isinstance(card.get("assigned_to_id"), int) and card.get("assigned_to_id") > 0
        )
        ignored_secondary_assignees_count = sum(
            1
            for assignee in import_data["card_secondary_assignees"]
            if isinstance(assignee.get("user_id"), int) and assignee.get("user_id") > 0
        )

        new_board = Board(
            name=resolved_board_name,
            description=board_description,
            archived=coerce_bool(board_data.get("archived"), default=False),
            owner_id=user_id,
            updated_at=utc_now(),
        )
        db.add(new_board)
        db.flush()

        old_to_new_column_id = {}
        old_to_new_card_id = {}
        old_to_new_schedule_id = {}
        pending_schedule_references = {}

        for setting in import_data["board_settings"]:
            setting_key = sanitize_import_text(
                setting.get("key"),
                "Board setting key",
                255,
                allow_none=False,
            )
            setting_value = setting.get("value")
            if setting_value is not None and not isinstance(setting_value, str):
                setting_value = json.dumps(setting_value)

            db.add(
                BoardSetting(
                    board_id=new_board.id,
                    key=setting_key,
                    value=setting_value,
                )
            )

        sorted_columns = sorted(
            import_data["columns"],
            key=lambda col: (int(col.get("order") or 0), int(col.get("id") or 0)),
        )
        for column in sorted_columns:
            source_column_id = column.get("id")
            if not isinstance(source_column_id, int):
                continue

            column_name = sanitize_import_text(
                column.get("name"),
                "Column name",
                MAX_TITLE_LENGTH,
                allow_none=False,
            )

            raw_order = column.get("order", 0)
            if isinstance(raw_order, bool):
                raw_order = 0
            if not isinstance(raw_order, int):
                raw_order = 0
            column_order = raw_order if raw_order >= 0 else 0

            new_column = BoardColumn(
                board_id=new_board.id,
                name=column_name,
                order=column_order,
                updated_at=utc_now(),
            )
            db.add(new_column)
            db.flush()
            old_to_new_column_id[source_column_id] = new_column.id

        # Pre-validate all user IDs referenced in the import data against the current DB.
        # This prevents FK violations for AFT-to-AFT imports (where original user IDs
        # won't exist in the target system) while allowing Trello imports with explicit
        # member_map (which were already validated against active users above).
        candidate_user_ids = set()
        for card in import_data.get("cards", []):
            uid = card.get("assigned_to_id")
            if isinstance(uid, int) and uid > 0:
                candidate_user_ids.add(uid)
        for assignee in import_data.get("card_secondary_assignees", []):
            uid = assignee.get("user_id")
            if isinstance(uid, int) and uid > 0:
                candidate_user_ids.add(uid)
        if candidate_user_ids:
            valid_import_user_ids = {
                row[0] for row in db.query(User.id)
                .filter(User.id.in_(list(candidate_user_ids)), User.is_active.is_(True))
                .all()
            }
        else:
            valid_import_user_ids = set()

        sorted_cards = sorted(
            import_data["cards"],
            key=lambda card: (
                int(card.get("column_id") or 0),
                int(card.get("order") or 0),
                int(card.get("id") or 0),
            ),
        )
        for card in sorted_cards:
            source_card_id = card.get("id")
            source_column_id = card.get("column_id")
            if not isinstance(source_card_id, int) or source_column_id not in old_to_new_column_id:
                continue

            title = sanitize_import_text(
                card.get("title"),
                "Card title",
                MAX_TITLE_LENGTH,
                allow_none=False,
            )
            description = sanitize_import_text(
                card.get("description"),
                "Card description",
                MAX_DESCRIPTION_LENGTH,
                allow_none=True,
            )

            raw_order = card.get("order", 0)
            if isinstance(raw_order, bool):
                raw_order = 0
            if not isinstance(raw_order, int):
                raw_order = 0
            card_order = raw_order if raw_order >= 0 else 0

            created_by_id = user_id
            source_assigned_to_id = card.get("assigned_to_id")
            assigned_to_id = (
                source_assigned_to_id
                if isinstance(source_assigned_to_id, int) and source_assigned_to_id in valid_import_user_ids
                else None
            )

            new_card = Card(
                column_id=old_to_new_column_id[source_column_id],
                title=title,
                description=description,
                order=card_order,
                archived=coerce_bool(card.get("archived"), default=False),
                scheduled=coerce_bool(card.get("scheduled"), default=False),
                done=coerce_bool(card.get("done"), default=False),
                schedule=None,
                created_by_id=created_by_id,
                assigned_to_id=assigned_to_id,
                start_date=parse_iso_datetime(card.get("start_date")),
                end_date=parse_iso_datetime(card.get("end_date")),
                updated_at=utc_now(),
            )
            db.add(new_card)
            db.flush()

            old_to_new_card_id[source_card_id] = new_card.id

            source_schedule_id = card.get("schedule")
            if isinstance(source_schedule_id, int) and source_schedule_id > 0:
                pending_schedule_references[new_card.id] = source_schedule_id

        for assignee in import_data.get("card_secondary_assignees", []):
            source_card_id = assignee.get("card_id")
            assignee_user_id = assignee.get("user_id")
            if source_card_id not in old_to_new_card_id:
                continue
            if not isinstance(assignee_user_id, int) or assignee_user_id not in valid_import_user_ids:
                continue
            db.add(CardSecondaryAssignee(
                card_id=old_to_new_card_id[source_card_id],
                user_id=assignee_user_id,
            ))

        sorted_checklists = sorted(
            import_data["checklists"],
            key=lambda item: (
                int(item.get("card_id") or 0),
                int(item.get("order") or 0),
                int(item.get("id") or 0),
            ),
        )
        for item in sorted_checklists:
            source_card_id = item.get("card_id")
            if source_card_id not in old_to_new_card_id:
                continue

            item_name = sanitize_import_text(
                item.get("name"),
                "Checklist item name",
                500,
                allow_none=False,
            )

            raw_order = item.get("order", 0)
            if isinstance(raw_order, bool):
                raw_order = 0
            if not isinstance(raw_order, int):
                raw_order = 0

            db.add(
                ChecklistItem(
                    card_id=old_to_new_card_id[source_card_id],
                    name=item_name,
                    checked=coerce_bool(item.get("checked"), default=False),
                    order=raw_order if raw_order >= 0 else 0,
                    updated_at=utc_now(),
                )
            )

        sorted_comments = sorted(
            import_data["comments"],
            key=lambda comment: (
                int(comment.get("card_id") or 0),
                int(comment.get("order") or 0),
                int(comment.get("id") or 0),
            ),
        )
        for comment in sorted_comments:
            source_card_id = comment.get("card_id")
            if source_card_id not in old_to_new_card_id:
                continue

            comment_text = sanitize_import_text(
                comment.get("comment"),
                "Comment",
                MAX_COMMENT_LENGTH,
                allow_none=False,
            )
            raw_order = comment.get("order", 0)
            if isinstance(raw_order, bool):
                raw_order = 0
            if not isinstance(raw_order, int):
                raw_order = 0

            db.add(
                Comment(
                    card_id=old_to_new_card_id[source_card_id],
                    comment=comment_text,
                    order=raw_order if raw_order >= 0 else 0,
                )
            )

        sorted_schedules = sorted(
            import_data["scheduled_cards"],
            key=lambda schedule: int(schedule.get("id") or 0),
        )
        for schedule in sorted_schedules:
            source_schedule_id = schedule.get("id")
            source_template_card_id = schedule.get("card_id")
            if source_template_card_id not in old_to_new_card_id:
                continue

            run_every = schedule.get("run_every")
            if isinstance(run_every, bool) or not isinstance(run_every, int) or run_every < 1:
                run_every = 1

            unit = schedule.get("unit")
            allowed_units = {"minute", "hour", "day", "week", "month", "year"}
            if not isinstance(unit, str) or unit not in allowed_units:
                unit = "day"

            start_datetime = parse_iso_datetime(schedule.get("start_datetime")) or utc_now()
            end_datetime = parse_iso_datetime(schedule.get("end_datetime"))

            new_schedule = ScheduledCard(
                card_id=old_to_new_card_id[source_template_card_id],
                run_every=run_every,
                unit=unit,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                schedule_enabled=coerce_bool(schedule.get("schedule_enabled"), default=True),
                allow_duplicates=coerce_bool(schedule.get("allow_duplicates"), default=False),
            )
            db.add(new_schedule)
            db.flush()

            if isinstance(source_schedule_id, int):
                old_to_new_schedule_id[source_schedule_id] = new_schedule.id

        for imported_card_id, imported_schedule_id in pending_schedule_references.items():
            mapped_schedule_id = old_to_new_schedule_id.get(imported_schedule_id)
            if not mapped_schedule_id:
                continue

            db.query(Card).filter(Card.id == imported_card_id).update({"schedule": mapped_schedule_id})

        # Secondary assignees are currently not imported by user ID.

        db.commit()

        return jsonify(
            {
                "success": True,
                "message": "Board imported successfully",
                "board": {
                    "id": new_board.id,
                    "name": new_board.name,
                    "description": new_board.description,
                    "archived": bool(new_board.archived),
                },
                "import_meta": {
                    "source_board_name": source_board_name,
                    "name_conflict_resolved": had_name_conflict,
                    "import_format": import_data.get("import_format", BOARD_EXPORT_FORMAT),
                    "import_format_version": import_data.get("import_format_version", "1.0"),
                    "assignee_mapping": "not_mapped",
                    "ignored_primary_assignees_count": ignored_primary_assignees_count,
                    "ignored_secondary_assignees_count": ignored_secondary_assignees_count,
                },
            }
        ), 201
    except ValueError as validation_error:
        db.rollback()
        return create_error_response(str(validation_error), 400)
    except Exception as e:
        db.rollback()
        logger.error(f"Error importing board: {str(e)}")
        return create_error_response("Failed to import board", 500)
    finally:
        db.close()


@board_bp.route("/api/boards/<int:board_id>/cards/scheduled", methods=["GET"])
@require_board_access()
def get_board_scheduled_cards(board_id):
    """Get all scheduled cards for a board with nested structure (user must have access).
    Returns only scheduled template cards (scheduled=True) organized by column.
    ---
    tags:
      - Cards
    parameters:
      - name: board_id
        in: path
        type: integer
        required: true
        description: The ID of the board
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
        description: Board with columns and scheduled cards
      401:
        description: Authentication required
      403:
        description: Access denied to this board
      404:
        description: Board not found
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        # Access already validated by @require_board_access decorator
        board = db.query(Board).filter(Board.id == board_id).first()
        if not board:
            return jsonify({"success": False, "message": "Board not found"}), 404
        
        # Get columns for the board
        columns = (
            db.query(BoardColumn)
            .filter(BoardColumn.board_id == board_id)
            .order_by(BoardColumn.order)
            .all()
        )
        
        selected_assignee_ids = _parse_assignee_ids_query_param(request.args.get('assignee_ids'))
        include_unassigned = request.args.get('include_unassigned', 'false').lower() == 'true'
        include_secondary_assignees = request.args.get('include_secondary_assignees', 'false').lower() == 'true'
        include_owner_candidates = request.args.get('include_owner_candidates', 'false').lower() == 'true'
        text_query, parsed_text_query, text_query_error = _validate_and_parse_text_search_query(
            request.args.get('q')
        )
        if text_query_error:
            return create_error_response(text_query_error, 400)

        # Build nested structure with scheduled cards
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
            # Get only scheduled template cards for this column
            cards = (
                db.query(Card)
                .options(selectinload(Card.assigned_to))
                .filter(Card.column_id == column.id)
                .filter(Card.scheduled.is_(True))
            )

            cards = _apply_assignee_card_filters(
                cards,
                selected_assignee_ids,
                include_unassigned,
                include_secondary_assignees,
            )

            cards = _apply_text_search_filter(cards, text_query, parsed_groups=parsed_text_query).order_by(Card.order).all()

            # Serialize cards with checklist items and comments
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

        return jsonify({"success": True, "board": result})
        
    except Exception as e:
        logger.error(f"Error getting scheduled cards for board {board_id}: {str(e)}")
        return jsonify({"success": False, "message": "Failed to get scheduled cards"}), 500
    finally:
        db.close()


@board_bp.route("/api/boards/<int:board_id>", methods=["DELETE"])
@require_board_access()
@require_permission('board.delete')
def delete_board(board_id):
    """Delete a board by ID.
    ---
    tags:
      - Boards
    parameters:
      - name: board_id
        in: path
        type: integer
        required: true
        description: The ID of the board to delete
    responses:
      200:
        description: Board deleted successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            message:
              type: string
              example: "Board deleted successfully"
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
        # Access already validated by @require_board_access decorator
        board = db.query(Board).filter(Board.id == board_id).first()

        if not board:
            return jsonify({"success": False, "message": "Board not found"}), 404

        # Check if this board is set as default_board for the current user
        user_id = g.user.id
        default_board_setting = (
            get_user_scoped_query(db, Setting, user_id).filter(Setting.key == "default_board").first()
        )
        if default_board_setting:
            try:
                default_board_id = json.loads(default_board_setting.value)
                if default_board_id == board_id:
                    # Reset to null since we're deleting the default board
                    default_board_setting.value = "null"
                    logger.info(
                        f"Reset default_board setting for user {user_id} because board {board_id} was deleted"
                    )
            except (json.JSONDecodeError, ValueError):
                # Ignore if setting value is malformed - we're deleting the board anyway
                pass

        db.delete(board)
        db.commit()

        return jsonify({"success": True, "message": "Board deleted successfully"}), 200
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        db.close()


@board_bp.route("/api/boards/<int:board_id>", methods=["PATCH"])
@require_board_access()
@require_permission('board.edit')
def update_board(board_id):
    """Update a board's name, description, and/or visibility with validation.

    This endpoint updates a board after validating:
    - At least one field (name, description, or is_public) is provided
    - Name (if provided) is a string and within length limits
    - Description (if provided) is a string and within length limits

    ---
    tags:
      - Boards
    parameters:
      - name: board_id
        in: path
        type: integer
        required: true
        description: The ID of the board to update
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            name:
              type: string
              example: "Updated Board Name"
              description: The new name for the board
            description:
              type: string
              example: "Updated board description"
              description: The new description for the board
            is_public:
                type: boolean
                example: true
                description: Toggle public visibility for anonymous read-only access
    responses:
      200:
        description: Board updated successfully
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
                  example: "Updated Board Name"
                description:
                  type: string
                  example: "Updated board description"
                is_public:
                    type: boolean
                    example: true
                public_slug:
                    type: string
                    nullable: true
                    example: "a1b2c3d4e5f6"
            message:
              type: string
              example: "Board updated successfully"
      400:
        description: Bad request - no valid fields provided
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            message:
              type: string
              example: "At least one field (name, description, or is_public) is required"
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
            
        if not data or (
            "name" not in data
            and "description" not in data
            and "is_public" not in data
        ):
            return create_error_response(
                "At least one field (name, description, or is_public) is required", 400
            )

        # Access already validated by @require_board_access decorator
        board = db.query(Board).filter(Board.id == board_id).first()
        if not board:
            return create_error_response("Board not found", 404)

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

            board.name = name

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

            board.description = description

        if "is_public" in data:
            is_public = data["is_public"]
            if not isinstance(is_public, bool):
                return create_error_response("is_public must be a boolean", 400)

            board.is_public = is_public
            # Keep public slug stable across visibility toggles.
            # Slug rotation is an explicit action via the rotate endpoint.
            if is_public and not board.public_slug:
                board.public_slug = _generate_public_slug(db)

        # Set updated_at timestamp
        board.updated_at = utc_now()

        db.commit()
        db.refresh(board)

        result = {
            "id": board.id, 
            "name": board.name, 
            "description": board.description,
            "is_public": bool(board.is_public),
            "public_slug": board.public_slug,
            "archived": bool(board.archived),
            "created_at": serialize_datetime(board.created_at),
            "updated_at": serialize_datetime(board.updated_at)
        }
        return create_success_response(
            {"board": result, "message": "Board updated successfully"}
        )

    except Exception as e:
        db.rollback()
        logger.error(f"Error updating board {board_id}: {str(e)}")
        return create_error_response("Failed to update board", 500)
    finally:
        db.close()


@board_bp.route("/api/boards/<int:board_id>/archive", methods=["PATCH"])
@require_board_access()
@require_permission('board.edit')
def archive_board(board_id):
    """Archive a board by ID.
    ---
    tags:
        - Boards
    parameters:
        - name: board_id
          in: path
          type: integer
          required: true
          description: The ID of the board to archive
    responses:
        200:
          description: Board archived successfully
        404:
          description: Board not found
        500:
          description: Server error
    """
    db = SessionLocal()
    try:
        board = db.query(Board).filter(Board.id == board_id).first()
        if not board:
            return create_error_response("Board not found", 404)

        board.archived = True
        board.updated_at = utc_now()

        db.commit()
        db.refresh(board)

        result = {
            "id": board.id,
            "name": board.name,
            "description": board.description,
            "is_public": bool(board.is_public),
            "public_slug": board.public_slug,
            "archived": bool(board.archived),
            "created_at": serialize_datetime(board.created_at),
            "updated_at": serialize_datetime(board.updated_at),
        }
        return create_success_response({"board": result, "message": "Board archived successfully"})
    except Exception as e:
        db.rollback()
        logger.error(f"Error archiving board {board_id}: {str(e)}")
        return create_error_response("Failed to archive board", 500)
    finally:
        db.close()


@board_bp.route("/api/boards/<int:board_id>/unarchive", methods=["PATCH"])
@require_board_access()
@require_permission('board.edit')
def unarchive_board(board_id):
    """Unarchive a board by ID.
    ---
    tags:
        - Boards
    parameters:
        - name: board_id
          in: path
          type: integer
          required: true
          description: The ID of the board to unarchive
    responses:
        200:
          description: Board unarchived successfully
        404:
          description: Board not found
        500:
          description: Server error
    """
    db = SessionLocal()
    try:
        board = db.query(Board).filter(Board.id == board_id).first()
        if not board:
            return create_error_response("Board not found", 404)

        board.archived = False
        board.updated_at = utc_now()

        db.commit()
        db.refresh(board)

        result = {
            "id": board.id,
            "name": board.name,
            "description": board.description,
            "is_public": bool(board.is_public),
            "public_slug": board.public_slug,
            "archived": bool(board.archived),
            "created_at": serialize_datetime(board.created_at),
            "updated_at": serialize_datetime(board.updated_at),
        }
        return create_success_response({"board": result, "message": "Board unarchived successfully"})
    except Exception as e:
        db.rollback()
        logger.error(f"Error unarchiving board {board_id}: {str(e)}")
        return create_error_response("Failed to unarchive board", 500)
    finally:
        db.close()


@board_bp.route("/api/boards/<int:board_id>/public-link/rotate", methods=["POST"])
@require_board_access()
@require_permission('board.edit')
def rotate_public_board_link(board_id):
    """Rotate a board's public link slug.
    ---
    tags:
      - Boards
    parameters:
      - name: board_id
        in: path
        type: integer
        required: true
        description: The ID of the board to rotate public link for
    responses:
      200:
        description: Public link rotated successfully
      400:
        description: Board is not public
      404:
        description: Board not found
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        board = db.query(Board).filter(Board.id == board_id).first()
        if not board:
            return create_error_response("Board not found", 404)

        if not board.is_public:
            return create_error_response("Board must be public before rotating its link", 400)

        previous_slug = board.public_slug
        new_slug = _generate_public_slug(db)
        # Extremely unlikely collision with existing board and avoid no-op reuse.
        while previous_slug and new_slug == previous_slug:
            new_slug = _generate_public_slug(db)

        board.public_slug = new_slug
        board.updated_at = utc_now()

        db.commit()
        db.refresh(board)

        result = {
            "id": board.id,
            "name": board.name,
            "description": board.description,
            "is_public": bool(board.is_public),
            "public_slug": board.public_slug,
            "archived": bool(board.archived),
            "created_at": serialize_datetime(board.created_at),
            "updated_at": serialize_datetime(board.updated_at),
        }
        return create_success_response(
            {
                "board": result,
                "previous_public_slug": previous_slug,
                "message": "Public link rotated successfully",
            }
        )

    except Exception as e:
        db.rollback()
        logger.error(f"Error rotating public link for board {board_id}: {str(e)}")
        return create_error_response("Failed to rotate public link", 500)
    finally:
        db.close()


@board_bp.route("/api/public/boards/<string:slug>", methods=["GET"])
def get_public_board(slug):
    """Get a public read-only board payload by public slug.
    ---
    tags:
      - Boards
    parameters:
      - name: slug
        in: path
        type: string
        required: true
        description: Public board slug
      - name: archived
        in: query
        type: string
        required: false
        enum: ['true', 'false', 'both']
        default: 'false'
        description: Filter by archived status
      - name: done
        in: query
        type: string
        required: false
        enum: ['true', 'false', 'both']
        default: 'both'
        description: Filter by done status
    responses:
      200:
        description: Public board payload
      400:
        description: Invalid query parameter
      404:
        description: Public board not found
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        is_limited, retry_after = _check_public_endpoint_rate_limit()
        if is_limited:
            response, status_code = create_error_response("Too many requests", 429)
            response.headers["Retry-After"] = str(retry_after)
            response.headers["Cache-Control"] = "private, no-store, max-age=0"
            return response, status_code

        safe_slug = (slug or "").strip().lower()
        if not safe_slug or not PUBLIC_SLUG_PATTERN.fullmatch(safe_slug):
            return create_error_response("Board not found", 404)

        board = (
            db.query(Board)
            .filter(
                Board.public_slug == safe_slug,
                Board.is_public.is_(True),
                Board.archived.is_(False),
            )
            .first()
        )
        if not board:
            return create_error_response("Board not found", 404)

        archived_param = request.args.get("archived", "false").lower()
        if archived_param not in {"true", "false", "both"}:
            return create_error_response("archived must be one of true, false, both", 400)

        done_param = request.args.get("done", "both").lower()
        if done_param not in {"true", "false", "both"}:
            return create_error_response("done must be one of true, false, both", 400)

        columns = (
            db.query(BoardColumn)
            .filter(BoardColumn.board_id == board.id)
            .order_by(BoardColumn.order)
            .all()
        )
        working_style_setting = (
            db.query(BoardSetting)
            .filter(BoardSetting.board_id == board.id, BoardSetting.key == "working_style")
            .first()
        )

        result = {
            "id": board.id,
            "name": board.name,
            "description": board.description,
            "is_public": bool(board.is_public),
            "public_slug": board.public_slug,
            "archived": bool(board.archived),
            "working_style": _parse_board_working_style(
                working_style_setting.value if working_style_setting else None
            ),
            "default_theme": None,
            "created_at": serialize_datetime(board.created_at),
            "updated_at": serialize_datetime(board.updated_at),
            "columns": [],
        }

        default_theme = get_instance_default_theme(db)
        if default_theme:
            result["default_theme"] = default_theme.to_dict()

        for column in columns:
            cards_query = db.query(Card).filter(
                Card.column_id == column.id,
                Card.scheduled.is_(False),
            )

            if archived_param == "true":
                cards_query = cards_query.filter(Card.archived.is_(True))
            elif archived_param == "false":
                cards_query = cards_query.filter(Card.archived.is_(False))

            if done_param == "true":
                cards_query = cards_query.filter(Card.done.is_(True))
            elif done_param == "false":
                cards_query = cards_query.filter(Card.done.is_(False))

            cards_query = cards_query.options(
                selectinload(Card.checklist_items),
                selectinload(Card.comments),
            )
            cards = cards_query.order_by(Card.order).all()

            cards_data = [
                {
                    "id": card.id,
                    "title": card.title,
                    "description": card.description,
                    "order": card.order,
                    "archived": card.archived,
                    "done": card.done,
                    "created_at": serialize_datetime(card.created_at),
                    "updated_at": serialize_datetime(card.updated_at),
                    "checklist_items": [
                        {
                            "id": item.id,
                            "card_id": item.card_id,
                            "name": item.name,
                            "checked": item.checked,
                            "order": item.order,
                            "created_at": serialize_datetime(item.created_at),
                            "updated_at": serialize_datetime(item.updated_at),
                        }
                        for item in card.checklist_items
                    ],
                    "comments": [
                        {
                            "id": comment.id,
                            "card_id": comment.card_id,
                            "comment": comment.comment,
                            "order": comment.order,
                            "created_at": serialize_datetime(comment.created_at),
                        }
                        for comment in card.comments
                    ],
                }
                for card in cards
            ]

            result["columns"].append(
                {
                    "id": column.id,
                    "name": column.name,
                    "order": column.order,
                    "created_at": serialize_datetime(column.created_at),
                    "updated_at": serialize_datetime(column.updated_at),
                    "cards": cards_data,
                }
            )

        response, status_code = create_success_response({"board": result})
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        response.headers["Cache-Control"] = "private, no-store, max-age=0"
        return response, status_code
    except Exception as e:
        logger.error(f"Error getting public board '{slug}': {str(e)}")
        return create_error_response("Failed to load public board", 500)
    finally:
        db.close()


@board_bp.route("/api/public/boards/<string:slug>/cards/<int:card_id>", methods=["GET"])
def get_public_card(slug, card_id):
    """Get a single card from a public board by slug and card ID.
    ---
    tags:
      - Cards
    parameters:
      - name: slug
        in: path
        type: string
        required: true
        description: Public board slug
      - name: card_id
        in: path
        type: integer
        required: true
        description: The ID of the card to retrieve
    responses:
      200:
        description: Card data retrieved successfully
      404:
        description: Public board or card not found
      429:
        description: Too many requests
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        is_limited, retry_after = _check_public_endpoint_rate_limit()
        if is_limited:
            response, status_code = create_error_response("Too many requests", 429)
            response.headers["Retry-After"] = str(retry_after)
            response.headers["Cache-Control"] = "private, no-store, max-age=0"
            return response, status_code

        safe_slug = (slug or "").strip().lower()
        if not safe_slug or not PUBLIC_SLUG_PATTERN.fullmatch(safe_slug):
            return create_error_response("Board not found", 404)

        board = (
            db.query(Board)
            .filter(
                Board.public_slug == safe_slug,
                Board.is_public.is_(True),
                Board.archived.is_(False),
            )
            .first()
        )
        if not board:
            return create_error_response("Board not found", 404)

        card = (
            db.query(Card)
            .join(BoardColumn, Card.column_id == BoardColumn.id)
            .filter(
                BoardColumn.board_id == board.id,
                Card.id == card_id,
                Card.scheduled.is_(False),
            )
            .options(
                selectinload(Card.checklist_items),
                selectinload(Card.comments),
            )
            .first()
        )
        if not card:
            return create_error_response("Card not found", 404)

        card_data = {
            "id": card.id,
            "title": card.title,
            "description": card.description,
            "column_id": card.column_id,
            "order": card.order,
            "archived": card.archived,
            "done": card.done,
            "done_datetime": serialize_datetime(card.done_datetime),
            "created_at": serialize_datetime(card.created_at),
            "updated_at": serialize_datetime(card.updated_at),
            "checklist_items": [
                {
                    "id": item.id,
                    "card_id": item.card_id,
                    "name": item.name,
                    "checked": item.checked,
                    "order": item.order,
                    "created_at": serialize_datetime(item.created_at),
                    "updated_at": serialize_datetime(item.updated_at),
                }
                for item in sorted(card.checklist_items, key=lambda x: x.order)
            ],
            "comments": [
                {
                    "id": comment.id,
                    "card_id": comment.card_id,
                    "comment": comment.comment,
                    "order": comment.order,
                    "created_at": serialize_datetime(comment.created_at),
                }
                for comment in card.comments
            ],
        }

        response, status_code = create_success_response({"card": card_data})
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        response.headers["Cache-Control"] = "private, no-store, max-age=0"
        return response, status_code
    except Exception as e:
        logger.error(f"Error getting public card {card_id} for board '{slug}': {str(e)}")
        return create_error_response("Failed to load card", 500)
    finally:
        db.close()


@board_bp.route("/api/boards/<int:board_id>/owner", methods=["PUT"])
@require_board_access()
def reassign_board_owner(board_id):
    """Reassign a board to a different owner.

    Only board owners and administrators can reassign boards.
    ---
    tags:
        - Boards
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
                  - owner_id
              properties:
                  owner_id:
                      type: integer
                      example: 2
                      description: The new owner user ID
    responses:
        200:
            description: Board reassigned successfully
        400:
            description: Invalid request body
        403:
            description: Only board owners or administrators can reassign boards
        404:
            description: Board or owner not found
        500:
            description: Server error
    """
    db = SessionLocal()
    try:
        data = request.get_json(silent=True) or {}
        new_owner_id = data.get("owner_id")

        if not isinstance(new_owner_id, int) or new_owner_id <= 0:
            return create_error_response("owner_id must be a positive integer", 400)

        board = db.query(Board).filter(Board.id == board_id).first()
        if not board:
            return create_error_response("Board not found", 404)

        if not _can_reassign_board(board, g.user.id):
            return create_error_response(
                "Only board owners or administrators can reassign boards", 403
            )

        previous_owner_id = board.owner_id

        new_owner = (
            db.query(User)
            .filter(
                User.id == new_owner_id,
                User.is_active.is_(True),
                User.is_approved.is_(True),
            )
            .first()
        )
        if not new_owner:
            return create_error_response("Selected owner not found", 404)

        board_editor_assigned = _ensure_board_editor_role_assignment(db, new_owner.id, board.id)
        available_users = [_user_summary(user) for user in _get_board_reassignment_users(db)]

        board.owner_id = new_owner.id
        board.updated_at = utc_now()
        db.commit()
        db.refresh(board)

        logger.info(
            "Board %s ownership reassigned from user %s to user %s by user %s",
            board.id,
            previous_owner_id,
            new_owner.id,
            g.user.id,
        )
        if board_editor_assigned:
            logger.info(
                "Granted board_editor on board %s to reassigned owner user %s",
                board.id,
                new_owner.id,
            )

        return create_success_response(
            {
                **_build_board_owner_response(
                    board,
                    _can_reassign_board(board, g.user.id),
                    available_users=available_users,
                ),
                **_build_board_owner_metadata(board, g.user.id, db, include_candidates=True),
            },
            message="Board reassigned successfully",
        )
    except ValueError as e:
        db.rollback()
        logger.error(f"Error reassigning board {board_id}: {str(e)}")
        return create_error_response(str(e), 500)
    except Exception as e:
        db.rollback()
        logger.error(f"Error reassigning board {board_id}: {str(e)}")
        return create_error_response("Failed to reassign board", 500)
    finally:
        db.close()


@board_bp.route("/api/boards/<int:board_id>/owner", methods=["GET"])
@require_board_access()
def get_board_owner(board_id):
    """Get board owner metadata for reassignment UI.

    Users with board read access can retrieve owner details.
    Candidate users are returned only for board owners and administrators.
    ---
    tags:
        - Boards
    parameters:
        - name: board_id
          in: path
          type: integer
          required: true
          description: The ID of the board
    responses:
        200:
            description: Board owner metadata loaded successfully
        404:
            description: Board not found
        500:
            description: Server error
    """
    db = SessionLocal()
    try:
        board = db.query(Board).filter(Board.id == board_id).first()
        if not board:
            return create_error_response("Board not found", 404)

        can_reassign = _can_reassign_board(board, g.user.id)
        available_users = [_user_summary(user) for user in _get_board_reassignment_users(db)] if can_reassign else []

        return create_success_response(
            {
                **_build_board_owner_response(
                    board,
                    can_reassign,
                    available_users=available_users,
                ),
                **_build_board_owner_metadata(board, g.user.id, db, include_candidates=True),
            },
            message="Board owner metadata loaded successfully",
        )
    except Exception as e:
        logger.error(f"Error loading board owner metadata for board {board_id}: {str(e)}")
        return create_error_response("Failed to load board owner metadata", 500)
    finally:
        db.close()

