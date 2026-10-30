"""
Passkey (WebAuthn) endpoints.

Passkeys are an alternative way to sign in, alongside the password. They are
off unless WEBAUTHN_RP_ID is set (see webauthn_settings.py and the README).

Registration and sign-in are each two requests: the server issues options with
a random challenge, the browser asks the authenticator, then the server
verifies the response. Challenges are kept in Redis, are single use and expire
after CEREMONY_TTL_SECONDS.
"""

import json
import logging
import os
import re
import secrets

from flask import Blueprint, request, session, g
from sqlalchemy.sql import func
from webauthn import (
    generate_registration_options,
    verify_registration_response,
    generate_authentication_options,
    verify_authentication_response,
    base64url_to_bytes,
)
from webauthn.helpers import (
    bytes_to_base64url,
    options_to_json_dict,
    parse_authentication_credential_json,
    parse_registration_credential_json,
)
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from auth import build_login_user_data, start_user_session, verify_password
from auth_rate_limit import (
    account_key,
    passkey_start_block_seconds,
    password_block_seconds,
    record_password_failure,
    too_many_attempts_response,
)
from database import SessionLocal
from datetime_helpers import serialize_datetime
from models import User, WebAuthnCredential
from utils import (
    create_error_response,
    create_success_response,
    require_authentication,
    require_permission,
)
from webauthn_settings import read_webauthn_settings

logger = logging.getLogger(__name__)

passkey_bp = Blueprint('passkeys', __name__, url_prefix='/api')

# Raises ValueError at startup if the passkey settings are invalid.
WEBAUTHN_SETTINGS = read_webauthn_settings()

CEREMONY_TIMEOUT_MS = 120_000
CEREMONY_TTL_SECONDS = 300
MAX_PASSKEYS_PER_USER = 20
MAX_PASSKEY_NAME_LENGTH = 100
DEFAULT_PASSKEY_NAME = 'Passkey'
# Registration responses carry an attestation object; a few KB is typical.
MAX_CEREMONY_BODY_BYTES = 64 * 1024

CEREMONY_KEY_PREFIX = 'aft:webauthn:'
# clientDataJSON is a small JSON object; challenges are 64 random bytes in base64url.
MAX_CLIENT_DATA_LENGTH = 4096
_CHALLENGE_PATTERN = re.compile(r'[A-Za-z0-9_-]{16,256}')

_redis_client = None


def _get_redis():
    """Return a shared Redis client for ceremony state."""
    global _redis_client
    if _redis_client is None:
        import redis
        _redis_client = redis.from_url(os.environ['REDIS_URL'])
    return _redis_client


def _store_ceremony(purpose, challenge, state=None):
    """Store ceremony state in Redis, keyed by its challenge and bound to this browser session.

    Keying by challenge lets several ceremonies run at once in one session, such
    as two login tabs, or passkey autofill plus the sign-in button.
    """
    binding = session.get('webauthn_binding')
    if not isinstance(binding, str):
        binding = secrets.token_urlsafe(32)
        session['webauthn_binding'] = binding
    challenge_b64 = bytes_to_base64url(challenge)
    payload = dict(state or {}, challenge=challenge_b64, binding=binding)
    _get_redis().set(
        f"{CEREMONY_KEY_PREFIX}{purpose}:{challenge_b64}",
        json.dumps(payload),
        ex=CEREMONY_TTL_SECONDS,
    )


def _take_ceremony(purpose, credential):
    """Return and delete the ceremony state this credential answers.

    The challenge is read from the credential's clientDataJSON; the signature
    check later proves it was really signed. Returns None if the challenge is
    unknown, expired, already used, or was issued to another browser session.
    """
    try:
        client_data_b64 = credential['response']['clientDataJSON']
        if not isinstance(client_data_b64, str) or len(client_data_b64) > MAX_CLIENT_DATA_LENGTH:
            return None
        challenge = json.loads(base64url_to_bytes(client_data_b64)).get('challenge')
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    if not isinstance(challenge, str) or not _CHALLENGE_PATTERN.fullmatch(challenge):
        return None

    raw = _get_redis().getdel(f"{CEREMONY_KEY_PREFIX}{purpose}:{challenge}")
    if not raw:
        return None
    state = json.loads(raw)
    binding = session.get('webauthn_binding')
    if not isinstance(binding, str) or not secrets.compare_digest(state.get('binding', ''), binding):
        return None
    return state


def _disabled_response():
    return create_error_response("Passkeys are not enabled on this server", 404)


def _read_credential_body():
    """Return (data, credential, error_response) for a ceremony verify request."""
    if request.content_length and request.content_length > MAX_CEREMONY_BODY_BYTES:
        return None, None, create_error_response("Request too large", 413)
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get('credential'), dict):
        return None, None, create_error_response("credential object is required", 400)
    return data, data['credential'], None


def _validate_passkey_name(raw_name, default=None):
    """Return (name, error_message) for a user-supplied passkey name."""
    if raw_name is None and default is not None:
        return default, None
    if not isinstance(raw_name, str):
        return None, "name must be a string"
    name = raw_name.strip()
    if not name:
        return None, "name cannot be empty"
    if len(name) > MAX_PASSKEY_NAME_LENGTH:
        return None, f"name exceeds maximum length of {MAX_PASSKEY_NAME_LENGTH} characters"
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in name):
        return None, "name contains control characters"
    return name, None


def _serialize_passkey(credential):
    return {
        'id': credential.id,
        'name': credential.name,
        'synced': bool(credential.backed_up),
        'created_at': serialize_datetime(credential.created_at),
        'last_used_at': serialize_datetime(credential.last_used_at),
    }


@passkey_bp.route('/auth/passkeys/status', methods=['GET'])
def passkey_status():
    """
    Report whether passkeys are enabled on this server.
    ---
    tags:
      - Authentication
    responses:
      200:
        description: Passkey availability
        schema:
          type: object
          properties:
            success:
              type: boolean
            enabled:
              type: boolean
    """
    return create_success_response(data={'enabled': WEBAUTHN_SETTINGS is not None})


@passkey_bp.route('/auth/passkeys/register/options', methods=['POST'])
@require_authentication
def passkey_register_options():
    """
    Start adding a passkey to the current account.
    ---
    tags:
      - Authentication
    security:
      - session: []
    description: >
      Requires the current password. Returns options for
      navigator.credentials.create(), with binary values base64url-encoded.
      Finish with POST /api/auth/passkeys/register/verify within 5 minutes.
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - password
          properties:
            password:
              type: string
              format: password
    responses:
      200:
        description: Registration options
        schema:
          type: object
          properties:
            success:
              type: boolean
            options:
              type: object
      400:
        description: >
          Missing or incorrect password, or passkey limit reached. A wrong
          password is 400, not 401, because the session is still valid.
      401:
        description: Not logged in
      404:
        description: Passkeys are not enabled
      429:
        description: Too many failed attempts. See the Retry-After header.
      500:
        description: Server error
    """
    if not WEBAUTHN_SETTINGS:
        return _disabled_response()

    data = request.get_json(silent=True)
    password = data.get('password') if isinstance(data, dict) else None
    if not isinstance(password, str) or not password:
        return create_error_response("Current password is required", 400)

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == g.user.id).first()
        if not user or not user.password_hash:
            return create_error_response("This account cannot add passkeys", 400)
        account = account_key(user)
        retry_after = password_block_seconds(account)
        if retry_after:
            return too_many_attempts_response(retry_after)
        if not verify_password(password, user.password_hash):
            record_password_failure(account)
            return create_error_response("Current password is incorrect", 400)

        existing = db.query(WebAuthnCredential).filter(
            WebAuthnCredential.user_id == user.id
        ).all()
        if len(existing) >= MAX_PASSKEYS_PER_USER:
            return create_error_response(
                f"You can register at most {MAX_PASSKEYS_PER_USER} passkeys", 400
            )

        if not user.webauthn_user_handle:
            user.webauthn_user_handle = bytes_to_base64url(secrets.token_bytes(32))
            db.commit()

        account_name = user.username or user.email
        options = generate_registration_options(
            rp_id=WEBAUTHN_SETTINGS.rp_id,
            rp_name=WEBAUTHN_SETTINGS.rp_name,
            user_id=base64url_to_bytes(user.webauthn_user_handle),
            user_name=account_name,
            user_display_name=user.display_name or account_name,
            timeout=CEREMONY_TIMEOUT_MS,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
            exclude_credentials=[
                PublicKeyCredentialDescriptor(id=base64url_to_bytes(c.credential_id))
                for c in existing
            ],
        )
        _store_ceremony('register', options.challenge, {'user_id': user.id})
        return create_success_response(data={'options': options_to_json_dict(options)})
    except Exception as e:
        logger.error(f"Passkey registration options error: {e}")
        return create_error_response("Could not start passkey registration", 500)
    finally:
        db.close()


@passkey_bp.route('/auth/passkeys/register/verify', methods=['POST'])
@require_authentication
def passkey_register_verify():
    """
    Finish adding a passkey to the current account.
    ---
    tags:
      - Authentication
    security:
      - session: []
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - credential
          properties:
            credential:
              type: object
              description: navigator.credentials.create() result as JSON (base64url values)
            name:
              type: string
              maxLength: 100
              description: Label for the passkey, such as the device it is on
    responses:
      201:
        description: Passkey added
        schema:
          type: object
          properties:
            success:
              type: boolean
            passkey:
              type: object
      400:
        description: Invalid input, expired request, or verification failed
      401:
        description: Not logged in
      404:
        description: Passkeys are not enabled
      409:
        description: Passkey is already registered
      413:
        description: Request too large
      500:
        description: Server error
    """
    if not WEBAUTHN_SETTINGS:
        return _disabled_response()

    data, credential, error = _read_credential_body()
    if error:
        return error

    name, name_error = _validate_passkey_name(data.get('name'), default=DEFAULT_PASSKEY_NAME)
    if name_error:
        return create_error_response(name_error, 400)

    try:
        state = _take_ceremony('register', credential)
    except Exception as e:
        logger.error(f"Passkey registration state error: {e}")
        return create_error_response("Could not add passkey", 500)
    if not state or state.get('user_id') != g.user.id:
        return create_error_response("Passkey registration has expired. Please try again.", 400)

    try:
        parsed = parse_registration_credential_json(credential)
        verification = verify_registration_response(
            credential=parsed,
            expected_challenge=base64url_to_bytes(state['challenge']),
            expected_rp_id=WEBAUTHN_SETTINGS.rp_id,
            expected_origin=list(WEBAUTHN_SETTINGS.origins),
            require_user_verification=True,
        )
    except (WebAuthnException, ValueError, TypeError, KeyError) as e:
        logger.info(f"Passkey registration rejected for user_id={g.user.id}: {e}")
        return create_error_response("Passkey could not be verified", 400)

    transports = [t.value for t in (parsed.response.transports or [])]
    db = SessionLocal()
    try:
        credential_id = bytes_to_base64url(verification.credential_id)
        if db.query(WebAuthnCredential.id).filter(
            WebAuthnCredential.credential_id == credential_id
        ).first():
            return create_error_response("This passkey is already registered", 409)

        count = db.query(WebAuthnCredential).filter(
            WebAuthnCredential.user_id == g.user.id
        ).count()
        if count >= MAX_PASSKEYS_PER_USER:
            return create_error_response(
                f"You can register at most {MAX_PASSKEYS_PER_USER} passkeys", 400
            )

        stored = WebAuthnCredential(
            user_id=g.user.id,
            credential_id=credential_id,
            public_key=bytes_to_base64url(verification.credential_public_key),
            sign_count=verification.sign_count,
            transports=json.dumps(transports)[:255],
            aaguid=verification.aaguid,
            backed_up=verification.credential_backed_up,
            name=name,
        )
        db.add(stored)
        db.commit()
        db.refresh(stored)
        logger.info(f"Passkey added for user_id={g.user.id} (passkey_id={stored.id})")
        return create_success_response(
            data={'passkey': _serialize_passkey(stored)},
            message="Passkey added",
            status_code=201,
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Passkey registration save error: {e}")
        return create_error_response("Could not add passkey", 500)
    finally:
        db.close()


@passkey_bp.route('/auth/passkeys/login/options', methods=['POST'])
def passkey_login_options():
    """
    Start signing in with a passkey.
    ---
    tags:
      - Authentication
    description: >
      Returns options for navigator.credentials.get(). No username is needed:
      the browser offers the passkeys it holds for this site. Finish with
      POST /api/auth/passkeys/login/verify within 5 minutes.
    responses:
      200:
        description: Sign-in options
        schema:
          type: object
          properties:
            success:
              type: boolean
            options:
              type: object
      404:
        description: Passkeys are not enabled
      429:
        description: Too many requests. See the Retry-After header.
      500:
        description: Server error
    """
    if not WEBAUTHN_SETTINGS:
        return _disabled_response()

    retry_after = passkey_start_block_seconds()
    if retry_after:
        return too_many_attempts_response(retry_after)

    try:
        options = generate_authentication_options(
            rp_id=WEBAUTHN_SETTINGS.rp_id,
            timeout=CEREMONY_TIMEOUT_MS,
            user_verification=UserVerificationRequirement.REQUIRED,
        )
        _store_ceremony('login', options.challenge)
        return create_success_response(data={'options': options_to_json_dict(options)})
    except Exception as e:
        logger.error(f"Passkey sign-in options error: {e}")
        return create_error_response("Could not start passkey sign-in", 500)


@passkey_bp.route('/auth/passkeys/login/verify', methods=['POST'])
def passkey_login_verify():
    """
    Finish signing in with a passkey.
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
            - credential
          properties:
            credential:
              type: object
              description: navigator.credentials.get() result as JSON (base64url values)
            remember_me:
              type: boolean
              default: false
    responses:
      200:
        description: Login successful. Same response as POST /api/auth/login.
      400:
        description: Invalid input or expired request
      401:
        description: Passkey not recognised or verification failed
      403:
        description: Account disabled or pending approval
      404:
        description: Passkeys are not enabled
      413:
        description: Request too large
      500:
        description: Server error
    """
    if not WEBAUTHN_SETTINGS:
        return _disabled_response()

    data, credential, error = _read_credential_body()
    if error:
        return error
    remember_me = data.get('remember_me', False) is True

    try:
        state = _take_ceremony('login', credential)
    except Exception as e:
        logger.error(f"Passkey sign-in state error: {e}")
        return create_error_response("An error occurred during login", 500)
    if not state:
        return create_error_response("Passkey sign-in has expired. Please try again.", 400)

    failed = create_error_response("Passkey sign-in failed", 401)
    db = SessionLocal()
    try:
        try:
            parsed = parse_authentication_credential_json(credential)
        except (WebAuthnException, ValueError, TypeError, KeyError):
            return failed

        stored = db.query(WebAuthnCredential).filter(
            WebAuthnCredential.credential_id == bytes_to_base64url(parsed.raw_id)
        ).first()
        if not stored:
            return failed
        user = stored.user

        user_handle = parsed.response.user_handle
        if not user_handle or bytes_to_base64url(user_handle) != user.webauthn_user_handle:
            return failed

        try:
            verification = verify_authentication_response(
                credential=parsed,
                expected_challenge=base64url_to_bytes(state['challenge']),
                expected_rp_id=WEBAUTHN_SETTINGS.rp_id,
                expected_origin=list(WEBAUTHN_SETTINGS.origins),
                credential_public_key=base64url_to_bytes(stored.public_key),
                credential_current_sign_count=stored.sign_count,
                require_user_verification=True,
            )
        except (WebAuthnException, ValueError, TypeError, KeyError) as e:
            logger.info(f"Passkey sign-in rejected for passkey_id={stored.id}: {e}")
            return failed

        if not user.is_active:
            return create_error_response("Account is disabled", 403)
        if not user.is_approved:
            return create_error_response(
                "Your account is pending administrator approval. You will be notified when approved.",
                403
            )

        stored.sign_count = verification.new_sign_count
        stored.backed_up = verification.credential_backed_up
        stored.last_used_at = func.now()
        user.last_login_at = func.now()
        db.commit()

        start_user_session(user, remember_me, passkey_id=stored.id)
        user_data = build_login_user_data(db, user)
        logger.info(f"User logged in with passkey: {user.email} (ID: {user.id})")
        return create_success_response(data={'user': user_data}, message="Login successful")
    except Exception as e:
        db.rollback()
        logger.error(f"Passkey sign-in error: {e}")
        return create_error_response("An error occurred during login", 500)
    finally:
        db.close()


@passkey_bp.route('/auth/passkeys', methods=['GET'])
@require_authentication
def list_own_passkeys():
    """
    List the current user's passkeys.
    ---
    tags:
      - Authentication
    security:
      - session: []
    responses:
      200:
        description: Passkeys, newest first
        schema:
          type: object
          properties:
            success:
              type: boolean
            passkeys:
              type: array
              items:
                type: object
                properties:
                  id:
                    type: integer
                  name:
                    type: string
                  synced:
                    type: boolean
                    description: The passkey is backed up and syncs across devices
                  created_at:
                    type: string
                  last_used_at:
                    type: string
      401:
        description: Not logged in
    """
    db = SessionLocal()
    try:
        passkeys = db.query(WebAuthnCredential).filter(
            WebAuthnCredential.user_id == g.user.id
        ).order_by(WebAuthnCredential.id.desc()).all()
        return create_success_response(
            data={'passkeys': [_serialize_passkey(p) for p in passkeys]}
        )
    finally:
        db.close()


@passkey_bp.route('/auth/passkeys/<int:passkey_id>', methods=['PATCH'])
@require_authentication
def rename_own_passkey(passkey_id):
    """
    Rename one of the current user's passkeys.
    ---
    tags:
      - Authentication
    security:
      - session: []
    parameters:
      - name: passkey_id
        in: path
        type: integer
        required: true
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
              maxLength: 100
    responses:
      200:
        description: Passkey renamed
      400:
        description: Invalid name
      401:
        description: Not logged in
      404:
        description: Passkey not found
    """
    data = request.get_json(silent=True)
    name, name_error = _validate_passkey_name(
        data.get('name') if isinstance(data, dict) else None
    )
    if name_error:
        return create_error_response(name_error, 400)

    db = SessionLocal()
    try:
        passkey = db.query(WebAuthnCredential).filter(
            WebAuthnCredential.id == passkey_id,
            WebAuthnCredential.user_id == g.user.id
        ).first()
        if not passkey:
            return create_error_response("Passkey not found", 404)
        passkey.name = name
        db.commit()
        return create_success_response(
            data={'passkey': _serialize_passkey(passkey)}, message="Passkey renamed"
        )
    finally:
        db.close()


@passkey_bp.route('/auth/passkeys/<int:passkey_id>', methods=['DELETE'])
@require_authentication
def delete_own_passkey(passkey_id):
    """
    Remove one of the current user's passkeys.
    ---
    tags:
      - Authentication
    security:
      - session: []
    description: >
      Sessions that were signed in with this passkey end. signed_out is true
      when that includes the current session.
    parameters:
      - name: passkey_id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: Passkey removed
        schema:
          type: object
          properties:
            success:
              type: boolean
            signed_out:
              type: boolean
      401:
        description: Not logged in
      404:
        description: Passkey not found
    """
    db = SessionLocal()
    try:
        passkey = db.query(WebAuthnCredential).filter(
            WebAuthnCredential.id == passkey_id,
            WebAuthnCredential.user_id == g.user.id
        ).first()
        if not passkey:
            return create_error_response("Passkey not found", 404)
        db.delete(passkey)
        db.commit()
        logger.info(f"Passkey removed by user_id={g.user.id} (passkey_id={passkey_id})")

        signed_out = session.get('passkey_id') == passkey_id
        if signed_out:
            session.clear()
        return create_success_response(
            data={'signed_out': signed_out}, message="Passkey removed"
        )
    finally:
        db.close()


@passkey_bp.route('/users/<int:user_id>/passkeys', methods=['GET'])
@require_permission('user.manage')
def admin_list_user_passkeys(user_id):
    """
    List a user's passkeys (admin).
    ---
    tags:
      - User Management
    security:
      - session: []
    parameters:
      - name: user_id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: The user's passkeys, newest first
      403:
        description: Forbidden - requires user.manage permission
      404:
        description: User not found
    """
    db = SessionLocal()
    try:
        if not db.query(User.id).filter(User.id == user_id).first():
            return create_error_response("User not found", 404)
        passkeys = db.query(WebAuthnCredential).filter(
            WebAuthnCredential.user_id == user_id
        ).order_by(WebAuthnCredential.id.desc()).all()
        return create_success_response(
            data={'passkeys': [_serialize_passkey(p) for p in passkeys]}
        )
    finally:
        db.close()


@passkey_bp.route('/users/<int:user_id>/passkeys', methods=['DELETE'])
@require_permission('user.manage')
def admin_revoke_user_passkeys(user_id):
    """
    Remove all of a user's passkeys (admin), for example after a lost device.
    ---
    tags:
      - User Management
    security:
      - session: []
    description: >
      The user's sessions that were signed in with a passkey end. Password
      sessions are not affected; reset the password to end those too.
    parameters:
      - name: user_id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: Passkeys removed
        schema:
          type: object
          properties:
            success:
              type: boolean
            removed:
              type: integer
      403:
        description: Forbidden - requires user.manage permission
      404:
        description: User not found
    """
    db = SessionLocal()
    try:
        if not db.query(User.id).filter(User.id == user_id).first():
            return create_error_response("User not found", 404)
        removed = db.query(WebAuthnCredential).filter(
            WebAuthnCredential.user_id == user_id
        ).delete(synchronize_session=False)
        db.commit()
        logger.info(f"Removed {removed} passkey(s) for user_id={user_id} by admin {g.user.id}")
        return create_success_response(
            data={'removed': removed}, message=f"Removed {removed} passkey(s)"
        )
    finally:
        db.close()
