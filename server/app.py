from flask import Flask, jsonify, request, g
from flask_socketio import SocketIO
from flask_cors import CORS
import logging
import os
import re
import time
import tempfile
from pathlib import Path
from flasgger import Swagger
from database import SessionLocal
from models import User
from sqlalchemy.exc import OperationalError, ProgrammingError
from werkzeug.routing import BaseConverter
from utils import (
    create_error_response,
    create_success_response,
)
from auth import auth_bp, load_user_from_session
from user_management import user_mgmt_bp
from role_management import role_mgmt_bp
from board_routes import board_bp, configure_board_routes
from health_routes import health_bp, configure_health_routes
from theme_routes import theme_bp, configure_theme_routes
from notification_routes import notification_bp
from settings_routes import settings_bp, configure_settings_routes
from backup_routes import backup_bp, configure_backup_routes
from column_routes import column_bp, configure_column_routes
from card_routes import card_bp, configure_card_routes
from schedule_routes import schedule_bp, configure_schedule_routes
from branding_routes import branding_bp
from planner_routes import planner_bp
from broadcasting import (
    broadcast_failures,
    broadcast_failures_lock,
    configure_broadcasting,
)
from websocket_handlers import register_websocket_handlers
from scheduler_lock import acquire_scheduler_lock
from security_validators import (
        validate_backup_file_security,
        validate_backup_file_size,
    validate_safe_url,
        validate_schema_integrity,
)

# Keep legacy imports re-exported from app.py for existing tests/callers.
__all__ = [
    "validate_backup_file_security",
    "validate_backup_file_size",
    "validate_safe_url",
    "validate_schema_integrity",
]

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Application version
APP_VERSION = "2026.5.2"

app = Flask(__name__)

# Configure session
app.config['SESSION_COOKIE_SECURE'] = os.getenv('SESSION_COOKIE_SECURE', 'True').lower() == 'true'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = 60 * 60 * 24 * 7  # 7 days

if not app.config['SESSION_COOKIE_SECURE']:
    logger.warning(
        'SESSION_COOKIE_SECURE is set to false. Session cookies may be transmitted over plain HTTP. '
        'Use only in controlled local development scenarios.'
    )

# Custom path converter that allows safe filenames (validation happens in the endpoint)
class SafeFilenameConverter(BaseConverter):
    """Converter for image filenames - matches filenames with a restricted safe character set.
    
    The actual security validation (preventing .. traversal) is done in the endpoint
    function itself, not in the regex. The regex here ensures only safe characters are
    accepted in the path segment.
    """
    regex = r'[a-zA-Z0-9._-]+'  # Only allow alphanumerics, dot, underscore, and hyphen

app.url_map.converters['safe_filename'] = SafeFilenameConverter

# Initialize CORS for HTTP and WebSocket endpoints
# Parse CORS allowed origins from environment variable
# Controls which origins can connect via HTTP/HTTPS and WebSocket
cors_origins_env = os.getenv('CORS_ALLOWED_ORIGINS', 'http://localhost')
cors_allowed_origins = [origin.strip() for origin in cors_origins_env.split(',')]

# Initialize Flask-CORS for HTTP/HTTPS endpoints
# Flask-CORS validates all cross-origin requests (requests with Origin header) against
# the configured origins list. Requests without an Origin header are processed normally
# (same-origin requests in browsers, or requests from non-browser clients).
# For disallowed origins, Flask-CORS will not add CORS headers to the response,
# which causes the browser to reject the cross-origin request.
CORS(
    app,
    origins=cors_allowed_origins,
    supports_credentials=True,
    methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS', 'PATCH']
)

# Initialize SocketIO for WebSocket support with Redis message queue for multi-worker support
# Redis allows multiple gunicorn workers to communicate WebSocket events to each other
redis_url = os.getenv('REDIS_URL')
server_side_sessions_enabled = os.getenv('ENABLE_SERVER_SIDE_SESSIONS', 'false').lower() == 'true'
redis_configured = bool(redis_url)

_secret_key = os.getenv('SECRET_KEY')
if not _secret_key:
    raise RuntimeError(
        'SECRET_KEY environment variable is not set. '
        'Generate one with: python -c "import secrets; print(secrets.token_hex(32))" '
        'and add it to your .env file. Never use a hardcoded or default secret in production.'
    )
app.config['SECRET_KEY'] = _secret_key

if server_side_sessions_enabled:
    if not redis_url:
        raise RuntimeError(
            'ENABLE_SERVER_SIDE_SESSIONS=true requires REDIS_URL to be configured.'
        )

    try:
        import redis
        from flask_session import Session as ServerSideSession
    except ImportError as e:
        raise RuntimeError(
            'ENABLE_SERVER_SIDE_SESSIONS=true requires flask-session and redis packages. '
            'Install with: pip install -r server/requirements.txt'
        ) from e

    app.config['SESSION_TYPE'] = 'redis'
    app.config['SESSION_REDIS'] = redis.from_url(redis_url)
    app.config['SESSION_KEY_PREFIX'] = 'aft:session:'
    app.config['SESSION_PERMANENT'] = True
    app.config['SESSION_USE_SIGNER'] = True
    ServerSideSession(app)
    logger.info(
        'Session mode: server-side (Redis). feature_flag=ENABLE_SERVER_SIDE_SESSIONS:true redis_configured=%s',
        redis_configured,
    )
else:
    logger.info(
        'Session mode: client-side (Flask signed cookie). feature_flag=ENABLE_SERVER_SIDE_SESSIONS:false redis_configured=%s',
        redis_configured,
    )

# Validate Redis configuration for multi-worker deployment
if not redis_url:
    logger.warning(
        "⚠️  REDIS_URL not configured. WebSocket broadcasts will NOT work across multiple gunicorn workers. "
        "Real-time updates may be lost if requests are routed to different workers. "
        "Set REDIS_URL environment variable to enable cross-worker WebSocket communication."
    )

socketio = SocketIO(
    app, 
    cors_allowed_origins=cors_allowed_origins,
    async_mode='threading',
    message_queue=redis_url  # Connect to Redis for message queue (None if not configured)
)

# Broadcast helpers and failure tracking (moved to broadcasting.py)
configure_health_routes(APP_VERSION, broadcast_failures, broadcast_failures_lock)

broadcast_event, broadcast_theme_event = configure_broadcasting(socketio)

# TESTING FLAG: When True, all new Socket.IO connections are rejected.
# Set via REJECT_SOCKETIO_CONNECTIONS=true env var. Never enable in production.
REJECT_SOCKETIO_CONNECTIONS = os.getenv("REJECT_SOCKETIO_CONNECTIONS", "false").lower() == "true"

# Register websocket broadcaster callback for the scheduler without importing app from scheduler.
try:
    from card_scheduler import set_broadcast_event_callback

    set_broadcast_event_callback(broadcast_event)
except Exception as callback_err:
    logger.warning(f"Failed to register scheduler broadcast callback: {callback_err}")

# Configure route blueprints
configure_settings_routes(app, APP_VERSION)
configure_backup_routes(APP_VERSION)
configure_board_routes(APP_VERSION)
configure_column_routes(broadcast_event)
configure_card_routes(broadcast_event)
configure_schedule_routes(broadcast_event)
configure_theme_routes(broadcast_theme_event)

# Register Socket.IO event handlers
register_websocket_handlers(socketio, reject_connections=REJECT_SOCKETIO_CONNECTIONS)

# Configure maximum upload size (110MB)
app.config["MAX_CONTENT_LENGTH"] = 110 * 1024 * 1024

# Configure Swagger
swagger_config = {
    "headers": [],
    "specs": [
        {
            "endpoint": "apispec",
            "route": "/api/apispec.json",
            "rule_filter": lambda rule: True,  # all in
            "model_filter": lambda tag: True,  # all in
        }
    ],
    "static_url_path": "/api/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/api/docs",
}

swagger_template = {
    "swagger": "2.0",
    "info": {
        "title": "AFT API",
        "description": """
API documentation for AFT application

**Authentication:** This API uses session-based authentication. To test authenticated endpoints in Swagger UI:

### Recommended Workflow
1. **First, validate your credentials**: Call `/api/auth/validate` (POST) with your credentials to verify they work
2. **Then, set up authentication**: 
   - Click the "Authorise" button (🔓) at the top right
   - Enter your credentials in the BasicAuth section (use email as username)
   - Click "Authorise"
3. **Test endpoints**: Your credentials will be sent with each request

⚠️ **Important**: The Authorise modal will say "Authorized" even with invalid credentials. 
This is a Swagger limitation - credentials are only validated when you actually call an endpoint.
Always use `/api/auth/validate` first to verify your credentials are correct.

### Alternative: Session-Based Login
1. Call `/api/auth/login` (POST) with your email and password
2. The session cookie will be automatically set and used for all requests
3. No need to use the Authorise button

### Default Test Credentials
- Email: `test-admin@localhost`
- Password: `TestAdmin123!`

<a href="/" style="text-decoration: none;">← Back to AFT Home</a>
        """,
        "version": "1.0.0",
    },
    "basePath": "/",
    "schemes": ["http", "https"],
    "securityDefinitions": {
        "SessionAuth": {
            "type": "apiKey",
            "name": "session",
            "in": "cookie",
            "description": "Session-based authentication. Login via `/api/auth/login` to obtain a session cookie."
        },
        "BasicAuth": {
            "type": "basic",
            "description": "⚠️ Basic Auth for testing. Modal accepts any input - credentials are validated when calling endpoints. Use /api/auth/validate to test credentials first."
        }
    },
    "security": [
        {"SessionAuth": []},
        {"BasicAuth": []}
    ]
}

swagger = Swagger(app, config=swagger_config, template=swagger_template)

# ============================================================================
# Authentication Setup
# ============================================================================

# Register authentication and shared route blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(user_mgmt_bp)
app.register_blueprint(role_mgmt_bp)
app.register_blueprint(health_bp)
app.register_blueprint(theme_bp)
app.register_blueprint(notification_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(backup_bp)
app.register_blueprint(board_bp)
app.register_blueprint(column_bp)
app.register_blueprint(card_bp)
app.register_blueprint(schedule_bp)
app.register_blueprint(branding_bp)
app.register_blueprint(planner_bp)

# Load user from session before each request
@app.before_request
def before_request():
    """Load authenticated user into Flask g object and check setup status."""
    # Skip setup check for setup/auth endpoints, health checks, and static files
    if (
        request.path.startswith('/api/auth/setup') or
        request.path == '/api/test' or  # Legacy health endpoint
        request.path == '/api/health/live' or
        request.path == '/api/health/ready' or
        request.path == '/api/server-health' or
        request.path.startswith('/setup.html') or
        request.path.startswith('/css/') or
        request.path.startswith('/js/') or
        request.path.startswith('/images/')
    ):
        load_user_from_session()
        return
    
    # Check if initial setup is complete (any active user with password exists).
    has_users = None
    db = SessionLocal()
    try:
      try:
        has_users = db.query(User).filter(
                    User.is_active,
          User.password_hash.isnot(None)
        ).count() > 0
      except (ProgrammingError, OperationalError) as error:
        # During /api/database resets, tables are briefly absent while Alembic
        # recreates the schema. Let reset/restore routes continue so their own
        # locking and wait logic can finish the operation.
        # IMPORTANT: do NOT treat a transient DB disconnect as "setup not done";
        # we only redirect to initial setup when we actually know there are no users.
        logger.info(f"Setup check skipped during transient database reset: {error}")
        if request.path.startswith('/api/database'):
          load_user_from_session()
          return

        if has_users is None:
            return jsonify({
                'success': False,
                'message': 'Service temporarily unavailable',
                'redirect': None,
            }), 503
    finally:
        db.close()

    if has_users is False:
        # Redirect to setup page for HTML requests
        if not request.path.startswith('/api/'):
            if request.path != '/setup.html':
                from flask import redirect
                return redirect('/setup.html', code=302)
        # For API requests, return a specific error
        else:
            return jsonify({
                'success': False,
                'message': 'Initial setup required',
                'redirect': '/setup.html'
            }), 503
    
    load_user_from_session()

# Close database session after each request if it was opened
@app.teardown_request
def teardown_request(exception=None):
    """Close database session if it was opened."""
    db = g.pop('db', None)
    if db is not None:
        try:
            db.close()
        except Exception as e:
            # Connection may have been killed during restore operations
            # This is expected and can be safely ignored
            logger.debug(f"Error closing database session in teardown (connection may have been killed): {e}")

# Request size limit (110MB) for non-file-upload endpoints
MAX_REQUEST_SIZE = 110 * 1024 * 1024


@app.before_request
def validate_request():
    """Validate incoming requests for security.

    This runs before every request to:
    1. Check request size to prevent DoS attacks (except file uploads)
    2. Validate Content-Type for JSON requests
    """
    # Exclude restore endpoints from size check (they use Flask's MAX_CONTENT_LENGTH instead)
    restore_endpoints = ['/api/database/restore', '/api/database/backups/restore/']
    is_restore_endpoint = any(request.path.startswith(endpoint) for endpoint in restore_endpoints)
    
    # Check request size for non-restore endpoints
    if not is_restore_endpoint and request.content_length and request.content_length > MAX_REQUEST_SIZE:
        return create_error_response(
            f"Request size exceeds maximum of {MAX_REQUEST_SIZE} bytes", 413
        )

    # Validate Content-Type for requests with body
    if request.method in ["POST", "PUT", "PATCH"]:
        if request.data and not request.is_json:
            # Allow multipart/form-data for file uploads
            if not request.content_type or not request.content_type.startswith(
                "multipart/form-data"
            ):
                return create_error_response(
                    "Content-Type must be application/json for JSON requests", 400
                )


# Board routes moved to board_routes.py
# Helper functions (_user_summary, _parse_assignee_ids_query_param, etc.) moved to board_routes.py

# Column routes moved to column_routes.py

# Card routes moved to card_routes.py

# Schedule, checklist, and comment routes moved to schedule_routes.py


# Error handlers to ensure API endpoints return JSON
@app.errorhandler(401)
def unauthorized_error(error):
    """Handle 401 errors with JSON response for API endpoints."""
    if request.path.startswith('/api/'):
        return jsonify({
            "success": False, 
            "message": str(error.description) if hasattr(error, 'description') else "Authentication required"
        }), 401
    return error


@app.errorhandler(403)
def forbidden_error(error):
    """Handle 403 errors with JSON response for API endpoints."""
    if request.path.startswith('/api/'):
        return jsonify({
            "success": False, 
            "message": str(error.description) if hasattr(error, 'description') else "Access forbidden"
        }), 403
    return error


@app.errorhandler(404)
def not_found_error(error):
    """Handle 404 errors with JSON response for API endpoints."""
    if request.path.startswith('/api/'):
        # Check if error has a custom description (e.g., "Column not found")
        message = str(error.description) if hasattr(error, 'description') and error.description else "Endpoint not found"
        return jsonify({"success": False, "message": message}), 404
    # For non-API routes, return default Flask 404
    return error


@app.errorhandler(405)
def method_not_allowed_error(error):
    """Handle 405 errors with JSON response for API endpoints."""
    if request.path.startswith('/api/'):
        return jsonify({"success": False, "message": "Method not allowed"}), 405
    return error


@app.errorhandler(413)
def request_entity_too_large_error(error):
    """Handle 413 errors (Request Entity Too Large) with JSON response for API endpoints."""
    if request.path.startswith('/api/'):
        return jsonify({
            "success": False, 
            "message": f"File size exceeds maximum allowed size of {app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)}MB"
        }), 413
    return error


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors with JSON response for API endpoints."""
    if request.path.startswith('/api/'):
        logger.error(f"Internal server error: {str(error)}")
        return jsonify({"success": False, "message": "Internal server error"}), 500
    return error


# Initialize backup scheduler on app startup
def cleanup_stale_scheduler_locks():
    """Remove stale scheduler lock files on application startup.

    Active lock owners are preserved to avoid forcing duplicate schedulers.
    """
    from pathlib import Path
    import tempfile
    from scheduler_lock import is_scheduler_lock_stale

    temp_dir = Path(tempfile.gettempdir())
    lock_files = [
        (temp_dir / "aft_backup_scheduler.lock", "backup"),
        (temp_dir / "aft_card_scheduler.lock", "card"),
        (temp_dir / "aft_housekeeping_scheduler.lock", "housekeeping"),
    ]

    for lock_file, scheduler_type in lock_files:
        try:
            if not lock_file.exists():
                continue

            if is_scheduler_lock_stale(lock_file, scheduler_type, stale_after_seconds=300):
                lock_file.unlink()
                logger.info("Cleaned up stale scheduler lock file: %s", lock_file)
            else:
                logger.info("Keeping active scheduler lock file: %s", lock_file)
        except Exception as e:
            logger.warning(f"Failed to clean lock file {lock_file}: {e}")


def init_backup_scheduler():
    """Initialize and start the backup scheduler."""
    try:
        from backup_scheduler import get_scheduler
        scheduler = get_scheduler()
        scheduler.start()
        logger.info("Backup scheduler initialization attempted")
    except Exception as e:
        logger.error(f"Failed to initialize backup scheduler: {str(e)}")

# Initialize card scheduler on app startup
def init_card_scheduler():
    """Initialize and start the card scheduler."""
    try:
        from card_scheduler import get_scheduler
        scheduler = get_scheduler()
        scheduler.start()
        logger.info("Card scheduler initialization attempted")
    except Exception as e:
        logger.error(f"Failed to initialize card scheduler: {str(e)}")

# Initialize housekeeping scheduler on app startup
def init_housekeeping_scheduler():
    """Initialize and start the housekeeping scheduler."""
    try:
        from housekeeping_scheduler import start_housekeeping_scheduler
        start_housekeeping_scheduler(APP_VERSION)
        logger.info("Housekeeping scheduler initialization attempted")
    except Exception as e:
        logger.error(f"Failed to initialize housekeeping scheduler: {str(e)}")

# Start schedulers when module is loaded
# Use file lock to ensure only one worker initializes schedulers
# This prevents race conditions with Gunicorn multi-worker setup

skip_scheduler_init = os.getenv('AFT_SKIP_SCHEDULER_INIT', 'false').lower() == 'true'
if skip_scheduler_init:
    logger.info("Skipping scheduler initialization because AFT_SKIP_SCHEDULER_INIT=true")

# Only initialize schedulers in the first worker to start.
# The init lock must use process-aware stale detection to avoid false stale evictions.
init_lock_file = Path(tempfile.gettempdir()) / "aft_scheduler_init.lock"

if skip_scheduler_init:
    acquired_init_lock, init_lock_details = False, {"reason": "skipped_by_env"}
    should_init = False
else:
    acquired_init_lock, init_lock_details = acquire_scheduler_lock(
        lock_file=init_lock_file,
        scheduler_type="scheduler_init",
        stale_after_seconds=300,
    )
    should_init = acquired_init_lock

if should_init:
    logger.info(
        "Worker PID %s: Acquired scheduler init lock (%s)",
        os.getpid(),
        init_lock_details,
    )
else:
    logger.info(
        "Worker PID %s: Init lock is held, skipping scheduler initialization (%s)",
        os.getpid(),
        init_lock_details,
    )

if should_init:
    try:
        logger.info(f"Worker PID {os.getpid()}: Initializing schedulers")
        
        # Clean up any stale lock files from previous container instances
        # This must happen AFTER acquiring init lock to prevent race conditions
        cleanup_stale_scheduler_locks()
        
        # Now start all schedulers
        init_backup_scheduler()
        init_card_scheduler()
        init_housekeeping_scheduler()  # Housekeeping also monitors other schedulers' health
        
        # Give schedulers a moment to create their lock files
        time.sleep(0.5)
    except Exception as e:
        logger.error(f"Error initializing schedulers: {e}")
else:
    logger.info(f"Worker PID {os.getpid()}: Waiting for first worker to initialize schedulers")
    # Wait for the first worker to finish initializing
    time.sleep(2)


# ============================================================================
# WebSocket handlers moved to websocket_handlers.py
_HEX_COLOUR_RE = re.compile(r'^#[0-9A-Fa-f]{6}$')


@app.route("/api/users/me/profile-colour", methods=["PUT"])
def update_profile_colour():
    """Update the current user's profile colour.
    ---
    tags:
      - Users
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - profile_colour
          properties:
            profile_colour:
              type: string
              description: RGB hex colour string e.g. '#E57373'
    responses:
      200:
        description: Profile colour updated successfully
      400:
        description: Invalid colour value
      500:
        description: Server error
    """
    try:
        data = request.get_json()
    except Exception:
        data = None
    if not g.get('user'):
      return create_error_response("Not authenticated", 401)
    if not data:
        return create_error_response("No data provided", 400)

    colour = data.get('profile_colour')
    if not colour or not isinstance(colour, str) or not _HEX_COLOUR_RE.match(colour):
        return create_error_response("profile_colour must be a valid RGB hex string e.g. '#A1B2C3'", 400)

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == g.user.id).first()
        if not user:
            return create_error_response("User not found", 404)
        setattr(user, "profile_colour", colour)
        db.commit()
        return create_success_response({'profile_colour': colour})
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating profile colour for user {g.user.id}: {str(e)}")
        return create_error_response("Failed to update profile colour", 500)
    finally:
        db.close()


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000)


