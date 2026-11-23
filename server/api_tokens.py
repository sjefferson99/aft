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


def validate_token_name(raw_name):
    """Return (name, error_message) for a user-supplied token name."""
    if not isinstance(raw_name, str):
        return None, "name is required"
    name = raw_name.strip()
    if not name:
        return None, "name cannot be empty"
    if len(name) > MAX_TOKEN_NAME_LENGTH:
        return None, f"name exceeds maximum length of {MAX_TOKEN_NAME_LENGTH} characters"
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in name):
        return None, "name contains control characters"
    return name, None


def parse_token_options(data):
    """Validate a create request body.

    Returns (options, error_message). options holds name, read_only and
    expires_at (None for no expiry).
    """
    if not isinstance(data, dict):
        return None, "Request body must be a JSON object"

    name, error = validate_token_name(data.get('name'))
    if error:
        return None, error

    read_only = data.get('read_only', False)
    if not isinstance(read_only, bool):
        return None, "read_only must be true or false"

    expires_in_days = data.get('expires_in_days')
    expires_at = None
    if expires_in_days is not None:
        if (isinstance(expires_in_days, bool) or not isinstance(expires_in_days, int)
                or not 1 <= expires_in_days <= MAX_EXPIRY_DAYS):
            return None, f"expires_in_days must be a whole number from 1 to {MAX_EXPIRY_DAYS}"
        expires_at = utc_now() + timedelta(days=expires_in_days)

    return {'name': name, 'read_only': read_only, 'expires_at': expires_at}, None


def create_token(db, user_id, options):
    """Create a token for a user and commit it.

    Returns (api_token, token, error_message). The token string is only
    available here; it is not stored.
    """
    count = db.query(ApiToken.id).filter(ApiToken.user_id == user_id).count()
    if count >= MAX_TOKENS_PER_USER:
        return None, None, f"An account can have at most {MAX_TOKENS_PER_USER} API tokens"

    token = generate_token()
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
    db.refresh(api_token)
    return api_token, token, None


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
