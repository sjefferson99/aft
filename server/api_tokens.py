"""Personal API tokens (#714).

Scripts and agents send a token as `Authorization: Bearer <token>` instead of
the account password. A token acts as its user, with the same roles, unless it
is read-only, which limits it to GET, HEAD and OPTIONS requests.

Tokens are 256 random bits, so only a SHA-256 of each is stored: a slow hash
adds nothing for a value that can't be guessed.
"""

import hashlib
import logging
import secrets
from datetime import timedelta

from sqlalchemy import or_

from datetime_helpers import serialize_datetime, utc_now
from models import ApiToken, User

logger = logging.getLogger(__name__)

TOKEN_PREFIX = 'aft_'
# token_urlsafe(32) gives 43 characters; allow a little room for format changes.
MAX_TOKEN_LENGTH = 128
DISPLAY_PREFIX_LENGTH = 12
MAX_TOKENS_PER_USER = 20
MAX_TOKEN_NAME_LENGTH = 100
MAX_EXPIRY_DAYS = 3650
# last_used_at is only written when it is this old, so busy clients don't
# cause a write on every request.
LAST_USED_UPDATE_SECONDS = 60
READ_ONLY_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS'})


def hash_token(token):
    """Return the hex SHA-256 of a token."""
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def generate_token():
    """Return a new random token string."""
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def bearer_token_from_header(header_value):
    """Return the token from an Authorization header, or None if it isn't Bearer.

    Returns an empty string for a Bearer header with no usable token, so the
    caller can still refuse the request rather than fall back to other auth.
    """
    if not header_value:
        return None
    scheme, _, value = header_value.partition(' ')
    if scheme.lower() != 'bearer':
        return None
    value = value.strip()
    if not value or len(value) > MAX_TOKEN_LENGTH or not value.isascii():
        return ''
    return value


def authenticate_token(db, token):
    """Return (user, api_token) for a valid, unexpired token, else (None, None).

    The user must be active and approved. API-only users are allowed: tokens
    are meant for them.
    """
    if not token:
        return None, None
    now = utc_now()
    row = db.query(ApiToken, User).join(User, User.id == ApiToken.user_id).filter(
        ApiToken.token_hash == hash_token(token),
        or_(ApiToken.expires_at.is_(None), ApiToken.expires_at > now),
        User.is_active == True,  # noqa: E712
        User.is_approved == True,  # noqa: E712
    ).first()
    if not row:
        return None, None

    api_token, user = row
    if (api_token.last_used_at is None
            or now - api_token.last_used_at >= timedelta(seconds=LAST_USED_UPDATE_SECONDS)):
        try:
            api_token.last_used_at = now
            db.commit()
        except Exception as e:  # The request can still go ahead without it.
            logger.warning("Could not record API token use: %s", e)
            db.rollback()
    return user, api_token


class TokenRequestError(Exception):
    """A create request was refused. message is always one of the fixed texts
    below, never built from the request."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


NAME_REQUIRED = "name is required"
NAME_EMPTY = "name cannot be empty"
NAME_TOO_LONG = f"name exceeds maximum length of {MAX_TOKEN_NAME_LENGTH} characters"
NAME_CONTROL_CHARS = "name contains control characters"
BODY_NOT_OBJECT = "Request body must be a JSON object"
READ_ONLY_INVALID = "read_only must be true or false"
EXPIRY_INVALID = f"expires_in_days must be a whole number from 1 to {MAX_EXPIRY_DAYS}"
TOO_MANY_TOKENS = f"An account can have at most {MAX_TOKENS_PER_USER} API tokens"


def validate_token_name(raw_name):
    """Return the cleaned token name, or raise TokenRequestError."""
    if not isinstance(raw_name, str):
        raise TokenRequestError(NAME_REQUIRED)
    name = raw_name.strip()
    if not name:
        raise TokenRequestError(NAME_EMPTY)
    if len(name) > MAX_TOKEN_NAME_LENGTH:
        raise TokenRequestError(NAME_TOO_LONG)
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in name):
        raise TokenRequestError(NAME_CONTROL_CHARS)
    return name


def parse_token_options(data):
    """Validate a create request body, or raise TokenRequestError.

    Returns a dict of name, read_only and expires_at (None for no expiry).
    """
    if not isinstance(data, dict):
        raise TokenRequestError(BODY_NOT_OBJECT)

    name = validate_token_name(data.get('name'))

    read_only = data.get('read_only', False)
    if not isinstance(read_only, bool):
        raise TokenRequestError(READ_ONLY_INVALID)

    expires_in_days = data.get('expires_in_days')
    expires_at = None
    if expires_in_days is not None:
        if (isinstance(expires_in_days, bool) or not isinstance(expires_in_days, int)
                or not 1 <= expires_in_days <= MAX_EXPIRY_DAYS):
            raise TokenRequestError(EXPIRY_INVALID)
        expires_at = utc_now() + timedelta(days=expires_in_days)

    return {'name': name, 'read_only': read_only, 'expires_at': expires_at}


def create_token(db, user_id, options, token):
    """Store a token made by generate_token() for a user, or raise TokenRequestError.

    Only its hash is kept, so the caller must hand the token back now.
    Returns the new token's id.
    """
    count = db.query(ApiToken.id).filter(ApiToken.user_id == user_id).count()
    if count >= MAX_TOKENS_PER_USER:
        raise TokenRequestError(TOO_MANY_TOKENS)

    api_token = ApiToken(
        user_id=user_id,
        name=options['name'],
        token_hash=hash_token(token),
        token_prefix=token[:DISPLAY_PREFIX_LENGTH],
        read_only=options['read_only'],
        expires_at=options['expires_at'],
    )
    db.add(api_token)
    db.commit()
    return api_token.id


def serialize_token(api_token):
    """Return the public fields of a token. Never includes the token or its hash."""
    expired = api_token.expires_at is not None and api_token.expires_at <= utc_now()
    return {
        'id': api_token.id,
        'name': api_token.name,
        'prefix': api_token.token_prefix,
        'read_only': bool(api_token.read_only),
        'created_at': serialize_datetime(api_token.created_at),
        'expires_at': serialize_datetime(api_token.expires_at),
        'last_used_at': serialize_datetime(api_token.last_used_at),
        'expired': expired,
    }
