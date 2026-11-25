"""Host restart and shut down endpoints (#726). See host_power.py.

Only global administrators can use them, as for admin password resets, and
they answer 404 unless the feature is turned on and the request directory is
mounted. Asking needs the administrator's password, which shares the
per-account sign-in rate limit.
"""

import logging

from flask import Blueprint, g, request

import host_power
from auth import verify_password
from auth_rate_limit import (
    account_key,
    get_client_ip,
    password_block_seconds,
    record_password_failure,
    too_many_attempts_response,
)
from database import SessionLocal
from models import Role, User, UserRole
from notification_utils import create_notification
from utils import create_error_response, create_success_response, require_authentication

logger = logging.getLogger(__name__)

host_power_bp = Blueprint('host_power', __name__, url_prefix='/api/system/host')

NOT_AVAILABLE = "Host power control is not enabled"
MAX_PASSWORD_LENGTH = 1024


def _is_global_administrator(db, user_id):
    return db.query(UserRole.id).join(Role).filter(
        UserRole.user_id == user_id,
        UserRole.board_id.is_(None),
        Role.name == 'administrator'
    ).first() is not None


def _check_access(db):
    """Return an error response, or None if the caller may use these routes."""
    if not _is_global_administrator(db, g.user.id):
        return create_error_response("Only administrators can restart or shut down the host", 403)
    if not host_power.is_enabled():
        return create_error_response(NOT_AVAILABLE, 404)
    return None


def _status():
    return {
        'enabled': True,
        'actions': list(host_power.ACTIONS),
        'pending': host_power.pending_request(),
        'requested': host_power.requested_action(),
    }


def _notify_admins(subject, message):
    create_notification(
        subject=subject,
        message=message,
        action_title='Instance Settings',
        action_url='/settings.html#instance',
        for_admins=True,
    )


@host_power_bp.route('', methods=['GET'])
@require_authentication
def get_host_power_status():
    """
    Host restart and shut down status.
    ---
    tags:
      - System
    security:
      - session: []
    description: >
      Only for hosts dedicated to AFT. Off unless HOST_POWER_CONTROL is set
      and the request directory is mounted and writable.
    responses:
      200:
        description: Host power control is enabled
        schema:
          $ref: '#/definitions/HostPowerStatus'
      401:
        description: Not logged in
      403:
        description: Not a global administrator
      404:
        description: Host power control is not enabled
    definitions:
      HostPowerStatus:
        type: object
        properties:
          success:
            type: boolean
          enabled:
            type: boolean
          actions:
            type: array
            items:
              type: string
              enum: [reboot, poweroff]
          pending:
            type: object
            x-nullable: true
            description: A request held until a backup or restore finishes
            properties:
              action:
                type: string
                enum: [reboot, poweroff]
              user_id:
                type: integer
              username:
                type: string
              client_ip:
                type: string
              requested_at:
                type: string
              expires_at:
                type: string
              waiting_for:
                type: array
                items:
                  type: string
                  enum: [backup, restore, reset]
          requested:
            type: string
            x-nullable: true
            description: >
              An action handed to the host that it hasn't acted on yet. If
              this stays set, the host service isn't running.
    """
    db = SessionLocal()
    try:
        error = _check_access(db)
        if error:
            return error
    finally:
        db.close()
    return create_success_response(data=_status())


def _request(action):
    data = request.get_json(silent=True) or {}
    db = SessionLocal()
    try:
        error = _check_access(db)
        if error:
            return error

        user = db.query(User).filter(User.id == g.user.id).first()
        if not user:
            return create_error_response("Authentication required", 401)

        # Basic auth sent the password with this request already.
        if g.get('auth_method') != 'basic':
            password = data.get('password')
            if not isinstance(password, str) or not password:
                return create_error_response("Current password is required", 400)
            if len(password) > MAX_PASSWORD_LENGTH or not user.password_hash:
                return create_error_response("Current password is incorrect", 400)
            account = account_key(user)
            retry_after = password_block_seconds(account)
            if retry_after:
                return too_many_attempts_response(retry_after)
            if not verify_password(password, user.password_hash):
                record_password_failure(account)
                # 400, not 401: the session is still valid.
                return create_error_response("Current password is incorrect", 400)
    finally:
        db.close()

    client_ip = get_client_ip()
    try:
        held, waiting_for = host_power.request_action(action, g.user, client_ip, _notify_admins)
    except host_power.RequestRefused as refused:
        return create_error_response(refused.message, 409)
    except OSError as error:
        logger.error("Couldn't write the host power request: %s", error)
        return create_error_response("The request couldn't be handed to the host", 500)

    verb = host_power.ACTION_NAMES[action]
    if held:
        message = f"{host_power.describe_work(waiting_for)} The host will {verb} when it finishes."
        status_code = 202
    else:
        message = f"The host will {verb} now. Everyone will be disconnected."
        status_code = 200
    return create_success_response(
        data=dict(_status(), held=held), message=message, status_code=status_code
    )


_REQUEST_DOC = """
    {summary}
    ---
    tags:
      - System
    security:
      - session: []
    description: >
      Needs the global administrator role and the current password, which
      shares the per-account sign-in rate limit. While a backup or restore
      runs, the request is held until it finishes (202).
    parameters:
      - name: body
        in: body
        required: false
        schema:
          type: object
          properties:
            password:
              type: string
              description: Current password. Not needed with HTTP Basic auth.
    responses:
      200:
        description: Handed to the host
        schema:
          $ref: '#/definitions/HostPowerStatus'
      202:
        description: Held until a running backup or restore finishes
        schema:
          $ref: '#/definitions/HostPowerStatus'
      400:
        description: >
          Missing or incorrect password. A wrong password is 400, not 401,
          because the session is still valid.
      401:
        description: Not logged in
      403:
        description: Not a global administrator
      404:
        description: Host power control is not enabled
      409:
        description: A request is already waiting
      429:
        description: Too many failed password attempts. See the Retry-After header.
"""


@host_power_bp.route('/reboot', methods=['POST'])
@require_authentication
def reboot_host():
    return _request('reboot')


@host_power_bp.route('/poweroff', methods=['POST'])
@require_authentication
def poweroff_host():
    return _request('poweroff')


reboot_host.__doc__ = _REQUEST_DOC.format(summary="Restart the host.")
poweroff_host.__doc__ = _REQUEST_DOC.format(summary="Shut down the host.")


@host_power_bp.route('/pending', methods=['DELETE'])
@require_authentication
def cancel_host_power_request():
    """
    Cancel a waiting host restart or shut down.
    ---
    tags:
      - System
    security:
      - session: []
    description: >
      Cancels a request held for a backup or restore, and a request the host
      hasn't acted on yet.
    responses:
      200:
        description: >
          Cancelled, or nothing was waiting. `cancelled` is the action
          cancelled, or null.
      401:
        description: Not logged in
      403:
        description: Not a global administrator
      404:
        description: Host power control is not enabled
    """
    db = SessionLocal()
    try:
        error = _check_access(db)
        if error:
            return error
    finally:
        db.close()

    client_ip = get_client_ip()
    cancelled = host_power.cancel(g.user, client_ip)
    if cancelled:
        verb = host_power.ACTION_NAMES[cancelled] if cancelled in host_power.ACTIONS else 'request'
        _notify_admins(
            f"Host {verb} cancelled",
            f"{g.user.username} cancelled the host {verb} from {client_ip}.",
        )
        message = f"The host {verb} was cancelled."
    else:
        message = "Nothing was waiting."
    return create_success_response(data=dict(_status(), cancelled=cancelled), message=message)
