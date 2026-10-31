"""Progress of a running database restore, for the page that started it.

The restore request stays open until it finishes, so the page polls a second
route for progress. That route can't use the session, because the users table
doesn't exist for part of a restore. The page makes up a random id instead and
sends it with the restore request, and only that id can read the progress.

Progress is kept in Redis so every worker can read it, with a per-worker
in-memory fallback while Redis is unavailable.
"""

import json
import logging
import os
import re
import threading
import time

import redis

logger = logging.getLogger(__name__)

RESTORE_PROGRESS_HEADER = 'X-Restore-Progress-Id'
PROGRESS_ID_PATTERN = re.compile(r'[0-9a-f]{32}')
PROGRESS_TTL_SECONDS = 3600
KEY_PREFIX = 'restore_progress:'
REDIS_TIMEOUT_SECONDS = 1
# Importing writes after every line, so limit how often that reaches the store.
IMPORT_WRITE_INTERVAL_SECONDS = 0.5


def is_valid_progress_id(progress_id):
    return bool(progress_id and PROGRESS_ID_PATTERN.fullmatch(progress_id))


class ProgressStore:
    """Holds the latest progress for each restore until it expires."""

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

    def write(self, progress_id, state):
        if self._redis:
            try:
                self._redis.set(KEY_PREFIX + progress_id, json.dumps(state), ex=PROGRESS_TTL_SECONDS)
                return
            except redis.RedisError as error:
                logger.warning("Restore progress write failed, using in-memory fallback: %s", error)

        now = time.monotonic()
        with self._lock:
            self._memory = {key: entry for key, entry in self._memory.items() if entry[1] > now}
            self._memory[progress_id] = (state, now + PROGRESS_TTL_SECONDS)

    def read(self, progress_id):
        if self._redis:
            try:
                stored = self._redis.get(KEY_PREFIX + progress_id)
                if stored:
                    return json.loads(stored)
            except redis.RedisError as error:
                logger.warning("Restore progress read failed, using in-memory fallback: %s", error)

        with self._lock:
            state, expires_at = self._memory.get(progress_id, (None, 0))
        return state if expires_at > time.monotonic() else None


_store = ProgressStore(os.getenv('REDIS_URL'))


def read_progress(progress_id):
    return _store.read(progress_id)


class RestoreProgress:
    """Reports one restore. Does nothing if the caller didn't ask for progress."""

    def __init__(self, progress_id):
        self._progress_id = progress_id if is_valid_progress_id(progress_id) else None
        self._table_number = 0
        self._last_write = 0

    def step(self, message):
        """Report a step that has no measurable progress of its own."""
        if self._progress_id:
            _store.write(self._progress_id, {'message': message})

    def importing(self, table_number, table_count, table, bytes_done, bytes_total):
        """Report how much of the backup file has been sent to MySQL."""
        if not self._progress_id:
            return

        now = time.monotonic()
        if table_number == self._table_number and now - self._last_write < IMPORT_WRITE_INTERVAL_SECONDS:
            return
        self._table_number = table_number

        message = 'Restoring data'
        if table:
            message = f'Restoring table {table_number} of {table_count}: {table}'
        _store.write(self._progress_id, {
            'message': message,
            'bytes_done': bytes_done,
            'bytes_total': bytes_total,
        })
        # After the write, so a slow store can't make every line wait for it.
        self._last_write = time.monotonic()
