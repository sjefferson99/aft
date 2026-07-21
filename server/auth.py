"""
Authentication endpoints and middleware for AFT.

This module provides:
- Login/logout endpoints
- Session management
- Password hashing/verification
- User registration
- Authentication middleware
"""

import hashlib
import random
import secrets
import json

# Default avatar colours assigned randomly to new users (RGB hex)
AVATAR_COLOURS = [
    '#E57373',  # red
    '#F06292',  # pink
    '#BA68C8',  # purple
    '#7986CB',  # indigo
    '#64B5F6',  # blue
    '#4DB6AC',  # teal
    '#81C784',  # green
    '#FFD54F',  # amber
    '#FF8A65',  # deep orange
    '#90A4AE',  # blue-grey
]
from flask import Blueprint, request, jsonify, session, g
from sqlalchemy.sql import func
from database import SessionLocal
from models import User, Role, UserRole
from permissions import INITIAL_ROLES
from utils import (
    validate_string_length,
    create_error_response,
    create_success_response,
    MAX_TITLE_LENGTH
)
import logging

logger = logging.getLogger(__name__)

# Create blueprint for auth routes
auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

# Session configuration constants
SESSION_LIFETIME_HOURS = 24 * 7  # 7 days


def ensure_global_role(db, user_id, role_name):
  """Ensure the user has the specified global role.

  Returns True if the role was newly assigned, False if the user already had it.
  Raises ValueError if the role is not defined in INITIAL_ROLES and does not
  already exist in the database, so callers can distinguish a no-op from a
  configuration failure without issuing an extra query.
  """
  role = db.query(Role).filter(Role.name == role_name).first()
  if not role:
    role_info = INITIAL_ROLES.get(role_name)
    if not role_info:
      raise ValueError(f"System role '{role_name}' is not defined in INITIAL_ROLES")
    role = Role(
      name=role_name,
      description=role_info['description'],
      is_system_role=role_info['is_system_role'],
      permissions=json.dumps(role_info['permissions'])
    )
    db.add(role)
    db.flush()

  existing_assignment = db.query(UserRole).filter(
    UserRole.user_id == user_id,
    UserRole.role_id == role.id,
    UserRole.board_id.is_(None)
  ).first()
  if existing_assignment:
    return False

  db.add(UserRole(user_id=user_id, role_id=role.id, board_id=None))
  return True


def ensure_theme_user_role(db, user_id):
  """Ensure the user has the global theme_user role."""
  return ensure_global_role(db, user_id, 'theme_user')


def hash_password(password: str) -> str:
    """
    Hash a password using PBKDF2-HMAC-SHA256.
    
    Args:
        password: Plain text password
        
    Returns:
        Hashed password in format: salt$hash
    """
    salt = secrets.token_hex(32)
    pwd_hash = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000  # iterations
    )
    return f"{salt}${pwd_hash.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    """
    Verify a password against a hash.
    
    Args:
        password: Plain text password to verify
        password_hash: Stored hash in format: salt$hash
        
    Returns:
        True if password matches
    """
    try:
        salt, stored_hash = password_hash.split('$')
        pwd_hash = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            100000
        )
        return pwd_hash.hex() == stored_hash
    except Exception as e:
        logger.error(f"Password verification error: {e}")
        return False


def _password_session_fingerprint(password_hash: str) -> str:
    """Create a stable short fingerprint for session validation.

    The fingerprint lets us invalidate existing sessions when a password hash
    changes (for example, after an admin reset) without storing server-side
    session records.
    """
    if not password_hash:
        return ''
    return hashlib.sha256(password_hash.encode('utf-8')).hexdigest()[:16]


def _resolve_session_user(skip_email_hash_validation=False):
    """Resolve and validate the current session user.

    Args:
        skip_email_hash_validation: When True, does not validate the stored
            email hash against the current user email hash.

    Returns:
        tuple: (user, db_session)
            - user: Authenticated User or None
            - db_session: Open database session if user is returned, else None
    """
    user_id = session.get('user_id')
    stored_email_hash = session.get('user_email_hash')
    stored_password_fingerprint = session.get('user_pwd_hash')

    if not user_id:
        return None, None

    db = SessionLocal()
    try:
        user = db.query(User).filter(
            User.id == user_id,
            User.is_active == True,
            User.is_approved == True
        ).first()

        if not user:
            session.clear()
            db.close()
            return None, None

        if not skip_email_hash_validation:
            current_email_hash = hashlib.sha256(user.email.encode()).hexdigest()[:16]
            if stored_email_hash != current_email_hash:
                logger.warning(f"Session email hash mismatch for user_id={user_id}, clearing session")
                session.clear()
                db.close()
                return None, None

            current_password_fingerprint = _password_session_fingerprint(user.password_hash)
            if stored_password_fingerprint != current_password_fingerprint:
                logger.info(
                    "Session password fingerprint mismatch for user_id=%s; forcing re-authentication",
                    user_id,
                )
                session.clear()
                db.close()
                return None, None

        return user, db
    except Exception as e:
        logger.error(f"Error resolving user from session: {e}")
        db.close()
        return None, None


def get_authenticated_socket_user():
    """Resolve the currently authenticated session user for Socket.IO handlers.

    Unlike HTTP request middleware, this helper always closes the DB session and
    returns a detached user object for short-lived Socket.IO event checks.

    Returns:
        User | None: Authenticated and approved user, or None.
    """
    user, db = _resolve_session_user(skip_email_hash_validation=False)
    if not user or not db:
        return None

    try:
        db.expunge(user)
        return user
    finally:
        db.close()


def load_user_from_session():
    """
    Middleware to load user from session or Basic Auth into Flask g object.
    Call this in app.before_request.
    
    Supports:
    1. Session-based authentication (primary method)
    2. HTTP Basic Authentication (for Swagger UI testing)
    """
    from flask import request
    
    # Skip email hash validation during database restore operations
    # (the database is being modified, so user data may be temporarily inconsistent)
    is_restore_endpoint = (
        request.path.startswith('/api/database/restore') or
        request.path.startswith('/api/database/backups/restore/')
    )

    user, db = _resolve_session_user(skip_email_hash_validation=is_restore_endpoint)
    if user and db:
        g.user = user
        g.db = db  # Make db available for the request
        return
    
    g.user = None
    g.db = None
    
    # If no session auth, try Basic Auth (for Swagger UI)
    auth = request.authorization
    if auth and auth.username and auth.password:
        db = SessionLocal()
        try:
            from sqlalchemy.sql import func
            # Try email first, then username
            user = db.query(User).filter(
                func.lower(User.email) == auth.username.lower()
            ).first()
            
            if not user:
                user = db.query(User).filter(
                    func.lower(User.username) == auth.username.lower()
                ).first()
            
            if user and user.is_active and user.is_approved and user.password_hash:
                if verify_password(auth.password, user.password_hash):
                    g.user = user
                    g.db = db
                    return
            
            # Invalid Basic Auth
            g.user = None
            g.db = None
            db.close()
        except Exception as e:
            logger.error(f"Error loading user from Basic Auth: {e}")
            g.user = None
            g.db = None
            db.close()
    else:
        g.user = None
        g.db = None


@auth_bp.route('/login', methods=['POST'])
def login():
    """
    Login endpoint.
    ---
    tags:
      - Authentication
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - email
            - password
          properties:
            email:
              type: string
              description: Email address or username
              example: test-admin@localhost
            password:
              type: string
              format: password
              description: User password
              example: TestAdmin123!
            remember_me:
              type: boolean
              description: Keep user logged in
              default: false
    responses:
      200:
        description: Login successful
        schema:
          type: object
          properties:
            success:
              type: boolean
            message:
              type: string
            user:
              type: object
              properties:
                id:
                  type: integer
                email:
                  type: string
                username:
                  type: string
                display_name:
                  type: string
                email_verified:
                  type: boolean
      400:
        description: Validation error
      401:
        description: Invalid credentials
      403:
        description: Account disabled or pending approval
    """
    try:
        data = request.get_json()
        
        if not data:
            return create_error_response("Request body required", 400)
        
        email_or_username = data.get('email', '').strip()
        password = data.get('password', '')
        remember_me = data.get('remember_me', False)
        
        # Validate inputs
        if not email_or_username or not password:
            return create_error_response("Email/username and password are required", 400)
        
        # Find user by email or username
        db = SessionLocal()
        try:
            # Try to find user by email first (case-insensitive)
            user = db.query(User).filter(
                func.lower(User.email) == email_or_username.lower()
            ).first()
            
            # If not found by email, try by username (case-insensitive)
            if not user:
                user = db.query(User).filter(
                    func.lower(User.username) == email_or_username.lower()
                ).first()
            
            if not user:
                # Don't reveal whether user exists
                return create_error_response("Invalid email/username or password", 401)
            
            # Check if user has a password (might be OAuth only)
            if not user.password_hash:
                return create_error_response(
                    "This account uses OAuth login. Please use the appropriate login method.",
                    400
                )
            
            # Verify password
            if not verify_password(password, user.password_hash):
                return create_error_response("Invalid email/username or password", 401)
            
            # Check if account is active
            if not user.is_active:
                return create_error_response("Account is disabled", 403)
            
            # Check if account is approved
            if not user.is_approved:
                return create_error_response(
                    "Your account is pending administrator approval. You will be notified when approved.",
                    403
                )
            
            # Create session
            session.clear()
            session['user_id'] = user.id
            session['user_email_hash'] = hashlib.sha256(user.email.encode()).hexdigest()[:16]
            session['user_pwd_hash'] = _password_session_fingerprint(user.password_hash)
            session.permanent = remember_me

            # Update last login
            user.last_login_at = func.now()
            db.commit()
            
            # Get user's roles and permissions
            from utils import get_user_permissions
            
            roles = db.query(Role).join(UserRole).filter(
                UserRole.user_id == user.id,
                UserRole.board_id.is_(None)  # Global roles only
            ).all()
            
            # Get user's global permissions
            permissions = list(get_user_permissions(user.id))
            
            # Return user data (without sensitive fields)
            user_data = {
                'id': user.id,
                'email': user.email,
                'username': user.username,
                'display_name': user.display_name,
                'email_verified': user.email_verified,
                'roles': [{'id': r.id, 'name': r.name, 'description': r.description} for r in roles],
                'permissions': permissions
            }
            
            logger.info(f"User logged in: {user.email} (ID: {user.id})")
            
            return create_success_response(
                data={'user': user_data},
                message="Login successful"
            )
            
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Login error: {e}")
        return create_error_response("An error occurred during login", 500)


@auth_bp.route('/logout', methods=['POST'])
def logout():
    """
    Logout endpoint.
    ---
    tags:
      - Authentication
    responses:
      200:
        description: Logout successful
        schema:
          type: object
          properties:
            success:
              type: boolean
            message:
              type: string
    """
    user_id = session.get('user_id')
    session.clear()
    
    if user_id:
        logger.info(f"User logged out: ID {user_id}")
    
    return create_success_response(message="Logout successful")


@auth_bp.route('/validate', methods=['POST'])
def validate_credentials():
    """
    Validate credentials without creating a session.
    Used by Swagger UI to test credentials before using them.
    ---
    tags:
      - Authentication
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - email
            - password
          properties:
            email:
              type: string
              description: Email address or username
              example: test-admin@localhost
            password:
              type: string
              format: password
              description: User password
              example: TestAdmin123!
    responses:
      200:
        description: Credentials are valid
        schema:
          type: object
          properties:
            success:
              type: boolean
            message:
              type: string
            email:
              type: string
            username:
              type: string
      400:
        description: Validation error
      401:
        description: Invalid credentials
      403:
        description: Account disabled or pending approval
    """
    try:
        data = request.get_json()
        
        if not data:
            return create_error_response("Request body required", 400)
        
        email_or_username = data.get('email', '').strip()
        password = data.get('password', '')
        
        if not email_or_username or not password:
            return create_error_response("Email/username and password are required", 400)
        
        db = SessionLocal()
        try:
            # Try email first, then username
            user = db.query(User).filter(
                func.lower(User.email) == email_or_username.lower()
            ).first()
            
            if not user:
                user = db.query(User).filter(
                    func.lower(User.username) == email_or_username.lower()
                ).first()
            
            if not user:
                return create_error_response("Invalid email/username or password", 401)
            
            if not user.password_hash:
                return create_error_response(
                    "This account uses OAuth login",
                    400
                )
            
            if not verify_password(password, user.password_hash):
                return create_error_response("Invalid email/username or password", 401)
            
            if not user.is_active:
                return create_error_response("Account is disabled", 403)
            
            if not user.is_approved:
                return create_error_response(
                    "Account pending approval",
                    403
                )
            
            # Credentials are valid
            return create_success_response(
                message="Credentials valid",
                data={
                    'email': user.email,
                    'username': user.username
                }
            )
            
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Credential validation error: {e}")
        return create_error_response("Validation failed", 500)


@auth_bp.route('/me', methods=['GET'])
def get_current_user():
    """
    Get current authenticated user information.
    ---
    tags:
      - Authentication
    responses:
      200:
        description: Current user data
        schema:
          type: object
          properties:
            success:
              type: boolean
            user:
              type: object
              properties:
                id:
                  type: integer
                email:
                  type: string
                username:
                  type: string
                display_name:
                  type: string
                email_verified:
                  type: boolean
                oauth_provider:
                  type: string
                roles:
                  type: array
                  items:
                    type: object
                    properties:
                      id:
                        type: integer
                      name:
                        type: string
                      description:
                        type: string
                permissions:
                  type: array
                  items:
                    type: string
                  description: List of permission strings the user has
      401:
        description: Not authenticated
    """
    if not g.get('user'):
        return create_error_response("Not authenticated", 401)
    
    user = g.user
    
    # Get user's roles and permissions
    db = SessionLocal()
    try:
        from utils import get_user_permissions

        roles = db.query(Role).join(UserRole).filter(
            UserRole.user_id == user.id,
            UserRole.board_id.is_(None)  # Global roles only
        ).all()
        
        # Get user's global permissions
        permissions = list(get_user_permissions(user.id))
        
        user_data = {
            'id': user.id,
            'email': user.email,
            'username': user.username,
            'display_name': user.display_name,
            'email_verified': user.email_verified,
            'oauth_provider': user.oauth_provider,
            'profile_colour': user.profile_colour,
            'roles': [{'id': r.id, 'name': r.name, 'description': r.description} for r in roles],
            'permissions': permissions
        }
        
        return create_success_response(data={'user': user_data})
        
    finally:
        db.close()


@auth_bp.route('/profile', methods=['PATCH'])
def update_profile():
    """
    Update current user's profile information.
    ---
    tags:
      - Authentication
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            display_name:
              type: string
              description: User's display name
            username:
              type: string
              description: User's username
            email:
              type: string
              description: User's email address
    responses:
      200:
        description: Profile updated successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
            message:
              type: string
            user:
              type: object
      400:
        description: Validation error
      401:
        description: Not authenticated
      409:
        description: Username or email already exists
    """
    if not g.get('user'):
        return create_error_response("Not authenticated", 401)
    
    user = g.user
    data = request.get_json()
    
    if not data:
        return create_error_response("No data provided", 400)
    
    db = SessionLocal()
    try:
        # Get current user from database
        db_user = db.query(User).filter(User.id == user.id).first()
        if not db_user:
            return create_error_response("User not found", 404)
        
        # OAuth users cannot change email
        if db_user.oauth_provider and 'email' in data and data['email'] != db_user.email:
            return create_error_response("Cannot change email for OAuth accounts", 400)
        
        # Validate and update username
        if 'username' in data:
            new_username = data['username'].strip()
            if not new_username:
                return create_error_response("Username cannot be empty", 400)
            
            if len(new_username) > 100:
                return create_error_response("Username too long (max 100 characters)", 400)
            
            # Check if username is already taken by another user
            if new_username != db_user.username:
                existing_user = db.query(User).filter(
                    User.username == new_username,
                    User.id != user.id
                ).first()
                if existing_user:
                    return create_error_response("Username already taken", 409)

                db_user.username = new_username

        # Validate and update email
        if 'email' in data:
            new_email = data['email'].strip().lower()
            if not new_email:
                return create_error_response("Email cannot be empty", 400)

            # Basic email validation
            import re
            email_regex = r'^[^\s@]+@[^\s@]+\.[^\s@]+$'
            if not re.match(email_regex, new_email):
                return create_error_response("Invalid email format", 400)

            if len(new_email) > 255:
                return create_error_response("Email too long (max 255 characters)", 400)

            # Check if email is already taken by another user
            if new_email != db_user.email:
                existing_user = db.query(User).filter(
                    User.email == new_email,
                    User.id != user.id
                ).first()
                if existing_user:
                    return create_error_response("Email already taken", 409)

                db_user.email = new_email
                # Mark email as unverified if changed
                db_user.email_verified = False
        
        # Update display name (can be empty)
        if 'display_name' in data:
            display_name = data['display_name'].strip() if data['display_name'] else None
            if display_name and len(display_name) > 255:
                return create_error_response("Display name too long (max 255 characters)", 400)
            db_user.display_name = display_name
        
        db.commit()
        
        # Return updated user data
        user_data = {
            'id': db_user.id,
            'email': db_user.email,
            'username': db_user.username,
            'display_name': db_user.display_name,
            'email_verified': db_user.email_verified,
            'oauth_provider': db_user.oauth_provider
        }
        
        return create_success_response(
            message="Profile updated successfully",
            data={'user': user_data}
        )
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating profile: {e}")
        return create_error_response("Failed to update profile", 500)
    finally:
        db.close()


@auth_bp.route('/register', methods=['POST'])
def register():
    """
    Register a new user account.
    Note: New accounts require administrator approval before login.
    ---
    tags:
      - Authentication
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - email
            - username
            - password
          properties:
            email:
              type: string
              format: email
              description: Email address
              example: newuser@example.com
            username:
              type: string
              description: Username (unique)
              example: newuser
            password:
              type: string
              format: password
              description: Password (minimum 8 characters)
              example: SecurePass123!
            display_name:
              type: string
              description: Display name (optional)
              example: New User
    responses:
      201:
        description: User created successfully, pending approval
        schema:
          type: object
          properties:
            success:
              type: boolean
            message:
              type: string
            user:
              type: object
              properties:
                id:
                  type: integer
                email:
                  type: string
                username:
                  type: string
                display_name:
                  type: string
                requires_approval:
                  type: boolean
      400:
        description: Validation error
      409:
        description: Email or username already exists
    """
    try:
        data = request.get_json()
        
        if not data:
            return create_error_response("Request body required", 400)
        
        email = data.get('email', '').strip().lower()
        username = data.get('username', '').strip()
        password = data.get('password', '')
        display_name = data.get('display_name', '').strip()
        
        # Validate inputs
        if not email:
            return create_error_response("Email is required", 400)
        
        if not username:
            return create_error_response("Username is required", 400)
        
        if not password:
            return create_error_response("Password is required", 400)
        
        if len(password) < 8:
            return create_error_response("Password must be at least 8 characters", 400)
        
        # Validate string lengths
        is_valid, error = validate_string_length(email, MAX_TITLE_LENGTH, "Email")
        if not is_valid:
            return create_error_response(error, 400)
        
        is_valid, error = validate_string_length(username, 100, "Username")
        if not is_valid:
            return create_error_response(error, 400)
        
        # Check if user already exists
        db = SessionLocal()
        try:
            existing_email = db.query(User).filter(
                func.lower(User.email) == email
            ).first()
            
            if existing_email:
                return create_error_response("Email already registered", 409)
            
            existing_username = db.query(User).filter(
                func.lower(User.username) == func.lower(username)
            ).first()
            
            if existing_username:
                return create_error_response("Username already taken", 409)
            
            # Create user
            user = User(
                email=email,
                username=username,
                display_name=display_name or username,
                password_hash=hash_password(password),
                is_active=True,
                is_approved=False,  # Requires admin approval
                email_verified=False,  # TODO: Send verification email
                profile_colour=random.choice(AVATAR_COLOURS)
            )
            
            db.add(user)
            db.flush()  # Get user ID
            
            # Create default settings for the new user
            from auth_helpers import create_default_user_settings
            create_default_user_settings(user.id, db)
            
            db.commit()
            
            logger.info(f"New user registered: {user.email} (ID: {user.id})")
            
            # Don't auto-login - user needs admin approval
            # Return success but explain approval is needed
            user_data = {
                'id': user.id,
                'email': user.email,
                'username': user.username,
                'display_name': user.display_name,
                'requires_approval': True
            }
            
            return create_success_response(
                data={'user': user_data},
                message="Registration successful! Your account is pending administrator approval. You will be able to log in once approved.",
                status_code=201
            )
            
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Registration error: {e}")
        return create_error_response("An error occurred during registration", 500)


@auth_bp.route('/change-password', methods=['POST'])
def change_password():
    """
    Change password for current authenticated user or reset another user's password as an administrator.
    ---
    tags:
      - Authentication
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - new_password
          properties:
            user_id:
              type: integer
              description: Optional target user ID (administrator role only)
            current_password:
              type: string
              format: password
              description: Current password (required when changing your own password)
            new_password:
              type: string
              format: password
              description: New password (minimum 8 characters)
    responses:
      200:
        description: Password changed successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
            message:
              type: string
      400:
        description: Validation error
      401:
        description: Not authenticated or current password incorrect
      403:
        description: Non-administrator attempted to reset another user's password
      404:
        description: Target user not found
    """
    if not g.get('user'):
        return create_error_response("Not authenticated", 401)
    
    try:
        data = request.get_json()
        
        if not data:
            return create_error_response("Request body required", 400)
        
        current_password = data.get('current_password', '')
        new_password = data.get('new_password', '')
        target_user_id = data.get('user_id', g.user.id)

        try:
            target_user_id = int(target_user_id)
        except (TypeError, ValueError):
            return create_error_response("Invalid user_id", 400)

        is_admin_reset = target_user_id != g.user.id

        if is_admin_reset and not new_password:
            return create_error_response("New password is required", 400)

        if not is_admin_reset and (not current_password or not new_password):
            return create_error_response("Current and new password are required", 400)
        
        if len(new_password) < 8:
            return create_error_response("New password must be at least 8 characters", 400)
        
        db = SessionLocal()
        try:
            if is_admin_reset:
                admin_role_assignment = db.query(UserRole.id).join(Role).filter(
                    UserRole.user_id == g.user.id,
                    UserRole.board_id.is_(None),
                    Role.name == 'administrator'
                ).first()
                if not admin_role_assignment:
                    return create_error_response("Administrator role required to reset another user's password", 403)

            user = db.query(User).filter(User.id == target_user_id).first()

            if not user:
                return create_error_response("User not found", 404)

            if not user.password_hash:
                return create_error_response("Cannot change password for this account", 400)

            if not is_admin_reset:
                # Verify current password for self-service password changes.
                if not verify_password(current_password, user.password_hash):
                    return create_error_response("Current password is incorrect", 401)

            # Update password for either self-change or admin reset.
            user.password_hash = hash_password(new_password)
            db.commit()

            if is_admin_reset:
                logger.info(
                    "Password reset for user: %s (ID: %s) by admin %s",
                    user.email,
                    user.id,
                    g.user.id,
                )
                return create_success_response(message="Password reset successfully")

            logger.info(f"Password changed for user: {user.email} (ID: {user.id})")

            return create_success_response(message="Password changed successfully")
            
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Change password error: {e}")
        return create_error_response("An error occurred while changing password", 500)


@auth_bp.route('/check', methods=['GET'])
def check_auth():
    """
    Check if user is authenticated.
    ---
    tags:
      - Authentication
    responses:
      200:
        description: User is authenticated
        schema:
          type: object
          properties:
            authenticated:
              type: boolean
            user:
              type: object
              properties:
                id:
                  type: integer
                email:
                  type: string
                username:
                  type: string
                display_name:
                  type: string
      401:
        description: Not authenticated
        schema:
          type: object
          properties:
            authenticated:
              type: boolean
    """
    if g.get('user'):
        return jsonify({
            'authenticated': True,
            'user': {
                'id': g.user.id,
                'email': g.user.email,
                'username': g.user.username,
                'display_name': g.user.display_name
            }
        })
    
    return jsonify({'authenticated': False}), 401


@auth_bp.route('/setup/status', methods=['GET'])
def setup_status():
    """
    Check if initial setup is complete.
    ---
    tags:
      - Authentication
    responses:
      200:
        description: Setup status information
        schema:
          type: object
          properties:
            setup_complete:
              type: boolean
              description: Whether initial setup is complete
            has_users:
              type: boolean
              description: Whether any users exist in system
    """
    db = SessionLocal()
    try:
        # Check if any active users with passwords exist
        user_count = db.query(User).filter(
            User.is_active == True,
            User.password_hash.isnot(None)
        ).count()
        
        setup_complete = user_count > 0
        
        return jsonify({
            'setup_complete': setup_complete,
            'has_users': user_count > 0
        })
    finally:
        db.close()


@auth_bp.route('/setup/admin', methods=['POST'])
def setup_admin():
    """
    Create the first administrator account during initial setup.
    This endpoint only works if no users exist yet.
    ---
    tags:
      - Authentication
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - email
            - username
            - password
          properties:
            email:
              type: string
              format: email
              description: Administrator email
              example: admin@example.com
            username:
              type: string
              description: Administrator username
              example: admin
            password:
              type: string
              format: password
              description: Administrator password (minimum 8 characters)
              example: SecureAdminPass123!
            display_name:
              type: string
              description: Display name (optional)
              example: Administrator
    responses:
      201:
        description: Admin user created and logged in
        schema:
          type: object
          properties:
            success:
              type: boolean
            message:
              type: string
            user:
              type: object
              properties:
                id:
                  type: integer
                email:
                  type: string
                username:
                  type: string
                display_name:
                  type: string
      400:
        description: Validation error
      403:
        description: Setup already complete
    """
    try:
        db = SessionLocal()
        
        try:
            # Check if setup is already complete
            existing_users = db.query(User).filter(
                User.is_active == True,
                User.password_hash.isnot(None)
            ).count()

            if existing_users > 0:
                return create_error_response(
                    "Setup is already complete. Please use the login page.",
                    403
                )
            
            data = request.get_json()
            
            if not data:
                return create_error_response("Request body required", 400)
            
            email = data.get('email', '').strip().lower()
            username = data.get('username', '').strip()
            password = data.get('password', '')
            display_name = data.get('display_name', '').strip()
            
            # Validate inputs
            if not email:
                return create_error_response("Email is required", 400)
            
            if not username:
                return create_error_response("Username is required", 400)
            
            if not password:
                return create_error_response("Password is required", 400)
            
            if len(password) < 8:
                return create_error_response("Password must be at least 8 characters", 400)
            
            # Validate string lengths
            is_valid, error = validate_string_length(email, MAX_TITLE_LENGTH, "Email")
            if not is_valid:
                return create_error_response(error, 400)
            
            is_valid, error = validate_string_length(username, 100, "Username")
            if not is_valid:
                return create_error_response(error, 400)
            
            # Check if default admin user exists (from migration)
            existing_admin = db.query(User).filter(
                User.username == 'admin',
                User.email == 'admin@localhost'
            ).first()

            def ensure_administrator_role(target_user):
                """Ensure the target user has the global administrator role."""
                admin_role = db.query(Role).filter(Role.name == 'administrator').first()
                if not admin_role:
                    logger.warning("Administrator role not found during setup; role assignment skipped")
                    return

                existing_assignment = db.query(UserRole).filter(
                    UserRole.user_id == target_user.id,
                    UserRole.role_id == admin_role.id,
                    UserRole.board_id.is_(None)
                ).first()

                if not existing_assignment:
                    db.add(UserRole(user_id=target_user.id, role_id=admin_role.id, board_id=None))
            
            if existing_admin and not existing_admin.password_hash:
                # Update the existing admin user from migration
                existing_admin.email = email
                existing_admin.username = username
                existing_admin.display_name = display_name or username
                existing_admin.password_hash = hash_password(password)
                existing_admin.email_verified = True
                existing_admin.is_approved = True  # Admin is auto-approved
                if not existing_admin.profile_colour:
                    existing_admin.profile_colour = random.choice(AVATAR_COLOURS)
                
                # Create default settings for the admin user if they don't exist
                from auth_helpers import create_default_user_settings
                create_default_user_settings(existing_admin.id, db)

                # Ensure administrator role exists for updated seed admin user
                ensure_administrator_role(existing_admin)
                
                db.commit()
                
                user = existing_admin
                logger.info(f"Updated default admin user: {user.email} (ID: {user.id})")
            else:
                # Create new admin user
                user = User(
                    email=email,
                    username=username,
                    display_name=display_name or username,
                    password_hash=hash_password(password),
                    is_active=True,
                    is_approved=True,  # Admin is auto-approved
                    email_verified=True,
                    profile_colour=random.choice(AVATAR_COLOURS)
                )
                
                db.add(user)
                db.flush()  # Get user ID
                
                # Create default settings for the new admin user
                from auth_helpers import create_default_user_settings
                create_default_user_settings(user.id, db)
                
                # Assign administrator role
                ensure_administrator_role(user)
                
                db.commit()
                
                logger.info(f"Created first admin user: {user.email} (ID: {user.id})")
            
            # Auto-login after setup
            session['user_id'] = user.id
            session['user_email_hash'] = hashlib.sha256(user.email.encode()).hexdigest()[:16]
            session['user_pwd_hash'] = _password_session_fingerprint(user.password_hash)
            
            # Get user's roles and permissions
            from utils import get_user_permissions
            
            roles = db.query(Role).join(UserRole).filter(
                UserRole.user_id == user.id,
                UserRole.board_id.is_(None)  # Global roles only
            ).all()
            
            # Get user's global permissions
            permissions = list(get_user_permissions(user.id))
            
            user_data = {
                'id': user.id,
                'email': user.email,
                'username': user.username,
                'display_name': user.display_name,
                'profile_colour': user.profile_colour,
                'roles': [{'id': r.id, 'name': r.name, 'description': r.description} for r in roles],
                'permissions': permissions
            }
            
            return create_success_response(
                data={'user': user_data},
                message="Setup complete! Welcome to AFT.",
                status_code=201
            )
            
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Setup error: {e}")
        return create_error_response("An error occurred during setup", 500)
