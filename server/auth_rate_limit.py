"""
Rate limits for password checks and other sign-in endpoints.

Every password check shares one budget per account, so guesses can't be spread
across login, Basic Auth, /validate, change-password and passkey enrolment.
Failures are also counted per client IP, which catches one client trying many
accounts. Only failures count, so normal sign-ins never use up a budget.

Blocks expire by themselves and blocked attempts don't extend them. This limits
how long an attacker can keep a real user out, which a hard lockout would not.
Counts are kept in Redis so every worker shares them, with a per-worker
in-memory fallback while Redis is unavailable.
"""

from dataclasses import dataclass
import hashlib
import ipaddress
import logging
import math
import os
import threading
import time

from flask import request
import redis

logger = logging.getLogger(__name__)

FAILURE_WINDOW_SECONDS = 15 * 60
REGISTRATION_WINDOW_SECONDS = 60 * 60
PASSKEY_START_WINDOW_SECONDS = 60

KEY_PREFIX = 'aft:rl:auth:'
REDIS_TIMEOUT_SECONDS = 1


@dataclass(frozen=True)
class AuthRateLimitSettings:
    """Limits read from the environment."""

    account_failures: int = 10
    ip_failures: int = 50
    registrations: int = 10
    passkey_starts: int = 60
    trusted_proxy_hops: int = 1


def _read_int(name, default, minimum):
    """Return an integer env var, raising ValueError if it is invalid."""
    raw = os.environ.get(name, '').strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        value = None
    if value is None or value < minimum:
        raise ValueError(
            f"Invalid auth rate limit setting: {name} must be a whole number "
            f"of at least {minimum}, got {raw!r}"
        )
    return value


def read_auth_rate_limit_settings():
    """Read and validate the rate limit settings.

    Returns:
        AuthRateLimitSettings: The validated settings.

    Raises:
        ValueError: If a setting is not a whole number in range.
    """
    defaults = AuthRateLimitSettings()
    return AuthRateLimitSettings(
        account_failures=_read_int('AUTH_RATE_LIMIT_ACCOUNT_FAILURES', defaults.account_failures, 1),
        ip_failures=_read_int('AUTH_RATE_LIMIT_IP_FAILURES', defaults.ip_failures, 1),
        registrations=_read_int('AUTH_RATE_LIMIT_REGISTRATIONS', defaults.registrations, 1),
        passkey_starts=_read_int('AUTH_RATE_LIMIT_PASSKEY_STARTS', defaults.passkey_starts, 1),
        trusted_proxy_hops=_read_int('TRUSTED_PROXY_HOPS', defaults.trusted_proxy_hops, 0),
    )


class AttemptStore:
    """Counts attempts per key, each count expiring a fixed time after it started."""

    def __init__(self, redis_url=None):
        self._redis = None
        if redis_url:
            # from_url connects on first use and reconnects, so Redis can start
            # later or restart without leaving this process on the fallback.
            self._redis = redis.from_url(
                redis_url,
                socket_connect_timeout=REDIS_TIMEOUT_SECONDS,
                socket_timeout=REDIS_TIMEOUT_SECONDS,
            )
        self._memory = {}
        self._lock = threading.Lock()

    def blocked_for(self, key, limit, window):
        """Return the seconds until key may try again, or 0 if it isn't blocked."""
        if self._redis:
            try:
                pipeline = self._redis.pipeline()
                pipeline.get(key)
                pipeline.ttl(key)
                count, ttl = pipeline.execute()
                if int(count or 0) < limit:
                    return 0
                return ttl if ttl > 0 else window
            except redis.RedisError as error:
                logger.warning("Auth rate limit read failed, using in-memory fallback: %s", error)

        now = time.monotonic()
        with self._lock:
            count, expires_at = self._memory.get(key, (0, now))
        if expires_at <= now or count < limit:
            return 0
        return max(1, math.ceil(expires_at - now))

    def record(self, key, window):
        """Count one attempt against key."""
        if self._redis:
            try:
                # Atomic, so a count can't be left behind without an expiry. SET
                # NX only applies to a new key and INCR keeps the existing expiry.
                pipeline = self._redis.pipeline(transaction=True)
                pipeline.set(key, 0, ex=window, nx=True)
                pipeline.incr(key)
                pipeline.execute()
                return
            except redis.RedisError as error:
                logger.warning("Auth rate limit write failed, using in-memory fallback: %s", error)

        now = time.monotonic()
        with self._lock:
            # Drop expired counts so fallback memory stays bounded.
            self._memory = {k: v for k, v in self._memory.items() if v[1] > now}
            count, expires_at = self._memory.get(key, (0, now + window))
            self._memory[key] = (count + 1, expires_at)

    def clear(self, key):
        """Forget all attempts against key."""
        if self._redis:
            try:
                self._redis.delete(key)
            except redis.RedisError as error:
                logger.warning("Auth rate limit clear failed: %s", error)
        with self._lock:
            self._memory.pop(key, None)


# Raises ValueError at startup if a setting is invalid.
SETTINGS = read_auth_rate_limit_settings()
_store = AttemptStore(os.getenv('REDIS_URL'))


def get_client_ip():
    """Return the client's IP address for rate limiting.

    The bundled nginx is the only way in, so remote_addr is always nginx. Each
    trusted proxy appends the address it saw to X-Forwarded-For, so the client
    is found by counting back from the right. Anything further left was sent by
    the client and can be spoofed.
    """
    hops = SETTINGS.trusted_proxy_hops
    if hops:
        forwarded = request.headers.get('X-Forwarded-For', '').split(',')
        if len(forwarded) >= hops:
            candidate = forwarded[-hops].strip()
            try:
                ipaddress.ip_address(candidate)
                return candidate
            except ValueError:
                logger.warning("Ignoring invalid X-Forwarded-For entry for rate limiting")
    return request.remote_addr or 'unknown'


def _client_key():
    """Return the rate limit identity for this client.

    IPv6 clients are grouped by /64, the smallest block usually given to one
    customer, so they can't get a new budget from each address in it.
    """
    client_ip = get_client_ip()
    try:
        address = ipaddress.ip_address(client_ip)
    except ValueError:
        return client_ip
    if address.version == 4:
        return str(address)
    if address.ipv4_mapped:
        return str(address.ipv4_mapped)
    return str(ipaddress.ip_network(f"{address}/64", strict=False))


def account_key(user, identifier=None):
    """Return the budget key for a sign-in attempt.

    Args:
        user: The matched User, or None if there is no such account.
        identifier: The email or username given, used when there is no User.

    Returns:
        A key that is the same for a user's email and username. Unknown names
        are limited too, so a block doesn't reveal whether an account exists.
        It uses the email, not the user ID, because a database restore can give
        an ID to a different user, who would then inherit the block.
    """
    name = user.email if user is not None else identifier
    digest = hashlib.sha256((name or '').lower().encode('utf-8')).hexdigest()
    return f"name:{digest}"


def password_block_seconds(account):
    """Return the seconds until a password may be checked, or 0 if allowed now.

    Call this before verifying a password. A blocked attempt must not verify
    it, or the response would still show whether the guess was right.
    """
    client = _client_key()
    retry_after = max(
        _store.blocked_for(
            f"{KEY_PREFIX}fail:{account}", SETTINGS.account_failures, FAILURE_WINDOW_SECONDS
        ),
        _store.blocked_for(
            f"{KEY_PREFIX}fail-ip:{client}", SETTINGS.ip_failures, FAILURE_WINDOW_SECONDS
        ),
    )
    if retry_after:
        logger.warning("Password attempt blocked for %s from %s", account, client)
    return retry_after


def record_password_failure(account):
    """Count a failed password check against the account and the client."""
    _store.record(f"{KEY_PREFIX}fail:{account}", FAILURE_WINDOW_SECONDS)
    _store.record(f"{KEY_PREFIX}fail-ip:{_client_key()}", FAILURE_WINDOW_SECONDS)


def clear_password_failures(account):
    """Reset an account's budget once its owner proves they know the password.

    The client's budget stays, so one valid login can't reset the count for
    guesses against other accounts.
    """
    _store.clear(f"{KEY_PREFIX}fail:{account}")


def _consume_client_budget(name, limit, window):
    """Count one request against this client, returning seconds blocked or 0."""
    key = f"{KEY_PREFIX}{name}:{_client_key()}"
    retry_after = _store.blocked_for(key, limit, window)
    if retry_after:
        logger.warning("Rate limit %s reached for %s", name, _client_key())
    else:
        _store.record(key, window)
    return retry_after


def registration_block_seconds():
    """Count a registration attempt, returning seconds blocked or 0 if allowed."""
    return _consume_client_budget('register', SETTINGS.registrations, REGISTRATION_WINDOW_SECONDS)


def passkey_start_block_seconds():
    """Count a passkey sign-in start, returning seconds blocked or 0 if allowed."""
    return _consume_client_budget('passkey', SETTINGS.passkey_starts, PASSKEY_START_WINDOW_SECONDS)


def too_many_attempts_response(retry_after):
    """Return a 429 response.

    This must stay a 429: the fetch wrapper in www/js/utils.js treats any 401
    as signed out.
    """
    # Imported here so the limiter can be unit tested without the database.
    from utils import create_error_response

    if retry_after > 60:
        minutes = math.ceil(retry_after / 60)
        wait = f"{minutes} minutes"
    else:
        wait = "a minute"
    response, status_code = create_error_response(
        f"Too many attempts. Please try again in {wait}.", 429
    )
    response.headers['Retry-After'] = str(retry_after)
    return response, status_code
