"""Restart or shut down the docker host from Instance Settings (#726).

Only for hosts dedicated to AFT, and off unless HOST_POWER_CONTROL is set and
the request directory is mounted and writable. The container can't run host
commands: it writes the word `reboot` or `poweroff` to a request file, and a
systemd path unit on the host (contrib/host-control) acts on it. The host
decides what is possible; the container can only ask.

A request made while a backup or restore runs is held until that finishes,
whether it succeeds or fails. Running work and the held request are kept in
Redis, so every worker sees them, with a per-worker in-memory fallback while
Redis is unavailable.
"""

import functools
import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import redis

logger = logging.getLogger(__name__)

ACTIONS = ('reboot', 'poweroff')
REQUEST_FILENAME = 'request'
DEFAULT_REQUEST_DIR = '/app/host-control'
# A held request expires, so a stuck backup can't restart the host much later.
PENDING_TTL_SECONDS = 3 * 3600
# Running work is forgotten after this, in case its process dies without
# saying so and isn't noticed as gone (see _process_is_alive).
RUNNING_TTL_SECONDS = 6 * 3600
REDIS_TIMEOUT_SECONDS = 1
KEY_PREFIX = 'host_power:'
PENDING_KEY = KEY_PREFIX + 'pending'
RUNNING_PREFIX = KEY_PREFIX + 'running:'

WORK_NAMES = {
    'backup': 'A backup',
    'restore': 'A restore',
    'reset': 'A database reset',
}
ACTION_NAMES = {'reboot': 'restart', 'poweroff': 'shut down'}


def is_enabled():
    """True only when the env setting is on and the request directory is usable."""
    if os.getenv('HOST_POWER_CONTROL', 'false').strip().lower() not in ('1', 'true', 'yes', 'on'):
        return False
    directory = request_dir()
    return os.path.isdir(directory) and os.access(directory, os.W_OK | os.X_OK)


def request_dir():
    return os.getenv('HOST_CONTROL_DIR', DEFAULT_REQUEST_DIR)


def _request_path():
    return os.path.join(request_dir(), REQUEST_FILENAME)


def _process_start_ticks(pid):
    """When a process started, in clock ticks since boot, or None if it isn't running.

    PIDs repeat, especially across container restarts, so a PID alone can't
    say whether the process that recorded some work is still the one running.
    """
    try:
        with open(f'/proc/{pid}/stat', encoding='ascii') as stat:
            # The command name can contain spaces, so count fields after its ')'.
            return stat.read().rsplit(')', 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def _process_is_alive(owner):
    if not os.path.isdir('/proc/self'):
        # No /proc (not Linux): trust the entry until it expires.
        return True
    ticks = _process_start_ticks(owner.get('pid'))
    if ticks is None:
        return False
    # No start time was recorded if the owner couldn't read its own.
    return owner.get('started') in (None, ticks)


class Store:
    """Running work and the held request, in Redis with an in-memory fallback."""

    def __init__(self, redis_url=None):
        self._redis = None
        if redis_url:
            self._redis = redis.from_url(
                redis_url,
                socket_connect_timeout=REDIS_TIMEOUT_SECONDS,
                socket_timeout=REDIS_TIMEOUT_SECONDS,
            )
        self._memory = {}
        self._lock = threading.Lock()

    def _memory_live(self):
        now = time.monotonic()
        self._memory = {key: entry for key, entry in self._memory.items() if entry[1] > now}
        return self._memory

    def set(self, key, value, ttl, only_if_absent=False):
        """Store a JSON value. Returns False if only_if_absent and the key exists."""
        if self._redis:
            try:
                return bool(self._redis.set(key, json.dumps(value), ex=ttl, nx=only_if_absent))
            except redis.RedisError as error:
                logger.warning("Host power store write failed, using in-memory fallback: %s", error)

        with self._lock:
            memory = self._memory_live()
            if only_if_absent and key in memory:
                return False
            memory[key] = (value, time.monotonic() + ttl)
        return True

    def get(self, key):
        if self._redis:
            try:
                stored = self._redis.get(key)
                return json.loads(stored) if stored else None
            except redis.RedisError as error:
                logger.warning("Host power store read failed, using in-memory fallback: %s", error)

        with self._lock:
            entry = self._memory_live().get(key)
        return entry[0] if entry else None

    def take(self, key):
        """Remove and return a value. Only one caller gets it."""
        if self._redis:
            try:
                stored = self._redis.getdel(key)
                return json.loads(stored) if stored else None
            except redis.RedisError as error:
                logger.warning("Host power store take failed, using in-memory fallback: %s", error)

        with self._lock:
            entry = self._memory_live().pop(key, None)
        return entry[0] if entry else None

    def delete(self, key):
        if self._redis:
            try:
                self._redis.delete(key)
            except redis.RedisError as error:
                logger.warning("Host power store delete failed: %s", error)

        with self._lock:
            self._memory.pop(key, None)

    def items(self, prefix):
        found = {}
        if self._redis:
            try:
                for key in self._redis.scan_iter(match=prefix + '*', count=100):
                    stored = self._redis.get(key)
                    if stored:
                        found[key.decode() if isinstance(key, bytes) else key] = json.loads(stored)
            except redis.RedisError as error:
                logger.warning("Host power store scan failed, using in-memory fallback: %s", error)

        with self._lock:
            for key, (value, _) in self._memory_live().items():
                if key.startswith(prefix):
                    found.setdefault(key, value)
        return found


_store = Store(os.getenv('REDIS_URL'))
_OWN_START_TICKS = _process_start_ticks(os.getpid())


# ---------------------------------------------------------------------------
# Running backups and restores
# ---------------------------------------------------------------------------

def running_work():
    """Names of the backups and restores running now, oldest first."""
    entries = []
    for key, owner in _store.items(RUNNING_PREFIX).items():
        if _process_is_alive(owner):
            entries.append(owner)
        else:
            logger.warning("Forgetting %s from a process that has stopped (pid %s)",
                           owner.get('work'), owner.get('pid'))
            _store.delete(key)
    entries.sort(key=lambda owner: owner.get('since', 0))
    return [owner.get('work') for owner in entries]


def start_work(work):
    key = RUNNING_PREFIX + uuid.uuid4().hex
    _store.set(key, {
        'work': work,
        'pid': os.getpid(),
        'started': _OWN_START_TICKS,
        'since': time.time(),
    }, RUNNING_TTL_SECONDS)
    return key


def finish_work(key):
    _store.delete(key)
    try:
        release_if_idle()
    except Exception:
        # Never let this fail the backup or restore it follows.
        logger.exception("Couldn't release a held host power request")


def holds_host_power(work):
    """Hold host restart and shut down requests while the wrapped function runs."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            key = start_work(work)
            try:
                return func(*args, **kwargs)
            finally:
                finish_work(key)
        return wrapper
    return decorator


def describe_work(work):
    names = [WORK_NAMES.get(name, 'A backup or restore') for name in dict.fromkeys(work)]
    if not names:
        return ''
    if len(names) == 1:
        return f"{names[0]} is running."
    return f"{', '.join(names[:-1])} and {names[-1].lower()} are running."


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

class RequestRefused(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def requested_action():
    """The action in a request file the host hasn't acted on yet, or None."""
    try:
        with open(_request_path(), encoding='ascii', errors='replace') as request_file:
            content = request_file.read(16)
    except (FileNotFoundError, IsADirectoryError):
        return None
    except OSError as error:
        logger.warning("Couldn't read the host power request file: %s", error)
        return None
    return content if content in ACTIONS else 'unknown'


def _write_request(action):
    """Hand the action to the host. Written whole and then renamed into place,
    so the host never reads a half-written file."""
    directory = request_dir()
    temp_path = os.path.join(directory, f'.{REQUEST_FILENAME}.{uuid.uuid4().hex}')
    fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o644)
    try:
        with os.fdopen(fd, 'w', encoding='ascii') as temp_file:
            temp_file.write(action)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, _request_path())
    except BaseException:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def pending_request():
    """The held request, with what it is waiting for, or None."""
    pending = _store.get(PENDING_KEY)
    if pending:
        pending = dict(pending, waiting_for=running_work())
    return pending


def request_action(action, user, client_ip, notify):
    """Ask the host to restart or shut down, now or once nothing is running.

    Returns (held, waiting_for). Raises RequestRefused if a request is already
    waiting.
    """
    if action not in ACTIONS:
        raise ValueError(action)
    if requested_action():
        raise RequestRefused("The host hasn't acted on the last request yet. Cancel it first.")

    now = datetime.now(timezone.utc)
    pending = {
        'action': action,
        'user_id': user.id,
        'username': user.username,
        'client_ip': client_ip,
        'requested_at': now.isoformat(),
        'expires_at': (now + timedelta(seconds=PENDING_TTL_SECONDS)).isoformat(),
    }
    # Store first and then check for running work. Work that ends meanwhile
    # releases it, and release_if_idle below covers the rest, so it can't be
    # left behind. Only one caller can take it, so it's written once.
    if not _store.set(PENDING_KEY, pending, PENDING_TTL_SECONDS, only_if_absent=True):
        raise RequestRefused("A host restart or shut down is already waiting. Cancel it first.")

    logger.warning("Host %s requested by user_id=%s (%s) from %s",
                   action, user.id, user.username, client_ip)
    waiting_for = running_work()
    if waiting_for:
        notify(
            f"Host {ACTION_NAMES[action]} requested",
            f"{user.username} asked to {ACTION_NAMES[action]} the host from {client_ip}. "
            f"{describe_work(waiting_for)} The host will {ACTION_NAMES[action]} when it finishes, "
            f"unless the request is cancelled in Instance Settings.",
        )
    else:
        notify(
            f"Host {ACTION_NAMES[action]} requested",
            f"{user.username} asked to {ACTION_NAMES[action]} the host from {client_ip}.",
        )

    released = release_if_idle(notify_release=False)
    return (not released and bool(waiting_for)), waiting_for


def release_if_idle(notify_release=True):
    """Hand a held request to the host if nothing is running. Returns True if
    a request was handed over by this call."""
    if running_work():
        return False
    pending = _store.take(PENDING_KEY)
    if not pending:
        return False
    action = pending.get('action')
    if action not in ACTIONS:
        return False
    if not is_enabled():
        logger.warning("Dropped a held host %s: host power control is no longer available", action)
        return False

    _write_request(action)
    logger.warning("Host %s handed to the host (requested by user_id=%s)", action, pending.get('user_id'))
    if notify_release:
        from notification_utils import create_notification
        create_notification(
            subject=f"Host {ACTION_NAMES[action]} going ahead",
            message=(f"The backup or restore has finished, so the host {ACTION_NAMES[action]} "
                     f"{pending.get('username')} asked for is going ahead now."),
            for_admins=True,
        )
    return True


def cancel(user, client_ip):
    """Cancel a held request, and a request the host hasn't acted on yet.

    Returns the cancelled action, or None if there was nothing to cancel.
    """
    cancelled = None
    pending = _store.take(PENDING_KEY)
    if pending:
        cancelled = pending.get('action')

    waiting = requested_action()
    if waiting:
        try:
            os.unlink(_request_path())
            cancelled = cancelled or waiting
        except FileNotFoundError:
            # The host acted on it meanwhile.
            pass

    if cancelled:
        logger.warning("Host %s cancelled by user_id=%s (%s) from %s",
                       cancelled, user.id, user.username, client_ip)
    return cancelled


def clear_on_startup():
    """Drop a held request left over from before the server started, unless a
    backup or restore is still running to release it."""
    if running_work():
        return
    pending = _store.take(PENDING_KEY)
    if pending:
        logger.warning("Dropped a held host %s from before the server started", pending.get('action'))
