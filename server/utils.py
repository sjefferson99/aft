"""Utility functions and decorators for the AFT application.

This module provides reusable helpers for:
- Database session management
- Input validation and sanitization
- Error response formatting
- User authentication and authorization
"""

import logging
import json
from functools import wraps
from typing import Callable, Any, Tuple
from flask import jsonify, request, g, abort
from database import SessionLocal

logger = logging.getLogger(__name__)

# Input validation constants
MAX_STRING_LENGTH = 10000  # Maximum length for any string input
MAX_TITLE_LENGTH = 255  # Maximum length for titles (board/column/card)
MAX_DESCRIPTION_LENGTH = 2000  # Maximum length for descriptions
MAX_COMMENT_LENGTH = 50000  # Maximum length for comments (50K chars for large notes)
MAX_REQUEST_SIZE = 10 * 1024 * 1024  # 10MB max request size

# Cap length of the client-supplied WebSocket session id header so a
# malformed/oversized value can't be used to probe or abuse Socket.IO
# internals. Socket.IO sids are short opaque tokens (typically ~20 chars).
MAX_SOCKET_ID_HEADER_LENGTH = 100


def get_request_socket_id() -> str | None:
    """Get the WebSocket session id the client attached to this HTTP request.

    The board UI tags mutating API requests with the id of its own active
    WebSocket connection (X-Socket-Id header, set in www/js/utils.js /
    board.js's WebSocketManager) so routes can pass it as skip_sid when
    broadcasting the resulting change. Without this, the originating client
    receives the echo of its own change over the WebSocket and reloads the
    board a second time for nothing.

    Returns None if the header is absent, empty, or implausibly long — never
    raises, since a missing/bad header should just mean "don't skip anyone",
    not break the request.
    """
    socket_id = request.headers.get("X-Socket-Id")
    if not socket_id or len(socket_id) > MAX_SOCKET_ID_HEADER_LENGTH:
        return None
    return socket_id


def db_session(func: Callable) -> Callable:
    """Decorator to handle database session lifecycle automatically.

    This decorator:
    1. Creates a database session
    2. Passes it to the decorated function
    3. Commits on success
    4. Rolls back on error
    5. Always closes the session

    Usage:
        @db_session
        def my_endpoint():
            # db parameter is automatically injected
            pass

    Args:
        func: The function to decorate

    Returns:
        Wrapped function with automatic session management
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        db = SessionLocal()
        try:
            # Inject db session as keyword argument
            result = func(*args, db=db, **kwargs)
            # If function succeeded and no explicit commit/rollback, commit
            if not db.is_active:
                # Session was already committed or rolled back
                pass
            else:
                db.commit()
            return result
        except Exception as e:
            db.rollback()
            logger.error(f"Error in {func.__name__}: {str(e)}")
            raise
        finally:
            db.close()

    return wrapper


def validate_json_content_type() -> Tuple[bool, Any]:
    """Validate that request has proper JSON content type.

    Returns:
        tuple: (is_valid, error_response or None)
    """
    if not request.is_json and request.data:
        return (
            False,
            jsonify(
                {"success": False, "message": "Content-Type must be application/json"}
            ),
            400,
        )
    return True, None


def validate_string_length(
    value: str, max_length: int, field_name: str
) -> Tuple[bool, str]:
    """Validate string length.

    Args:
        value: The string to validate
        max_length: Maximum allowed length
        field_name: Name of the field for error messages

    Returns:
        tuple: (is_valid, error_message or None)
    """
    if value is None:
        return True, None

    if not isinstance(value, str):
        return False, f"{field_name} must be a string"

    if len(value) > max_length:
        return False, f"{field_name} exceeds maximum length of {max_length} characters"

    return True, None


def validate_integer(
    value: Any,
    field_name: str,
    min_value: int = None,
    max_value: int = None,
    allow_none: bool = False,
) -> Tuple[bool, str]:
    """Validate integer value.

    Args:
        value: The value to validate
        field_name: Name of the field for error messages
        min_value: Minimum allowed value (optional)
        max_value: Maximum allowed value (optional)
        allow_none: Whether None is allowed

    Returns:
        tuple: (is_valid, error_message or None)
    """
    if value is None:
        if allow_none:
            return True, None
        return False, f"{field_name} is required"

    # Reject boolean values (True/False are instances of int in Python)
    if isinstance(value, bool):
        return False, f"{field_name} must be an integer, not boolean"

    if not isinstance(value, int):
        return False, f"{field_name} must be an integer"

    if min_value is not None and value < min_value:
        return False, f"{field_name} must be at least {min_value}"

    if max_value is not None and value > max_value:
        return False, f"{field_name} must be at most {max_value}"

    return True, None


def sanitize_string(value: str) -> str:
    """Sanitize string input by removing potentially dangerous characters.

    This is a basic sanitization. SQL injection is prevented by using
    SQLAlchemy's parameterized queries. This mainly prevents XSS if
    the API responses are rendered in HTML without escaping.

    Args:
        value: The string to sanitize

    Returns:
        Sanitized string
    """
    if value is None:
        return None

    # Strip leading/trailing whitespace
    value = value.strip()

    # Additional sanitization can be added here if needed
    # For now, we rely on proper escaping on the frontend

    return value


def validate_request_size() -> Tuple[bool, Any]:
    """Validate request size to prevent DoS attacks.

    Returns:
        tuple: (is_valid, error_response or None)
    """
    content_length = request.content_length

    if content_length and content_length > MAX_REQUEST_SIZE:
        return (
            False,
            jsonify(
                {
                    "success": False,
                    "message": f"Request size exceeds maximum allowed size of {MAX_REQUEST_SIZE} bytes",
                }
            ),
            413,
        )  # 413 Payload Too Large

    return True, None


def create_error_response(message: str, status_code: int = 400) -> Tuple[Any, int]:
    """Create a standardized error response.

    Args:
        message: Error message to return
        status_code: HTTP status code

    Returns:
        tuple: (json_response, status_code)
    """
    return jsonify({"success": False, "message": message}), status_code


def create_success_response(
    data: dict = None, message: str = None, status_code: int = 200
) -> Tuple[Any, int]:
    """Create a standardized success response.

    Args:
        data: Data to include in response
        message: Optional success message
        status_code: HTTP status code

    Returns:
        tuple: (json_response, status_code)
    """
    response = {"success": True}

    if message:
        response["message"] = message

    if data:
        response.update(data)

    return jsonify(response), status_code


# ============================================================================
# User Authentication and Authorization Functions
# ============================================================================

def get_user_scoped_query(db, model, user_id):
    """
    Get a query for a model automatically scoped to user.
    This is the PRIMARY defense against cross-user data access.
    
    CRITICAL: Always use this function when querying user-owned data.
    This prevents accidental data leaks across users.
    
    BOARD ACCESS MODEL:
    - Boards are included if user OWNS them (owner_id) OR has explicit role assignment (UserRole with board_id)
    - Having global permissions does NOT automatically grant access to all boards
    - Only 'system.admin' permission grants universal access (checked separately in endpoints)
    - Cards, Columns, Comments inherit board access through their relationships
    
    Args:
        db: Database session
        model: SQLAlchemy model class
        user_id: ID of the current user
        
    Returns:
        SQLAlchemy query scoped to the user
        
    Raises:
        ValueError: If model scoping is not defined (fail secure)
    """
    # Import here to avoid circular imports
    from models import Board, BoardColumn, Card, ChecklistItem, Comment, Setting, Theme, Notification, ScheduledCard, UserRole
    
    query = db.query(model)

    from permissions import has_permission

    # Notifications are ALWAYS user-scoped, even for admins
    # (admins shouldn't see other users' personal notifications)
    if model.__name__ == 'Notification':
        return query.filter(model.user_id == user_id)
    
    if has_permission(get_user_permissions(user_id), 'system.admin'):
        return query
    
    # Models with direct user_id column
    if hasattr(model, 'user_id'):
        # For settings/themes, include user items plus globally visible items.
        # Theme global visibility includes system themes (user_id IS NULL)
        # and user-owned themes marked global_theme=True.
        if model.__name__ in ['Setting', 'Theme']:
            if model.__name__ == 'Theme':
                return query.filter(
                    (model.user_id == user_id)
                    | (model.user_id.is_(None))
                    | (model.global_theme.is_(True))
                )
            return query.filter((model.user_id == user_id) | (model.user_id.is_(None)))
        # For notifications, only show user's own (already handled above)
        return query.filter(model.user_id == user_id)
    
    # Models with owner_id (like Board) - include owned boards AND boards where user has a role
    if hasattr(model, 'owner_id'):
        # Board can be accessed if user owns it OR has a role on it
        owned = query.filter(model.owner_id == user_id)
        role_based = query.join(UserRole).filter(UserRole.user_id == user_id)
        return owned.union(role_based)
    
    # Models that inherit permissions through relationships
    # Card inherits from Board through Column - include owned boards AND role-assigned boards
    if model.__name__ == 'Card':
        return query.join(BoardColumn).join(Board).filter(
            (Board.owner_id == user_id) | 
            (Board.id.in_(
                db.query(UserRole.board_id).filter(UserRole.user_id == user_id)
            ))
        )
    
    if model.__name__ == 'BoardColumn':
        return query.join(Board).filter(
            (Board.owner_id == user_id) | 
            (Board.id.in_(
                db.query(UserRole.board_id).filter(UserRole.user_id == user_id)
            ))
        )
    
    if model.__name__ == 'ChecklistItem':
        return query.join(Card).join(BoardColumn).join(Board).filter(
            (Board.owner_id == user_id) | 
            (Board.id.in_(
                db.query(UserRole.board_id).filter(UserRole.user_id == user_id)
            ))
        )
    
    if model.__name__ == 'Comment':
        return query.join(Card).join(BoardColumn).join(Board).filter(
            (Board.owner_id == user_id) | 
            (Board.id.in_(
                db.query(UserRole.board_id).filter(UserRole.user_id == user_id)
            ))
        )
    
    if model.__name__ == 'ScheduledCard':
        return query.join(Card).join(BoardColumn).join(Board).filter(
            (Board.owner_id == user_id) | 
            (Board.id.in_(
                db.query(UserRole.board_id).filter(UserRole.user_id == user_id)
            ))
        )
    
    # Fail secure: if we don't know how to scope it, raise an error
    logger.error(f"No scoping rule defined for model {model.__name__}. This is a security issue!")
    raise ValueError(f"Cannot scope queries for model {model.__name__}. Access denied.")


def get_current_user_id():
    """
    Get the current user's ID from Flask's g object.
    
    Returns:
        int: User ID or None if not authenticated
    """
    user = g.get('user')
    return user.id if user else None


def require_permission(permission, require_board_context=None):
    """
    Decorator to check if current user has required permission.
    
    This decorator checks both global and board-specific permissions.
    If the decorated function has a board_id, column_id, card_id, schedule_id, or item_id parameter,
    board-specific permissions are also checked by looking up the associated board.
    Also checks request body for these IDs if not found in URL parameters.
    
    Security: For operations that should always have board context (cards, columns, schedules, checklists),
    if board_id cannot be determined, access is DENIED by default for safety.
    
    Usage:
        @require_permission('board.edit')
        def edit_board(board_id):
            ...
        
        @require_permission('column.update')  # Auto-requires board context
        def update_column(column_id):
            ...
        
        @require_permission('card.create')  # Auto-requires board context
        def create_schedule():  # card_id in request body
            ...
        
        @require_permission('setting.edit')  # Doesn't require board context
        def update_setting():
            ...
    
    Args:
        permission: Permission string to require (e.g., 'board.edit')
        require_board_context: If True, denies access if board_id can't be determined.
                              If None (default), auto-detects based on permission type.
                              If False, allows global permission check without board context.
        
    Returns:
        Decorator function
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not g.get('user'):
                abort(401, description="Authentication required")
            
            # Try to get board_id for board-specific permissions
            board_id = kwargs.get('board_id')
            source_column_id = kwargs.get('source_column_id')
            target_column_id = kwargs.get('target_column_id')
            column_id = kwargs.get('column_id') or source_column_id or target_column_id
            card_id = kwargs.get('card_id')
            comment_id = kwargs.get('comment_id')
            schedule_id = kwargs.get('schedule_id')
            item_id = kwargs.get('item_id')  # checklist item
            missing_resource_message = None
            
            # If not in URL params, try request body
            if board_id is None and column_id is None and card_id is None and comment_id is None and schedule_id is None and item_id is None:
                try:
                    data = request.get_json(silent=True)
                    if data:
                        board_id = data.get('board_id')
                        column_id = data.get('column_id') or data.get('target_column_id')
                        card_id = data.get('card_id')
                        comment_id = data.get('comment_id')
                        schedule_id = data.get('schedule_id')
                        item_id = data.get('item_id')
                        
                        # For batch operations, try to get first card_id from card_ids array
                        if card_id is None and 'card_ids' in data:
                            card_ids = data.get('card_ids')
                            if isinstance(card_ids, list) and len(card_ids) > 0:
                                card_id = card_ids[0]
                except Exception:
                    pass

            # If no board_id, try to derive it from comment_id
            if board_id is None and comment_id:
                from models import Comment
                db = SessionLocal()
                try:
                    comment = db.query(Comment).filter(Comment.id == comment_id).first()
                    if not comment:
                        missing_resource_message = "Comment not found"
                    elif comment.card:
                        card_id = comment.card.id
                        if comment.card.column:
                            board_id = comment.card.column.board_id
                        else:
                            missing_resource_message = "Column not found"
                    else:
                        missing_resource_message = "Card not found"
                finally:
                    db.close()
            
            # If no board_id, try to derive it from item_id (checklist item)
            if board_id is None and item_id:
                from models import ChecklistItem, Card
                db = SessionLocal()
                try:
                    item = db.query(ChecklistItem).filter(ChecklistItem.id == item_id).first()
                    if not item:
                        missing_resource_message = "Checklist item not found"
                    elif item.card:
                        card_id = item.card.id
                        if item.card.column:
                            board_id = item.card.column.board_id
                        else:
                            missing_resource_message = "Card not found"
                    else:
                        missing_resource_message = "Card not found"
                finally:
                    db.close()
            
            # If no board_id, try to derive it from schedule_id
            if board_id is None and schedule_id:
                from models import ScheduledCard, Card
                db = SessionLocal()
                try:
                    schedule = db.query(ScheduledCard).filter(ScheduledCard.id == schedule_id).first()
                    if not schedule:
                        missing_resource_message = "Schedule not found"
                    elif schedule.template_card:
                        card_id = schedule.template_card.id
                        if schedule.template_card.column:
                            board_id = schedule.template_card.column.board_id
                        else:
                            missing_resource_message = "Card not found"
                    else:
                        missing_resource_message = "Card not found"
                finally:
                    db.close()
            
            # If no board_id, try to derive it from column_id
            if board_id is None and column_id:
                from models import BoardColumn
                db = SessionLocal()
                try:
                    column = db.query(BoardColumn).filter(BoardColumn.id == column_id).first()
                    if column:
                        board_id = column.board_id
                    else:
                        # Be specific about which column wasn't found
                        if source_column_id and column_id == source_column_id:
                            missing_resource_message = "Source column not found"
                        elif target_column_id and column_id == target_column_id:
                            missing_resource_message = "Target column not found"
                        else:
                            missing_resource_message = "Column not found"
                finally:
                    db.close()
            
            # If no board_id, try to derive it from card_id
            if board_id is None and card_id:
                from models import Card
                db = SessionLocal()
                try:
                    card = db.query(Card).filter(Card.id == card_id).first()
                    if not card:
                        missing_resource_message = "Card not found"
                    elif card.column:
                        board_id = card.column.board_id
                    else:
                        missing_resource_message = "Column not found"
                finally:
                    db.close()
            
            # Fallback: check if first arg is an integer (might be an ID)
            if board_id is None and len(args) > 0 and isinstance(args[0], int):
                # Try to determine if it's a board_id, column_id, card_id, schedule_id, or item_id based on function name
                func_name = f.__name__.lower()
                if 'board' in func_name:
                    board_id = args[0]
                elif 'checklist' in func_name or 'item' in func_name:
                    item_id = args[0]
                    from models import ChecklistItem, Card
                    db = SessionLocal()
                    try:
                        item = db.query(ChecklistItem).filter(ChecklistItem.id == item_id).first()
                        if not item:
                            missing_resource_message = "Checklist item not found"
                        elif item.card and item.card.column:
                            board_id = item.card.column.board_id
                        elif not item.card:
                            missing_resource_message = "Card not found"
                        else:
                            missing_resource_message = "Column not found"
                    finally:
                        db.close()
                elif 'schedule' in func_name:
                    schedule_id = args[0]
                    from models import ScheduledCard, Card
                    db = SessionLocal()
                    try:
                        schedule = db.query(ScheduledCard).filter(ScheduledCard.id == schedule_id).first()
                        if not schedule:
                            missing_resource_message = "Schedule not found"
                        elif schedule.template_card and schedule.template_card.column:
                            board_id = schedule.template_card.column.board_id
                        elif not schedule.template_card:
                            missing_resource_message = "Card not found"
                        else:
                            missing_resource_message = "Column not found"
                    finally:
                        db.close()
                elif 'column' in func_name:
                    column_id = args[0]
                    from models import BoardColumn
                    db = SessionLocal()
                    try:
                        column = db.query(BoardColumn).filter(BoardColumn.id == column_id).first()
                        if column:
                            board_id = column.board_id
                        else:
                            missing_resource_message = "Column not found"
                    finally:
                        db.close()
                elif 'card' in func_name:
                    card_id = args[0]
                    from models import Card
                    db = SessionLocal()
                    try:
                        card = db.query(Card).filter(Card.id == card_id).first()
                        if not card:
                            missing_resource_message = "Card not found"
                        elif card and card.column:
                            board_id = card.column.board_id
                        else:
                            missing_resource_message = "Column not found"
                    finally:
                        db.close()
                elif 'comment' in func_name:
                    comment_id = args[0]
                    from models import Comment
                    db = SessionLocal()
                    try:
                        comment = db.query(Comment).filter(Comment.id == comment_id).first()
                        if not comment:
                            missing_resource_message = "Comment not found"
                        elif comment.card and comment.card.column:
                            board_id = comment.card.column.board_id
                        elif not comment.card:
                            missing_resource_message = "Card not found"
                        else:
                            missing_resource_message = "Column not found"
                    finally:
                        db.close()

            # Auto-detect if board context should be required based on permission type
            needs_board_context = require_board_context
            if needs_board_context is None:
                # Permissions that MUST have board context for security
                board_related_perms = [
                    'card.', 'column.', 'schedule.',
                    'board.edit', 'board.delete'
                ]
                needs_board_context = any(permission.startswith(prefix) or permission == prefix.rstrip('.') 
                                         for prefix in board_related_perms)
            
            # Only abort for missing resources if board context is required
            if needs_board_context and board_id is None and missing_resource_message:
                abort(404, description=missing_resource_message)
            
            # If board context is required but couldn't be determined, DENY access for security
            if needs_board_context and board_id is None:
                abort(403, description=f"Permission denied: {permission} (board context required but not found)")
            
            # Get permissions (global and board-specific if board_id is available)
            user_permissions = get_user_permissions(g.user.id, board_id)
            
            # Check if user has the required permission
            from permissions import has_permission
            if not has_permission(user_permissions, permission):
                abort(403, description=f"Permission denied: {permission}")
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def require_any_permission(*permissions):
    """
    Decorator to check if current user has ANY of the required permissions.
    
    Usage:
        @require_any_permission('role.manage', 'user.role')
        def get_roles():
            ...
    
    Args:
        permissions: Variable number of permission strings
        
    Returns:
        Decorator function
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not g.get('user'):
                abort(401, description="Authentication required")
            
            user_permissions = get_user_permissions(g.user.id)
            
            # Check if user has any of the required permissions
            from permissions import has_permission
            has_any = any(has_permission(user_permissions, perm) for perm in permissions)
            
            if not has_any:
                perms_str = ' or '.join(permissions)
                abort(403, description=f"Permission denied: requires {perms_str}")
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def require_board_access(require_owner=False):
    """
    Decorator to check if user can access a board.
    Expects board_id as a parameter to the decorated function.
    
    Usage:
        @require_board_access()
        def get_board(board_id):
            ...
            
        @require_board_access(require_owner=True)
        def delete_board(board_id):
            ...
    
    Args:
        require_owner: If True, user must be the board owner (default: False)
        
    Returns:
        Decorator function
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not g.get('user'):
                abort(401, description="Authentication required")
            
            # Get board_id from kwargs or args
            board_id = kwargs.get('board_id')
            if board_id is None and len(args) > 0:
                board_id = args[0]
            
            if board_id is None:
                abort(400, description="Board ID required")

            from models import Board
            db = SessionLocal()
            try:
                board_exists = db.query(Board.id).filter(Board.id == board_id).first()
            finally:
                db.close()

            # Return 403 (not 404) to avoid leaking information about board existence
            # From a security perspective, "board doesn't exist" and "you can't access this board"
            # should look the same to the user
            if not board_exists:
                abort(403, description="Access denied to this board")
            
            # Check access
            has_access, is_owner = can_access_board(g.user.id, board_id)
            
            if not has_access:
                abort(403, description="Access denied to this board")
            
            if require_owner and not is_owner:
                abort(403, description="Board owner access required")
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def get_user_permissions(user_id, board_id=None):
    """
    Get all permissions for a user, optionally scoped to a board.
    
    BOARD OWNER LOGIC:
      - If checking permissions for a board the user OWNS, they automatically get ALL board-related permissions
      - Board owners have full control regardless of assigned roles
    
    When board_id is provided:
      - First checks if user is the board owner (if so, returns all board permissions)
      - If user has board-specific roles for that board, ONLY those are used
      - If no board-specific roles exist, falls back to global roles
      - Board-specific roles can restrict access even if user has powerful global roles
    
    Args:
        user_id: User ID
        board_id: Optional board ID to get board-specific permissions
        
    Returns:
        set: Set of permission strings
    """
    from models import Role, UserRole, Board
    
    db = SessionLocal()
    try:
        global_query = db.query(Role.permissions).join(UserRole).filter(
            UserRole.user_id == user_id,
            UserRole.board_id.is_(None)
        )

        global_perms = set()
        for (perms_json,) in global_query.all():
            perms = json.loads(perms_json)
            global_perms.update(perms)

        if board_id:
            # Check if user is the board owner - owners have ALL permissions on their boards
            board = db.query(Board).filter(Board.id == board_id).first()
            if board and board.owner_id == user_id:
                # Board owner gets all board-related permissions automatically
                owner_perms = {
                    'board.view', 'board.edit', 'board.delete',
                    'card.create', 'card.view', 'card.edit', 'card.update', 
                    'card.delete', 'card.archive',
                    'column.create', 'column.update', 'column.delete',
                    'schedule.create', 'schedule.view', 'schedule.edit', 'schedule.delete',
                    'setting.view', 'setting.edit',
                }
                # Also include global permissions (for user.role, theme permissions, etc)
                owner_perms.update(global_perms)
                return owner_perms
            
            # Not the owner - check for board-specific roles
            board_specific_query = db.query(Role.permissions).join(UserRole).filter(
                UserRole.user_id == user_id,
                UserRole.board_id == board_id
            )
            
            board_specific_perms = set()
            has_board_specific_roles = False
            
            for (perms_json,) in board_specific_query.all():
                has_board_specific_roles = True
                perms = json.loads(perms_json)
                board_specific_perms.update(perms)
            
            # If board-specific roles exist, use those plus any global system-level
            # permissions that must remain universal, especially system.admin.
            if has_board_specific_roles:
                if 'system.admin' in global_perms:
                    board_specific_perms.add('system.admin')
                return board_specific_perms
            
            # No board-specific roles, fall through to get global roles

        return global_perms
    finally:
        db.close()


def can_access_board(user_id, board_id):
    """
    Check if user can access a board (owns it or has a role on it).
    
    BOARD ACCESS is granted through THREE mechanisms:
    1. Ownership: User created the board (board.owner_id == user_id)
    2. Explicit role assignment: Admin granted user a board-specific role (UserRole with board_id)
    3. Global admin access: User has system.admin permission (grants access to ALL boards)
    
    Args:
        user_id: User ID
        board_id: Board ID
        
    Returns:
        tuple: (has_access: bool, is_owner: bool)
    """
    from models import Board, UserRole
    from permissions import has_permission
    
    db = SessionLocal()
    try:
        board = db.query(Board).filter(Board.id == board_id).first()
        if not board:
            return False, False
        
        # Owner always has access
        if board.owner_id == user_id:
            return True, True
        
        # Check if user has system.admin permission (grants access to all boards)
        user_permissions = get_user_permissions(user_id)
        if has_permission(user_permissions, 'system.admin'):
            return True, False
        
        # Check if user has any role on this board
        has_role = db.query(UserRole).filter(
            UserRole.user_id == user_id,
            UserRole.board_id == board_id
        ).first() is not None
        
        return has_role, False
    finally:
        db.close()


def get_user_role_ids(user_id, board_id=None):
    """
    Get all role IDs assigned to a user.
    
    Args:
        user_id: User ID
        board_id: Optional board ID to get board-specific roles only
        
    Returns:
        set: Set of role IDs the user has
    """
    from models import UserRole
    
    db = SessionLocal()
    try:
        query = db.query(UserRole.role_id).filter(UserRole.user_id == user_id)
        
        if board_id is not None:
            # Get roles for this specific board
            query = query.filter(UserRole.board_id == board_id)
        else:
            # Get global roles (board_id is NULL)
            query = query.filter(UserRole.board_id.is_(None))
        
        role_ids = {role_id for (role_id,) in query.all()}
        return role_ids
    finally:
        db.close()


def require_authentication(f):
    """
    Decorator to require authentication but not specific permissions.
    
    Usage:
        @require_authentication
        def my_endpoint():
            # g.user is guaranteed to exist
            ...
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not g.get('user'):
            abort(401, description="Authentication required")
        return f(*args, **kwargs)
    return decorated_function
