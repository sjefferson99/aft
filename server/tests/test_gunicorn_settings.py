"""Unit tests for gunicorn worker/thread settings (issue #566)."""

import pytest

from gunicorn_settings import (
    DEFAULT_THREADS,
    DEFAULT_WORKERS,
    MAX_THREADS,
    MAX_WORKERS,
    connection_warning,
    read_worker_settings,
)

# Mark all tests in this module as unit tests (don't wait for API)
pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    """Start each test with none of the settings set."""
    for name in ("GUNICORN_WORKERS", "GUNICORN_THREADS", "MYSQL_MAX_CONNECTIONS"):
        monkeypatch.delenv(name, raising=False)


class TestReadWorkerSettings:
    """Tests for read_worker_settings."""

    def test_defaults_when_unset(self):
        """Unset variables fall back to the defaults."""
        assert read_worker_settings() == (DEFAULT_WORKERS, DEFAULT_THREADS)

    def test_defaults_when_blank(self, monkeypatch):
        """Blank values, as left by an empty line in .env, use the defaults."""
        monkeypatch.setenv("GUNICORN_WORKERS", "")
        monkeypatch.setenv("GUNICORN_THREADS", "  ")
        assert read_worker_settings() == (DEFAULT_WORKERS, DEFAULT_THREADS)

    def test_reads_values(self, monkeypatch):
        """Valid values are used as given."""
        monkeypatch.setenv("GUNICORN_WORKERS", "4")
        monkeypatch.setenv("GUNICORN_THREADS", "16")
        assert read_worker_settings() == (4, 16)

    def test_accepts_upper_bounds(self, monkeypatch):
        """The maximum values are allowed."""
        monkeypatch.setenv("GUNICORN_WORKERS", str(MAX_WORKERS))
        monkeypatch.setenv("GUNICORN_THREADS", str(MAX_THREADS))
        assert read_worker_settings() == (MAX_WORKERS, MAX_THREADS)

    @pytest.mark.parametrize("value", ["0", "-1", "abc", "2.5", "4O", "1e3", "\u00b2", "\u0664"])
    def test_rejects_invalid_workers(self, monkeypatch, value):
        """Non-positive or non-integer worker counts fail with the variable name."""
        monkeypatch.setenv("GUNICORN_WORKERS", value)
        with pytest.raises(ValueError, match="GUNICORN_WORKERS"):
            read_worker_settings()

    def test_rejects_workers_above_maximum(self, monkeypatch):
        """Worker counts above the maximum are rejected."""
        monkeypatch.setenv("GUNICORN_WORKERS", str(MAX_WORKERS + 1))
        with pytest.raises(ValueError, match="GUNICORN_WORKERS"):
            read_worker_settings()

    @pytest.mark.parametrize("value", ["0", str(MAX_THREADS + 1), "eight"])
    def test_rejects_invalid_threads(self, monkeypatch, value):
        """Out-of-range or non-integer thread counts fail with the variable name."""
        monkeypatch.setenv("GUNICORN_THREADS", value)
        with pytest.raises(ValueError, match="GUNICORN_THREADS"):
            read_worker_settings()


class TestConnectionWarning:
    """Tests for connection_warning."""

    def test_no_warning_within_default_limit(self):
        """6 workers need 100 connections, which fits the default limit of 100."""
        assert connection_warning(6) is None

    def test_warns_above_default_limit(self):
        """7 workers need 115 connections, above the default limit."""
        warning = connection_warning(7)
        assert warning is not None
        assert "MYSQL_MAX_CONNECTIONS" in warning
        assert "115" in warning

    def test_uses_configured_limit(self, monkeypatch):
        """A raised MYSQL_MAX_CONNECTIONS removes the warning."""
        monkeypatch.setenv("MYSQL_MAX_CONNECTIONS", "200")
        assert connection_warning(12) is None

    @pytest.mark.parametrize("value", ["lots", "\u00b2"])
    def test_invalid_limit_falls_back_to_default(self, monkeypatch, value):
        """A non-numeric limit is treated as the default (MySQL refuses to start on it anyway)."""
        monkeypatch.setenv("MYSQL_MAX_CONNECTIONS", value)
        assert connection_warning(7) is not None
