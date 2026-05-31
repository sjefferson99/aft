"""Health, diagnostics, and admin utility routes extracted from app.py."""

import json
import logging
import os
import secrets
from datetime import datetime

from flask import Blueprint, g, jsonify, request
from sqlalchemy import text

from database import SessionLocal
from models import Board, BoardColumn, Card, ChecklistItem, Role, User, UserRole
from utils import (
    get_user_permissions,
    get_user_scoped_query,
    require_any_permission,
    require_authentication,
    require_permission,
)

logger = logging.getLogger(__name__)

health_bp = Blueprint("health_routes", __name__)

APP_VERSION = "unknown"
BROADCAST_FAILURES = {}
BROADCAST_FAILURES_LOCK = None

TEST_USER_EMAIL = "test-admin@localhost"
TEST_USER_USERNAME = "test-admin"
TEST_USER_DISPLAY_NAME = "Test Admin"


def configure_health_routes(app_version, broadcast_failures, broadcast_failures_lock):
    """Inject runtime dependencies owned by the main app module."""
    global APP_VERSION, BROADCAST_FAILURES, BROADCAST_FAILURES_LOCK
    APP_VERSION = app_version
    BROADCAST_FAILURES = broadcast_failures
    BROADCAST_FAILURES_LOCK = broadcast_failures_lock


def _collect_scheduler_health() -> dict:
    """Collect detailed scheduler thread health data for all background schedulers."""
    health = {}

    try:
        from backup_scheduler import get_scheduler
        scheduler = get_scheduler()

        status = scheduler.get_status()
        last_backup_iso = status.get('latest_backup_date')

        lock_file_exists = scheduler.lock_file.exists()
        is_healthy = False

        if lock_file_exists:
            try:
                lock_data = json.loads(scheduler.lock_file.read_text())
                last_heartbeat = datetime.fromisoformat(lock_data['last_heartbeat'])
                lock_age = (datetime.now() - last_heartbeat).total_seconds()
                is_healthy = lock_age < 150

                health['backup_scheduler'] = {
                    'running': is_healthy,
                    'thread_alive': is_healthy,
                    'last_backup': last_backup_iso,
                    'lock_file_exists': True,
                    'lock_file_age_seconds': lock_age,
                    'lock_pid': lock_data.get('pid'),
                    'lock_container': lock_data.get('container_id'),
                    'permission_error': scheduler.permission_error
                }
            except Exception as e:
                health['backup_scheduler'] = {
                    'running': False,
                    'thread_alive': False,
                    'lock_file_exists': True,
                    'lock_file_error': str(e),
                    'permission_error': scheduler.permission_error
                }
        else:
            health['backup_scheduler'] = {
                'running': False,
                'thread_alive': False,
                'last_backup': last_backup_iso,
                'lock_file_exists': False,
                'permission_error': scheduler.permission_error
            }
    except Exception as e:
        health['backup_scheduler'] = {'error': str(e)}

    try:
        from card_scheduler import get_scheduler as get_card_scheduler
        scheduler = get_card_scheduler()

        lock_file_exists = scheduler.lock_file.exists()
        is_healthy = False

        if lock_file_exists:
            try:
                lock_data = json.loads(scheduler.lock_file.read_text())
                last_heartbeat = datetime.fromisoformat(lock_data['last_heartbeat'])
                lock_age = (datetime.now() - last_heartbeat).total_seconds()
                is_healthy = lock_age < 150

                health['card_scheduler'] = {
                    'running': is_healthy,
                    'thread_alive': is_healthy,
                    'lock_file_exists': True,
                    'lock_file_age_seconds': lock_age,
                    'lock_pid': lock_data.get('pid'),
                    'lock_container': lock_data.get('container_id')
                }
            except Exception as e:
                health['card_scheduler'] = {
                    'running': False,
                    'thread_alive': False,
                    'lock_file_exists': True,
                    'lock_file_error': str(e)
                }
        else:
            health['card_scheduler'] = {
                'running': False,
                'thread_alive': False,
                'lock_file_exists': False
            }
    except Exception as e:
        health['card_scheduler'] = {'error': str(e)}

    try:
        from housekeeping_scheduler import get_housekeeping_scheduler
        scheduler = get_housekeeping_scheduler(APP_VERSION)

        lock_file_exists = scheduler.lock_file.exists()
        is_healthy = False

        if lock_file_exists:
            try:
                lock_data = json.loads(scheduler.lock_file.read_text())
                last_heartbeat = datetime.fromisoformat(lock_data['last_heartbeat'])
                lock_age = (datetime.now() - last_heartbeat).total_seconds()
                is_healthy = lock_age < 150

                health['housekeeping_scheduler'] = {
                    'running': is_healthy,
                    'thread_alive': is_healthy,
                    'lock_file_exists': True,
                    'lock_file_age_seconds': lock_age,
                    'lock_pid': lock_data.get('pid'),
                    'lock_container': lock_data.get('container_id')
                }
            except Exception as e:
                health['housekeeping_scheduler'] = {
                    'running': False,
                    'thread_alive': False,
                    'lock_file_exists': True,
                    'lock_file_error': str(e)
                }
        else:
            health['housekeeping_scheduler'] = {
                'running': False,
                'thread_alive': False,
                'lock_file_exists': False
            }
    except Exception as e:
        health['housekeeping_scheduler'] = {'error': str(e)}

    return health


def _is_scheduler_thread_healthy(details: dict) -> bool:
    """Return True when scheduler detail payload reports a running/alive thread."""
    if not isinstance(details, dict):
        return False
    if details.get('error'):
        return False
    return bool(details.get('running')) and bool(details.get('thread_alive'))


def _evaluate_server_health() -> bool:
    """Evaluate whether the server should be considered healthy for monitoring."""
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db.close()
        return False
    finally:
        try:
            db.close()
        except Exception:
            pass

    scheduler_health = _collect_scheduler_health()

    # Thread health is always required regardless of enabled/disabled workload state.
    for scheduler_key in ('backup_scheduler', 'card_scheduler', 'housekeeping_scheduler'):
        if not _is_scheduler_thread_healthy(scheduler_health.get(scheduler_key, {})):
            return False

    # Backup workload health should only count when automatic backups are enabled.
    try:
        from backup_scheduler import get_scheduler
        backup_status = get_scheduler().get_status()
        backup_enabled = bool(backup_status.get('enabled'))
        if backup_enabled and not bool(backup_status.get('backup_within_window')):
            return False
    except Exception:
        return False

    return True


@health_bp.route("/api/version")
@require_authentication
def get_version():
    """Get application and database schema version.
    ---
    tags:
      - Health
    security:
      - SessionAuth: []
    responses:
      200:
        description: App and DB version numbers
        schema:
          type: object
          properties:
            success:
              type: boolean
            app_version:
              type: string
            db_version:
              type: string
      500:
        description: Database error
    """
    db = SessionLocal()
    try:
        result = db.execute(text("SELECT version_num FROM alembic_version"))
        row = result.fetchone()
        db_version = row[0] if row else "unknown"

        return jsonify(
            {"success": True, "app_version": APP_VERSION, "db_version": db_version}
        )
    except Exception as e:
        logger.error(f"Error getting version: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        db.close()


def _find_known_test_user(db):
    return db.query(User).filter(
        User.email == TEST_USER_EMAIL,
        User.username == TEST_USER_USERNAME,
    ).first()


@health_bp.route("/api/admin/test-user", methods=["GET"])
@require_any_permission('user.manage', 'user.role')
def get_test_user_status():
    """Get known test user status and test compatibility guidance.
    ---
    tags:
      - Admin
    security:
      - SessionAuth: []
    responses:
      200:
        description: Test user presence and compatibility details
      403:
        description: Insufficient permissions
    """
    from permissions import has_permission

    db = SessionLocal()
    try:
        test_user = _find_known_test_user(db)
        user_permissions = get_user_permissions(g.user.id)
        can_remove = has_permission(user_permissions, 'user.manage')

        detected_user = None
        if test_user:
            detected_user = {
                "id": test_user.id,
                "email": test_user.email,
                "username": test_user.username,
                "display_name": test_user.display_name,
                "is_active": test_user.is_active,
                "is_approved": test_user.is_approved,
            }

        return jsonify({
            "success": True,
            "test_user_present": test_user is not None,
            "test_user_compatible": bool(
                test_user and test_user.is_active and test_user.is_approved
            ),
            "clean_database_compatible": True,
            "expected_user": {
                "email": TEST_USER_EMAIL,
                "username": TEST_USER_USERNAME,
                "display_name": TEST_USER_DISPLAY_NAME,
            },
            "detected_user": detected_user,
            "permissions": {
                "can_remove": can_remove,
            },
        })
    finally:
        db.close()


@health_bp.route("/api/admin/test-user", methods=["DELETE"])
@require_permission('user.manage')
def remove_test_user():
    """Remove the known test user if present.
    ---
    tags:
      - Admin
    security:
      - SessionAuth: []
    responses:
      200:
        description: Test user deleted
      404:
        description: Test user not found
      403:
        description: Insufficient permissions
      500:
        description: Deletion failed
    """
    db = SessionLocal()
    try:
        test_user = _find_known_test_user(db)
        if not test_user:
            return jsonify({
                "success": False,
                "message": "Known test user was not found",
            }), 404

        deleted_current_user = test_user.id == g.user.id
        user_id = test_user.id
        username = test_user.username

        db.query(UserRole).filter(UserRole.user_id == user_id).delete()
        db.delete(test_user)
        db.commit()

        logger.info(
            f"Known test user deleted: {username} (ID: {user_id}) by user {g.user.id}"
        )

        return jsonify({
            "success": True,
            "action": "deleted",
            "deleted_current_user": deleted_current_user,
            "message": f"Known test user '{username}' has been deleted",
        })
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting known test user: {e}")
        return jsonify({
            "success": False,
            "message": f"Failed to delete known test user: {str(e)}",
        }), 500
    finally:
        db.close()


@health_bp.route("/api/debug/permissions")
@require_authentication
def debug_user_permissions():
    """Check the current user's resolved permissions, optionally scoped to a board.
    ---
    tags:
      - Admin
    security:
      - SessionAuth: []
    parameters:
      - name: board_id
        in: query
        required: false
        type: integer
        description: Optional board ID for board-scoped permission resolution
    responses:
      200:
        description: User permissions and role assignments
      403:
        description: Not authenticated
    """
    board_id = request.args.get('board_id', type=int)

    db = SessionLocal()
    try:
        global_perms = get_user_permissions(g.user.id, board_id=None)

        board_perms = None
        if board_id:
            board_perms = get_user_permissions(g.user.id, board_id=board_id)

        role_assignments = db.query(UserRole, Role).join(
            Role, UserRole.role_id == Role.id
        ).filter(
            UserRole.user_id == g.user.id
        ).all()

        roles_data = []
        for user_role, role in role_assignments:
            roles_data.append({
                'role_name': role.name,
                'role_id': role.id,
                'board_id': user_role.board_id,
                'permissions': json.loads(role.permissions) if isinstance(role.permissions, str) else role.permissions
            })

        return jsonify({
            'success': True,
            'user_id': g.user.id,
            'username': g.user.username,
            'checked_board_id': board_id,
            'global_permissions': sorted(list(global_perms)),
            'board_specific_permissions': sorted(list(board_perms)) if board_perms else None,
            'all_role_assignments': roles_data
        })
    finally:
        db.close()


@health_bp.route("/api/permissions/mapping")
@require_authentication
def get_permissions_mapping():
    """Get the full API endpoint-to-permission mapping with current user's access.
    ---
    tags:
      - Admin
    security:
      - SessionAuth: []
    parameters:
      - name: board_id
        in: query
        required: false
        type: integer
        description: Optional board ID for board-scoped permission evaluation
    responses:
      200:
        description: Permission mapping with user's current access status
      403:
        description: Not authenticated
    """
    board_id = request.args.get('board_id', type=int)
    db = SessionLocal()

    try:
        user_perms = get_user_permissions(g.user.id, board_id=board_id)

        has_board_assignment = db.query(UserRole.id).filter(
            UserRole.user_id == g.user.id,
            UserRole.board_id.isnot(None)
        ).first() is not None

        has_board_edit_assignment = False
        if has_board_assignment:
            board_role_assignments = (
                db.query(UserRole, Role)
                .join(Role, UserRole.role_id == Role.id)
                .filter(
                    UserRole.user_id == g.user.id,
                    UserRole.board_id.isnot(None),
                )
                .all()
            )
            for _, role in board_role_assignments:
                try:
                    role_permissions = set(json.loads(role.permissions))
                except (TypeError, json.JSONDecodeError):
                    continue
                if 'board.edit' in role_permissions:
                    has_board_edit_assignment = True
                    break

        endpoint_mapping = {
            'GET /api/boards': {
                'mode': 'composite',
                'any_permissions': ['board.view', 'board.create'],
                'allow_board_assignment': True,
                'description': 'View boards list (global board permission OR board assignment)'
            },
            'POST /api/boards': {'permission': 'board.create', 'description': 'Create new board'},
            'POST /api/boards/import': {
              'mode': 'composite',
              'any_permissions': ['board.create', 'board.edit'],
              'allow_board_edit_assignment': True,
              'description': 'Import board from AFT JSON export'
            },
            'DELETE /api/boards/:id': {'permission': 'board.delete', 'description': 'Delete board'},
            'PATCH /api/boards/:id': {'permission': 'board.edit', 'description': 'Edit board'},
            'PATCH /api/boards/:id/archive': {'permission': 'board.edit', 'description': 'Archive board'},
            'PATCH /api/boards/:id/unarchive': {'permission': 'board.edit', 'description': 'Unarchive board'},
            'GET /api/boards/:id/export': {'permission': 'board.view', 'description': 'Export board as JSON'},
            'GET /api/boards/:id/cards/scheduled': {'permission': 'schedule.view', 'description': 'View scheduled cards'},
            'GET /api/boards/:id/cards': {'permission': 'card.view', 'description': 'View board cards'},
            'GET /api/boards/:id/settings/working-style': {'permission': 'board.view', 'description': 'View board working style'},
            'PUT /api/boards/:id/settings/working-style': {'permission': 'board.edit', 'description': 'Update board working style'},
            'GET /api/boards/:id/columns': {'permission': 'board.view', 'description': 'View board columns'},
            'POST /api/boards/:id/columns': {'permission': 'column.create', 'description': 'Create column'},
            'DELETE /api/columns/:id': {'permission': 'column.delete', 'description': 'Delete column'},
            'PATCH /api/columns/:id': {'permission': 'column.update', 'description': 'Update column'},
            'GET /api/columns/:id/cards': {'permission': 'card.view', 'description': 'View column cards'},
            'GET /api/columns/:id/cards/scheduled': {'permission': 'schedule.view', 'description': 'View scheduled cards in column'},
            'POST /api/columns/:id/archive-after': {'permission': 'card.archive', 'description': 'Archive cards after position'},
            'POST /api/columns/:id/cards': {'permission': 'card.create', 'description': 'Create card'},
            'DELETE /api/columns/:id/cards': {'permission': 'card.delete', 'description': 'Delete all cards in column'},
            'POST /api/columns/:source_id/cards/move': {'permission': 'card.update', 'description': 'Move card between columns'},
            'GET /api/cards/:id': {'permission': 'card.view', 'description': 'View card details'},
            'PATCH /api/cards/:id': {'permission': 'card.update', 'description': 'Update card'},
            'DELETE /api/cards/:id': {'permission': 'card.delete', 'description': 'Delete card'},
            'PATCH /api/cards/:id/archive': {'permission': 'card.archive', 'description': 'Archive card'},
            'PATCH /api/cards/:id/unarchive': {'permission': 'card.archive', 'description': 'Unarchive card'},
            'GET /api/cards/:id/done': {'permission': 'card.view', 'description': 'Get card done status'},
            'PATCH /api/cards/:id/done': {'permission': 'card.update', 'description': 'Update card done status'},
            'GET /api/cards/:id/assignees': {'permission': 'card.view', 'description': 'Get card assignees'},
            'PUT /api/cards/:id/assignees': {'permission': 'card.update', 'description': 'Set card assignees'},
            'POST /api/cards/batch/archive': {'permission': 'card.archive', 'description': 'Batch archive cards'},
            'POST /api/cards/batch/unarchive': {'permission': 'card.archive', 'description': 'Batch unarchive cards'},
            'POST /api/schedules': {'permission': 'schedule.create', 'description': 'Create scheduled card'},
            'GET /api/schedules/:id': {'permission': 'schedule.view', 'description': 'View schedule details'},
            'PUT /api/schedules/:id': {'permission': 'schedule.edit', 'description': 'Update schedule'},
            'DELETE /api/schedules/:id': {'permission': 'schedule.delete', 'description': 'Delete schedule'},
            'POST /api/schedules/regenerate/preview': {'permission': 'system.admin', 'description': 'Preview manual scheduled card regeneration'},
            'POST /api/schedules/regenerate': {'permission': 'system.admin', 'description': 'Manually generate scheduled cards for a date range'},
            'GET /api/settings/schema': {'permission': 'setting.view', 'description': 'View settings schema'},
            'GET /api/settings/:key': {'permission': 'setting.view', 'description': 'View setting'},
            'PUT /api/settings/:key': {'permission': 'setting.edit', 'description': 'Update setting'},
            'GET /api/settings/backup/config': {'permission': 'setting.view', 'description': 'View backup config'},
            'PUT /api/settings/backup/config': {'permission': 'setting.edit', 'description': 'Update backup config'},
            'GET /api/settings/backup/status': {'permission': 'setting.view', 'description': 'View backup status'},
            'GET /api/settings/housekeeping/status': {'permission': 'setting.view', 'description': 'View housekeeping status'},
            'PUT /api/settings/housekeeping/config': {'permission': 'setting.edit', 'description': 'Update housekeeping config'},
            'GET /api/settings/card-scheduler/status': {'permission': 'setting.view', 'description': 'View scheduler status'},
            'PUT /api/settings/card-scheduler/config': {'permission': 'setting.edit', 'description': 'Update scheduler config'},
            'GET /api/database/backup': {'permission': 'admin.database', 'description': 'Download database backup'},
            'POST /api/database/backup/manual': {'permission': 'admin.database', 'description': 'Create manual backup'},
            'POST /api/database/restore': {'permission': 'admin.database', 'description': 'Restore database'},
            'GET /api/database/backups/list': {'permission': 'admin.database', 'description': 'List all backups'},
            'POST /api/database/backups/restore/:filename': {'permission': 'admin.database', 'description': 'Restore specific backup'},
            'DELETE /api/database/backups/delete/:filename': {'permission': 'admin.database', 'description': 'Delete backup'},
            'POST /api/database/backups/delete-multiple': {'permission': 'admin.database', 'description': 'Delete multiple backups'},
            'DELETE /api/database': {'permission': 'admin.database', 'description': 'Reset database'},
            'GET /api/admin/test-user': {'permission': 'user.manage or user.role', 'description': 'View known test user status'},
            'DELETE /api/admin/test-user': {'permission': 'user.manage', 'description': 'Remove known test user'},
            'GET /api/users': {'permission': 'user.manage', 'description': 'List all users'},
            'GET /api/users/:id': {'permission': 'user.manage', 'description': 'Get user details'},
            'PATCH /api/users/:id': {'permission': 'user.manage', 'description': 'Update user'},
            'DELETE /api/users/:id': {'permission': 'user.manage', 'description': 'Delete user'},
            'PATCH /api/users/:id/active': {'permission': 'user.manage', 'description': 'Toggle user active status'},
            'POST /api/users/:id/roles': {'permission': 'user.role', 'description': 'Assign user role'},
            'DELETE /api/users/:id/roles/:role_id': {'permission': 'user.role', 'description': 'Remove user role'},
            'PUT /api/users/me/profile-colour': {'mode': 'authenticated', 'description': 'Update current user avatar/profile colour'},
            'GET /api/roles': {'permission': 'role.manage', 'description': 'List all roles'},
            'POST /api/roles': {'permission': 'role.manage', 'description': 'Create role'},
            'GET /api/roles/:id': {'permission': 'role.manage', 'description': 'Get role details'},
            'PATCH /api/roles/:id': {'permission': 'role.manage', 'description': 'Update role'},
            'DELETE /api/roles/:id': {'permission': 'role.manage', 'description': 'Delete role'},
            'GET /api/roles/permission-model': {'mode': 'public', 'description': 'Get permission model (public)'},
            'GET /api/themes': {'permission': 'theme.view', 'description': 'List themes'},
            'POST /api/themes': {'permission': 'theme.create', 'description': 'Create theme'},
            'GET /api/themes/:id': {'permission': 'theme.view', 'description': 'Get theme details'},
            'PUT /api/themes/:id': {'permission': 'theme.edit', 'description': 'Update theme'},
            'PUT /api/themes/:id/rename': {'permission': 'theme.edit', 'description': 'Rename theme'},
            'DELETE /api/themes/:id': {'permission': 'theme.delete', 'description': 'Delete theme'},
            'POST /api/themes/:id/promote-global': {'permission': 'branding.edit', 'description': 'Promote theme to global visibility'},
            'POST /api/themes/:id/demote-global': {'permission': 'branding.edit', 'description': 'Demote theme from global visibility'},
            'GET /api/settings/default-theme': {'mode': 'authenticated', 'description': 'Get instance default theme'},
            'PUT /api/settings/default-theme': {'permission': 'branding.edit', 'description': 'Set instance default theme'},
            'GET /api/stats': {'permission': 'board.view', 'description': 'View statistics'},
            'GET /api/scheduler/health': {'permission': 'setting.view', 'description': 'View scheduler health'},
            'GET /api/broadcast-status': {'permission': 'monitoring.system', 'description': 'View broadcast status'},
        }

        return jsonify({
            'success': True,
            'endpoint_permissions': endpoint_mapping,
            'user_permissions': sorted(list(user_perms)),
            'user_context': {
              'has_board_assignment': has_board_assignment,
              'has_board_edit_assignment': has_board_edit_assignment,
            },
            'board_id': board_id
        })
    except Exception as e:
        logger.error(f"Error getting permissions mapping: {e}")
        return jsonify({
            'success': False,
            'message': f'Failed to get permissions mapping: {str(e)}'
        }), 500
    finally:
        db.close()


@health_bp.route("/api/broadcast-status")
@require_permission('monitoring.system')
def get_broadcast_status():
    """Get WebSocket broadcast error counts per room (debugging).
    ---
    tags:
      - Health
    security:
      - SessionAuth: []
    responses:
      200:
        description: Broadcast failure counts per room
      403:
        description: Insufficient permissions
    """
    with BROADCAST_FAILURES_LOCK:
        failures_copy = dict(BROADCAST_FAILURES)
        total_rooms = len(BROADCAST_FAILURES)

    return jsonify({
        "success": True,
        "broadcast_failures": failures_copy,
        "total_failure_rooms": total_rooms
    })


@health_bp.route("/api/scheduler/health")
@require_permission('setting.view')
def get_scheduler_health():
    """Get health status of all background schedulers.
    ---
    tags:
      - Health
    security:
      - SessionAuth: []
    responses:
      200:
        description: Scheduler health details for all background threads
      403:
        description: Insufficient permissions
    """
    return jsonify(_collect_scheduler_health()), 200


@health_bp.route("/api/server-health")
def server_health():
    """Public server health check (no authentication required).
    ---
    tags:
      - Health
    responses:
      200:
        description: Boolean health status covering DB and all scheduler threads
        schema:
          type: object
          properties:
            healthy:
              type: boolean
    """
    return jsonify({"healthy": _evaluate_server_health()}), 200


def _healthcheck_allowed_source_ips():
    """Return the configured set of source IPs allowed for readiness checks."""
    allowed_raw = os.getenv('HEALTHCHECK_ALLOWED_SOURCE_IP', '127.0.0.1')
    allowed_ips = {ip.strip() for ip in allowed_raw.split(',') if ip.strip()}
    if '127.0.0.1' in allowed_ips:
        allowed_ips.add('::1')
    return allowed_ips


def _is_internal_readiness_request_authorized():
    """Validate token plus source IP for the internal readiness endpoint."""
    expected_token = os.getenv('HEALTHCHECK_TOKEN', '').strip()
    provided_token = request.headers.get('X-Health-Token', '').strip()

    if not expected_token:
        logger.warning('HEALTHCHECK_TOKEN is not set; readiness request denied')
        return False

    if not provided_token or not secrets.compare_digest(provided_token, expected_token):
        return False

    remote_addr = (request.remote_addr or '').strip()
    return remote_addr in _healthcheck_allowed_source_ips()


@health_bp.route("/api/health/live")
def health_live():
    """Public liveness endpoint — confirms the server process is running.
    ---
    tags:
      - Health
    responses:
      200:
        description: Server is alive
        schema:
          type: object
          properties:
            ok:
              type: boolean
    """
    return jsonify({"ok": True}), 200


@health_bp.route("/api/health/ready")
def health_ready():
    """Internal readiness endpoint for compose health checks (token + IP restricted).
    ---
    tags:
      - Health
    parameters:
      - name: X-Health-Token
        in: header
        required: true
        type: string
        description: HEALTHCHECK_TOKEN value configured in the environment
    responses:
      200:
        description: Server and database are ready
      404:
        description: Unauthorised (invalid token or source IP)
      503:
        description: Database not reachable
    """
    if not _is_internal_readiness_request_authorized():
        return jsonify({"ok": False}), 404

    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return jsonify({"ok": True}), 200
    except Exception as e:
        logger.warning(f"Readiness check failed: {e}")
        return jsonify({"ok": False}), 503
    finally:
        db.close()


@health_bp.route("/api/test")
@require_authentication
def test_db():
    """Legacy database connectivity test.
    ---
    tags:
      - Health
    security:
      - SessionAuth: []
    responses:
      200:
        description: Database is reachable
      500:
        description: Database not reachable
    """
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return jsonify({"success": True, "message": "Connected to database"})
    except Exception as e:
        logger.error(f"Legacy health check failed: {e}")
        return jsonify({"success": False, "message": "Database not reachable"}), 500
    finally:
        db.close()


@health_bp.route("/api/stats")
@require_permission('board.view')
def get_stats():
    """Get board and card statistics scoped to the current user.
    ---
    tags:
      - Health
    security:
      - SessionAuth: []
    responses:
      200:
        description: Board, column, card and checklist item counts
      403:
        description: Insufficient permissions
      500:
        description: Server error
    """
    db = SessionLocal()
    try:
        user_id = g.user.id

        boards_count = get_user_scoped_query(db, Board, user_id).count()
        columns_count = get_user_scoped_query(db, BoardColumn, user_id).count()
        cards_count = get_user_scoped_query(db, Card, user_id).count()
        cards_archived_count = get_user_scoped_query(db, Card, user_id).filter(Card.archived.is_(True)).count()
        checklist_items_total = get_user_scoped_query(db, ChecklistItem, user_id).count()
        checklist_items_checked = get_user_scoped_query(db, ChecklistItem, user_id).filter(ChecklistItem.checked.is_(True)).count()
        checklist_items_unchecked = get_user_scoped_query(db, ChecklistItem, user_id).filter(ChecklistItem.checked.is_(False)).count()

        return jsonify(
            {
                "success": True,
                "boards_count": boards_count,
                "columns_count": columns_count,
                "cards_count": cards_count,
                "cards_archived_count": cards_archived_count,
                "checklist_items_total": checklist_items_total,
                "checklist_items_checked": checklist_items_checked,
                "checklist_items_unchecked": checklist_items_unchecked,
            }
        )
    except Exception as e:
        logger.error(f"Error getting stats: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        db.close()
