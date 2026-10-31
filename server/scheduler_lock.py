"""Shared file-lock helpers for scheduler processes.

These helpers provide a consistent lock acquisition strategy with:
- exclusive file creation to prevent startup races
- lock metadata diagnostics for observability
- stale lock detection based on owner liveness and heartbeat age
"""

import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Gunicorn doesn't preload the app, so this is imported once per worker, before
# the worker can acquire any lock.
_PROCESS_STARTED_AT = datetime.now()


def _current_container_id() -> str:
    """Return the container/host identifier used for lock ownership."""
    return os.environ.get("HOSTNAME", "unknown")


def _is_pid_alive(pid: int) -> bool:
    """Check whether a PID is alive from the current process namespace."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        # No such process.
        return False
    except PermissionError:
        # Process likely exists but is owned by another user/namespace.
        return True
    except OSError:
        # Conservatively treat other OS errors as not alive.
        return False


def _is_own_lock_from_previous_process(lock_data: dict[str, Any]) -> bool:
    """Check for a lock left by an earlier process that had this same PID.

    A container restart keeps /tmp and its PIDs repeat, so a new worker can find
    a lock naming its own PID. The owner looks alive, but it can't be this
    process if the lock predates it.
    """
    if lock_data.get("pid") != os.getpid():
        return False

    acquired_text = lock_data.get("acquired_at")
    if not isinstance(acquired_text, str):
        return False

    try:
        return datetime.fromisoformat(acquired_text) < _PROCESS_STARTED_AT
    except ValueError:
        return False


def _lock_file_signature(lock_file: Path) -> tuple[int, int, int] | None:
    """Return a best-effort signature for race-safe lock eviction checks."""
    try:
        stat_result = lock_file.stat()
        return (
            int(getattr(stat_result, "st_ino", 0)),
            int(stat_result.st_size),
            int(stat_result.st_mtime_ns),
        )
    except FileNotFoundError:
        return None


def _read_lock_data(lock_file: Path) -> dict[str, Any]:
    """Read lock metadata from disk."""
    raw = lock_file.read_text(encoding="utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Lock data is not a JSON object")
    return value


def _lock_owner_identity(lock_data: dict[str, Any]) -> tuple[Any, Any, Any, Any]:
    """Return the identifying fields used to validate stale-lock ownership."""
    return (
        lock_data.get("pid"),
        lock_data.get("container_id"),
        lock_data.get("scheduler_type"),
        lock_data.get("acquired_at"),
    )


def get_lock_diagnostics(lock_file: Path) -> dict[str, Any]:
    """Return best-effort diagnostics about a lock file."""
    diagnostics: dict[str, Any] = {
        "lock_file": str(lock_file),
        "exists": lock_file.exists(),
        "valid": False,
    }

    if not lock_file.exists():
        return diagnostics

    try:
        lock_data = _read_lock_data(lock_file)
        diagnostics["valid"] = True
        diagnostics["pid"] = lock_data.get("pid")
        diagnostics["container_id"] = lock_data.get("container_id")
        diagnostics["scheduler_type"] = lock_data.get("scheduler_type")
        diagnostics["acquired_at"] = lock_data.get("acquired_at")
        diagnostics["last_heartbeat"] = lock_data.get("last_heartbeat")

        pid = lock_data.get("pid")
        if isinstance(pid, int):
            diagnostics["pid_alive"] = _is_pid_alive(pid)

        heartbeat_text = lock_data.get("last_heartbeat")
        if isinstance(heartbeat_text, str):
            try:
                heartbeat = datetime.fromisoformat(heartbeat_text)
                diagnostics["heartbeat_age_seconds"] = (datetime.now() - heartbeat).total_seconds()
            except ValueError:
                diagnostics["heartbeat_age_seconds"] = None

    except Exception as exc:
        diagnostics["error"] = str(exc)

    return diagnostics


def is_scheduler_lock_stale(
    lock_file: Path,
    scheduler_type: str,
    stale_after_seconds: int = 300,
) -> bool:
    """Determine whether an existing scheduler lock should be evicted."""
    if not lock_file.exists():
        return True

    try:
        lock_data = _read_lock_data(lock_file)

        lock_scheduler_type = lock_data.get("scheduler_type")
        if lock_scheduler_type and lock_scheduler_type != scheduler_type:
            logger.warning(
                "Lock type mismatch for %s: expected=%s found=%s",
                lock_file,
                scheduler_type,
                lock_scheduler_type,
            )
            return True

        lock_container = lock_data.get("container_id", "unknown")
        current_container = _current_container_id()

        pid = lock_data.get("pid")
        if not isinstance(pid, int):
            return True

        # Different container means stale in Docker restart scenarios.
        if lock_container != current_container:
            return True

        if _is_own_lock_from_previous_process(lock_data):
            return True

        pid_alive = _is_pid_alive(pid)
        if not pid_alive:
            return True

        heartbeat_text = lock_data.get("last_heartbeat")
        if isinstance(heartbeat_text, str):
            try:
                age_seconds = (datetime.now() - datetime.fromisoformat(heartbeat_text)).total_seconds()
                if age_seconds > stale_after_seconds:
                    # Keep active-owner locks to avoid duplicate schedulers if the thread is delayed.
                    logger.warning(
                        "Scheduler lock heartbeat is old but owner pid is alive: lock=%s pid=%s age=%.1fs",
                        lock_file,
                        pid,
                        age_seconds,
                    )
                return False
            except ValueError:
                return False

        return False
    except Exception:
        return True


def acquire_scheduler_lock(
    lock_file: Path,
    scheduler_type: str,
    stale_after_seconds: int = 300,
) -> tuple[bool, dict[str, Any]]:
    """Acquire a scheduler lock using exclusive create with one stale-lock retry."""
    metadata = {
        "pid": os.getpid(),
        "container_id": _current_container_id(),
        "scheduler_type": scheduler_type,
        "acquired_at": datetime.now().isoformat(),
        "last_heartbeat": datetime.now().isoformat(),
    }

    for attempt in range(2):
        try:
            fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(metadata, handle, indent=2)
            return True, {"reason": "acquired", **get_lock_diagnostics(lock_file)}
        except FileExistsError:
            signature_before_check = _lock_file_signature(lock_file)
            stale_lock_data: dict[str, Any] | None = None
            try:
                stale_lock_data = _read_lock_data(lock_file)
            except Exception:
                stale_lock_data = None

            stale = is_scheduler_lock_stale(
                lock_file=lock_file,
                scheduler_type=scheduler_type,
                stale_after_seconds=stale_after_seconds,
            )
            if not stale:
                return False, {"reason": "active_lock", **get_lock_diagnostics(lock_file)}

            if attempt == 0:
                try:
                    # Re-validate the lock file immediately before removal to avoid TOCTOU deletion.
                    signature_before_unlink = _lock_file_signature(lock_file)
                    if (
                        signature_before_check is not None
                        and signature_before_unlink is not None
                        and signature_before_unlink != signature_before_check
                    ):
                        return False, {
                            "reason": "stale_lock_changed_before_remove",
                            **get_lock_diagnostics(lock_file),
                        }

                    if stale_lock_data is not None and signature_before_unlink is not None:
                        try:
                            current_lock_data = _read_lock_data(lock_file)
                            if _lock_owner_identity(current_lock_data) != _lock_owner_identity(stale_lock_data):
                                return False, {
                                    "reason": "stale_lock_owner_changed_before_remove",
                                    **get_lock_diagnostics(lock_file),
                                }
                        except Exception:
                            return False, {
                                "reason": "stale_lock_unreadable_before_remove",
                                **get_lock_diagnostics(lock_file),
                            }

                    lock_file.unlink(missing_ok=False)
                except FileNotFoundError:
                    pass
                except Exception as exc:
                    return False, {
                        "reason": "stale_lock_remove_failed",
                        "error": str(exc),
                        **get_lock_diagnostics(lock_file),
                    }
                continue

            return False, {"reason": "stale_lock_retry_failed", **get_lock_diagnostics(lock_file)}
        except Exception as exc:
            return False, {"reason": "error", "error": str(exc), **get_lock_diagnostics(lock_file)}

    return False, {"reason": "unknown", **get_lock_diagnostics(lock_file)}


def update_scheduler_heartbeat(lock_file: Path, scheduler_type: str) -> bool:
    """Refresh lock heartbeat without changing ownership metadata."""
    try:
        data = {}
        if lock_file.exists():
            try:
                data = _read_lock_data(lock_file)
            except Exception:
                data = {}

        data["pid"] = os.getpid()
        data["container_id"] = _current_container_id()
        data["scheduler_type"] = scheduler_type
        if "acquired_at" not in data:
            data["acquired_at"] = datetime.now().isoformat()
        data["last_heartbeat"] = datetime.now().isoformat()

        lock_dir = lock_file.parent
        temp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(lock_dir),
                delete=False,
                prefix=f".{lock_file.name}.",
                suffix=".tmp",
            ) as temp_handle:
                json.dump(data, temp_handle, indent=2)
                temp_handle.flush()
                os.fsync(temp_handle.fileno())
                temp_path = temp_handle.name

            os.replace(temp_path, str(lock_file))
            temp_path = None
        finally:
            if temp_path is not None:
                try:
                    Path(temp_path).unlink(missing_ok=True)
                except Exception:
                    pass
        return True
    except Exception as exc:
        logger.warning("Failed to update scheduler heartbeat for %s: %s", lock_file, exc)
        return False


def release_scheduler_lock(lock_file: Path) -> None:
    """Remove lock file, if present."""
    try:
        if lock_file.exists():
            lock_file.unlink()
    except Exception as exc:
        logger.error("Failed to release scheduler lock %s: %s", lock_file, exc)
