"""
Personal API token endpoints (#714).

People manage their own tokens under /api/auth/tokens. Holders of user.manage
can list and revoke anyone's tokens, and create tokens for API-only accounts,
which can't sign in to the web app to make their own.

A request made with an API token can't create tokens, so a leaked token can't
be used to make others that outlive it.
"""

import logging

from flask import Blueprint, g, request

from api_tokens import (
    create_token,
    parse_token_options,
    serialize_token,
)
from auth import verify_password
from auth_rate_limit import (
    account_key,
    password_block_seconds,
    record_password_failure,
    too_many_attempts_response,
)
from database import SessionLocal
from models import ApiToken, User
from utils import (
    create_error_response,
    create_success_response,
    require_authentication,
    require_permission,
)

logger = logging.getLogger(__name__)

api_token_bp = Blueprint('api_tokens', __name__, url_prefix='/api')

TOKEN_AUTH_CANNOT_CREATE = "API tokens can't be used to create API tokens"


def _list_tokens(db, user_id):
    tokens = db.query(ApiToken).filter(
        ApiToken.user_id == user_id
    ).order_by(ApiToken.id.desc()).all()
    return [serialize_token(t) for t in tokens]


def _created_response(api_token, token):
    data = {'token': token, 'api_token': serialize_token(api_token)}
    return create_success_response(
        data=data, message="API token created. Copy it now: it won't be shown again.",
        status_code=201,
    )


@api_token_bp.route('/auth/tokens', methods=['GET'])
@require_authentication
def list_own_tokens():
    """
    List the current user's API tokens.
    ---
    tags:
      - Authentication
    security:
      - session: []
    responses:
      200:
        description: Tokens, newest first. The token values themselves are never returned.
        schema:
          type: object
          properties:
            success:
              type: boolean
            tokens:
              type: array
              items:
                $ref: '#/definitions/ApiToken'
      401:
        description: Not logged in
    definitions:
      ApiToken:
        type: object
        properties:
          id:
            type: integer
          name:
            type: string
          prefix:
            type: string
            description: The first characters of the token, to tell tokens apart
          read_only:
            type: boolean
          created_at:
            type: string
          expires_at:
            type: string
            x-nullable: true
          last_used_at:
            type: string
            x-nullable: true
          expired:
            type: boolean
    """
    db = SessionLocal()
    try:
        return create_success_response(data={'tokens': _list_tokens(db, g.user.id)})
    finally:
        db.close()


@api_token_bp.route('/auth/tokens', methods=['POST'])
@require_authentication
def create_own_token():
    """
    Create an API token for the current user.
    ---
    tags:
      - Authentication
    security:
      - session: []
    description: >
      Scripts and agents send the token as `Authorization: Bearer <token>`. It
      acts as the user, with the same roles, and a read-only token can only make
      GET, HEAD and OPTIONS requests. The token is returned once and can't be
      shown again. A signed-in session must confirm the current password;
      Basic auth has already sent it. Requests made with an API token can't
      create tokens.
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
              maxLength: 100
            read_only:
              type: boolean
              default: false
            expires_in_days:
              type: integer
              minimum: 1
              maximum: 3650
              x-nullable: true
              description: Leave out or null for a token that doesn't expire
            password:
              type: string
              format: password
              description: The current password. Required for a signed-in session.
    responses:
      201:
        description: Token created
        schema:
          type: object
          properties:
            success:
              type: boolean
            token:
              type: string
              description: The token. Shown only this once.
            api_token:
              $ref: '#/definitions/ApiToken'
      400:
        description: >
          Invalid fields, token limit reached, or a missing or incorrect
          password. A wrong password is 400, not 401, because the session is
          still valid.
      401:
        description: Not logged in
      403:
        description: The request was made with an API token
      429:
        description: Too many failed password attempts. See the Retry-After header.
    """
    if g.get('auth_method') == 'token':
        return create_error_response(TOKEN_AUTH_CANNOT_CREATE, 403)

    data = request.get_json(silent=True)
    options, error = parse_token_options(data)
    if error:
        return create_error_response(error, 400)

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == g.user.id).first()
        if not user:
            return create_error_response("Authentication required", 401)

        if g.get('auth_method') != 'basic':
            password = data.get('password')
            if not isinstance(password, str) or not password:
                return create_error_response("Current password is required", 400)
            if not user.password_hash:
                return create_error_response("This account cannot create API tokens", 400)
            account = account_key(user)
            retry_after = password_block_seconds(account)
            if retry_after:
                return too_many_attempts_response(retry_after)
            if not verify_password(password, user.password_hash):
                record_password_failure(account)
                return create_error_response("Current password is incorrect", 400)

        api_token, token, error = create_token(db, user.id, options)
        if error:
            return create_error_response(error, 400)
        logger.info(f"API token created by user_id={user.id} (token_id={api_token.id})")
        return _created_response(api_token, token)
    finally:
        db.close()


@api_token_bp.route('/auth/tokens/<int:token_id>', methods=['DELETE'])
@require_authentication
def revoke_own_token(token_id):
    """
    Revoke one of the current user's API tokens.
    ---
    tags:
      - Authentication
    security:
      - session: []
    description: >
      The token stops working at once. A token can revoke itself, for example
      when a script rotates to a new one.
    parameters:
      - name: token_id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: Token revoked
      401:
        description: Not logged in
      403:
        description: The request was made with a read-only API token
      404:
        description: Token not found
    """
    db = SessionLocal()
    try:
        removed = db.query(ApiToken).filter(
            ApiToken.id == token_id,
            ApiToken.user_id == g.user.id
        ).delete(synchronize_session=False)
        if not removed:
            return create_error_response("API token not found", 404)
        db.commit()
        logger.info(f"API token revoked by user_id={g.user.id} (token_id={token_id})")
        return create_success_response(message="API token revoked")
    finally:
        db.close()


@api_token_bp.route('/users/<int:user_id>/tokens', methods=['GET'])
@require_permission('user.manage')
def admin_list_user_tokens(user_id):
    """
    List a user's API tokens (admin).
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
        description: The user's tokens, newest first
        schema:
          type: object
          properties:
            success:
              type: boolean
            tokens:
              type: array
              items:
                $ref: '#/definitions/ApiToken'
      403:
        description: Forbidden - requires user.manage permission
      404:
        description: User not found
    """
    db = SessionLocal()
    try:
        if not db.query(User.id).filter(User.id == user_id).first():
            return create_error_response("User not found", 404)
        return create_success_response(data={'tokens': _list_tokens(db, user_id)})
    finally:
        db.close()


@api_token_bp.route('/users/<int:user_id>/tokens', methods=['POST'])
@require_permission('user.manage')
def admin_create_user_token(user_id):
    """
    Create an API token for an API-only account (admin).
    ---
    tags:
      - User Management
    security:
      - session: []
    description: >
      API-only accounts can't sign in to the web app, so an admin makes their
      tokens. Other accounts make their own on the Profile page. The token is
      returned once. Requests made with an API token can't create tokens.
    parameters:
      - name: user_id
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
            read_only:
              type: boolean
              default: false
            expires_in_days:
              type: integer
              minimum: 1
              maximum: 3650
              x-nullable: true
    responses:
      201:
        description: Token created
        schema:
          type: object
          properties:
            success:
              type: boolean
            token:
              type: string
            api_token:
              $ref: '#/definitions/ApiToken'
      400:
        description: Invalid fields, the account isn't API-only, or token limit reached
      403:
        description: Forbidden - requires user.manage, or the request was made with an API token
      404:
        description: User not found
    """
    if g.get('auth_method') == 'token':
        return create_error_response(TOKEN_AUTH_CANNOT_CREATE, 403)

    options, error = parse_token_options(request.get_json(silent=True))
    if error:
        return create_error_response(error, 400)

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return create_error_response("User not found", 404)
        if not user.api_only:
            return create_error_response(
                "Admins can only create tokens for API-only accounts. "
                "Other people create their own on their Profile page.", 400
            )
        api_token, token, error = create_token(db, user.id, options)
        if error:
            return create_error_response(error, 400)
        logger.info(
            f"API token created for user_id={user.id} by admin {g.user.id} "
            f"(token_id={api_token.id})"
        )
        return _created_response(api_token, token)
    finally:
        db.close()


@api_token_bp.route('/users/<int:user_id>/tokens/<int:token_id>', methods=['DELETE'])
@require_permission('user.manage')
def admin_revoke_user_token(user_id, token_id):
    """
    Revoke one of a user's API tokens (admin).
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
      - name: token_id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: Token revoked
      403:
        description: Forbidden - requires user.manage permission
      404:
        description: Token not found
    """
    db = SessionLocal()
    try:
        removed = db.query(ApiToken).filter(
            ApiToken.id == token_id,
            ApiToken.user_id == user_id
        ).delete(synchronize_session=False)
        if not removed:
            return create_error_response("API token not found", 404)
        db.commit()
        logger.info(f"API token {token_id} of user_id={user_id} revoked by admin {g.user.id}")
        return create_success_response(message="API token revoked")
    finally:
        db.close()


@api_token_bp.route('/users/<int:user_id>/tokens', methods=['DELETE'])
@require_permission('user.manage')
def admin_revoke_user_tokens(user_id):
    """
    Revoke all of a user's API tokens (admin), for example after a leak.
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
        description: Tokens revoked
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
        removed = db.query(ApiToken).filter(
            ApiToken.user_id == user_id
        ).delete(synchronize_session=False)
        db.commit()
        logger.info(f"Revoked {removed} API token(s) for user_id={user_id} by admin {g.user.id}")
        return create_success_response(
            data={'removed': removed}, message=f"Revoked {removed} API token(s)"
        )
    finally:
        db.close()
