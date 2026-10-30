"""Unit tests for the sign-in rate limiter (issue #597)."""

from flask import Flask
import pytest
import redis

import auth_rate_limit
from auth_rate_limit import (
    AttemptStore,
    AuthRateLimitSettings,
    account_key,
    get_client_ip,
    read_auth_rate_limit_settings,
    registration_block_seconds,
)

# Mark all tests in this module as unit tests (don't wait for API)
pytestmark = pytest.mark.unit

SETTING_NAMES = (
    "AUTH_RATE_LIMIT_ACCOUNT_FAILURES",
    "AUTH_RATE_LIMIT_IP_FAILURES",
    "AUTH_RATE_LIMIT_REGISTRATIONS",
    "AUTH_RATE_LIMIT_PASSKEY_STARTS",
    "TRUSTED_PROXY_HOPS",
)


class BrokenRedis:
    """A Redis client whose every command fails."""

    def pipeline(self, **_kwargs):
        raise redis.ConnectionError("down")

    def delete(self, *_args):
        raise redis.ConnectionError("down")


class FakeUser:
    id = 7
    email = "Someone@Example.com"


class FakeUserWithSameIdAfterRestore:
    id = 7
    email = "other@example.com"


def _request_context(forwarded=None, remote_addr="172.18.0.5"):
    headers = {"X-Forwarded-For": forwarded} if forwarded is not None else {}
    return Flask(__name__).test_request_context(
        headers=headers, environ_base={"REMOTE_ADDR": remote_addr}
    )


def _use_settings(monkeypatch, **overrides):
    monkeypatch.setattr(auth_rate_limit, "SETTINGS", AuthRateLimitSettings(**overrides))


class TestReadSettings:
    """Tests for read_auth_rate_limit_settings."""

    @pytest.fixture(autouse=True)
    def clear_env(self, monkeypatch):
        for name in SETTING_NAMES:
            monkeypatch.delenv(name, raising=False)

    def test_defaults_when_unset(self):
        assert read_auth_rate_limit_settings() == AuthRateLimitSettings()

    def test_reads_values(self, monkeypatch):
        monkeypatch.setenv("AUTH_RATE_LIMIT_ACCOUNT_FAILURES", "3")
        monkeypatch.setenv("TRUSTED_PROXY_HOPS", "0")
        settings = read_auth_rate_limit_settings()
        assert settings.account_failures == 3
        assert settings.trusted_proxy_hops == 0

    @pytest.mark.parametrize("name,value", [
        ("AUTH_RATE_LIMIT_ACCOUNT_FAILURES", "0"),
        ("AUTH_RATE_LIMIT_IP_FAILURES", "abc"),
        ("AUTH_RATE_LIMIT_REGISTRATIONS", "-1"),
        ("AUTH_RATE_LIMIT_PASSKEY_STARTS", "1.5"),
        ("TRUSTED_PROXY_HOPS", "-1"),
    ])
    def test_invalid_values_are_rejected(self, monkeypatch, name, value):
        monkeypatch.setenv(name, value)
        with pytest.raises(ValueError, match=name):
            read_auth_rate_limit_settings()


class TestAttemptStoreFallback:
    """The in-memory store, used when Redis is missing or failing."""

    def test_blocks_at_limit(self):
        store = AttemptStore()
        store.record("key", 60)
        assert store.blocked_for("key", 2, 60) == 0
        store.record("key", 60)
        assert 0 < store.blocked_for("key", 2, 60) <= 60

    def test_keys_are_independent(self):
        store = AttemptStore()
        store.record("one", 60)
        assert store.blocked_for("two", 1, 60) == 0

    def test_clear_resets_count(self):
        store = AttemptStore()
        store.record("key", 60)
        store.clear("key")
        assert store.blocked_for("key", 1, 60) == 0

    def test_block_expires(self, monkeypatch):
        now = [1000.0]
        monkeypatch.setattr(auth_rate_limit.time, "monotonic", lambda: now[0])
        store = AttemptStore()
        store.record("key", 60)
        assert store.blocked_for("key", 1, 60) == 60
        now[0] += 61
        assert store.blocked_for("key", 1, 60) == 0

    def test_later_attempts_do_not_extend_the_window(self, monkeypatch):
        now = [1000.0]
        monkeypatch.setattr(auth_rate_limit.time, "monotonic", lambda: now[0])
        store = AttemptStore()
        store.record("key", 60)
        now[0] += 50
        store.record("key", 60)
        assert store.blocked_for("key", 1, 60) == 10

    def test_expired_counts_are_dropped(self, monkeypatch):
        now = [1000.0]
        monkeypatch.setattr(auth_rate_limit.time, "monotonic", lambda: now[0])
        store = AttemptStore()
        store.record("old", 60)
        now[0] += 61
        store.record("new", 60)
        assert list(store._memory) == ["new"]

    def test_redis_failure_uses_memory(self):
        store = AttemptStore()
        store._redis = BrokenRedis()
        store.record("key", 60)
        assert store.blocked_for("key", 1, 60) > 0
        store.clear("key")
        assert store.blocked_for("key", 1, 60) == 0


class TestGetClientIp:
    """X-Forwarded-For must be read from the right, or clients could spoof it."""

    def test_bundled_nginx_entry_is_used(self, monkeypatch):
        _use_settings(monkeypatch, trusted_proxy_hops=1)
        with _request_context("203.0.113.9"):
            assert get_client_ip() == "203.0.113.9"

    def test_spoofed_entries_are_ignored(self, monkeypatch):
        _use_settings(monkeypatch, trusted_proxy_hops=1)
        with _request_context("1.1.1.1, 2.2.2.2, 203.0.113.9"):
            assert get_client_ip() == "203.0.113.9"

    def test_extra_proxy_counts_back_one_more(self, monkeypatch):
        _use_settings(monkeypatch, trusted_proxy_hops=2)
        with _request_context("1.1.1.1, 203.0.113.9, 172.18.0.2"):
            assert get_client_ip() == "203.0.113.9"

    def test_no_trusted_proxies_ignores_header(self, monkeypatch):
        _use_settings(monkeypatch, trusted_proxy_hops=0)
        with _request_context("203.0.113.9"):
            assert get_client_ip() == "172.18.0.5"

    def test_too_few_entries_falls_back_to_remote_addr(self, monkeypatch):
        _use_settings(monkeypatch, trusted_proxy_hops=2)
        with _request_context("203.0.113.9"):
            assert get_client_ip() == "172.18.0.5"

    @pytest.mark.parametrize("forwarded", ["", "not-an-ip", "1.2.3.4\r\nInjected: yes"])
    def test_invalid_entry_falls_back_to_remote_addr(self, monkeypatch, forwarded):
        _use_settings(monkeypatch, trusted_proxy_hops=1)
        with _request_context():
            auth_rate_limit.request.environ["HTTP_X_FORWARDED_FOR"] = forwarded
            assert get_client_ip() == "172.18.0.5"


class TestAccountKey:
    """Tests for account_key."""

    def test_user_key_ignores_the_identifier(self):
        assert account_key(FakeUser, "a@example.com") == account_key(FakeUser, "a-username")

    def test_reused_user_id_does_not_share_a_budget(self):
        assert account_key(FakeUser) != account_key(FakeUserWithSameIdAfterRestore)

    def test_unknown_names_ignore_case(self):
        assert account_key(None, "Nobody@Example.com") == account_key(None, "nobody@example.com")

    def test_unknown_name_is_not_stored_in_clear(self):
        assert "nobody" not in account_key(None, "nobody@example.com")


class TestClientBudgets:
    """Tests for the per-client limits, which the API tests can't reach."""

    @pytest.fixture(autouse=True)
    def fresh_store(self, monkeypatch):
        monkeypatch.setattr(auth_rate_limit, "_store", AttemptStore())

    def test_registration_blocks_after_limit(self, monkeypatch):
        _use_settings(monkeypatch, registrations=2)
        with _request_context("203.0.113.9"):
            assert registration_block_seconds() == 0
            assert registration_block_seconds() == 0
            assert registration_block_seconds() > 0

    def test_other_clients_keep_their_budget(self, monkeypatch):
        _use_settings(monkeypatch, registrations=1)
        with _request_context("203.0.113.9"):
            registration_block_seconds()
        with _request_context("203.0.113.10"):
            assert registration_block_seconds() == 0

    def test_ipv6_addresses_in_one_64_share_a_budget(self, monkeypatch):
        _use_settings(monkeypatch, registrations=1)
        with _request_context("2001:db8:1:2::1"):
            registration_block_seconds()
        with _request_context("2001:db8:1:2::2"):
            assert registration_block_seconds() > 0

    def test_ipv4_failures_block_any_account(self, monkeypatch):
        _use_settings(monkeypatch, ip_failures=2, account_failures=100)
        with _request_context("203.0.113.9"):
            auth_rate_limit.record_password_failure("name:a")
            auth_rate_limit.record_password_failure("name:b")
            assert auth_rate_limit.password_block_seconds("name:c") > 0
        with _request_context("203.0.113.10"):
            assert auth_rate_limit.password_block_seconds("name:c") == 0

    def test_clearing_an_account_keeps_the_client_count(self, monkeypatch):
        _use_settings(monkeypatch, ip_failures=1, account_failures=100)
        with _request_context("203.0.113.9"):
            auth_rate_limit.record_password_failure("user:1")
            auth_rate_limit.clear_password_failures("user:1")
            assert auth_rate_limit.password_block_seconds("user:2") > 0
