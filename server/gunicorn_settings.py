"""Gunicorn worker and thread counts read from the environment.

Kept separate from gunicorn.conf.py so the validation can be unit tested.
"""

import os
import re

# One worker keeps memory low. Threads are cheap but each open Socket.IO
# websocket (one per board tab) holds a thread for its whole life, so the
# thread count is roughly the number of tabs one worker can serve.
DEFAULT_WORKERS = 1
MAX_WORKERS = 16
DEFAULT_THREADS = 32
MAX_THREADS = 128

# Each worker process has its own SQLAlchemy pool (pool_size 5 + max_overflow 10).
DB_CONNECTIONS_PER_WORKER = 15
# Headroom for mysqldump/mysql during backup and restore.
DB_CONNECTION_HEADROOM = 10
DEFAULT_MYSQL_MAX_CONNECTIONS = 100

_WHOLE_NUMBER = re.compile(r"[0-9]+")


def read_count(name: str, default: int, maximum: int) -> int:
    """Read a positive integer setting, failing clearly on bad values."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    if not _WHOLE_NUMBER.fullmatch(raw):
        raise ValueError(f"{name} must be a whole number between 1 and {maximum}, got {raw!r}")
    value = int(raw)
    if not 1 <= value <= maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}, got {value}")
    return value


def read_worker_settings() -> tuple[int, int]:
    """Return (workers, threads) from GUNICORN_WORKERS and GUNICORN_THREADS."""
    workers = read_count("GUNICORN_WORKERS", DEFAULT_WORKERS, MAX_WORKERS)
    threads = read_count("GUNICORN_THREADS", DEFAULT_THREADS, MAX_THREADS)
    return workers, threads


def connection_warning(workers: int) -> str | None:
    """Return a warning if the workers could exceed MySQL's connection limit."""
    raw = os.environ.get("MYSQL_MAX_CONNECTIONS", "").strip()
    limit = int(raw) if _WHOLE_NUMBER.fullmatch(raw) else DEFAULT_MYSQL_MAX_CONNECTIONS
    needed = workers * DB_CONNECTIONS_PER_WORKER + DB_CONNECTION_HEADROOM
    if needed <= limit:
        return None
    return (
        f"GUNICORN_WORKERS={workers} can open up to {needed} database connections "
        f"(including backup headroom) but MYSQL_MAX_CONNECTIONS is {limit}. "
        f"Set MYSQL_MAX_CONNECTIONS to at least {needed} in .env."
    )
