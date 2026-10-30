"""Unit tests for passkey (WebAuthn) settings (issue #546)."""

import pytest

from webauthn_settings import DEFAULT_RP_NAME, read_webauthn_settings

# Mark all tests in this module as unit tests (don't wait for API)
pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    """Start each test with no passkey settings and Redis configured."""
    for name in ("WEBAUTHN_RP_ID", "WEBAUTHN_RP_NAME", "WEBAUTHN_ORIGINS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")


class TestReadWebAuthnSettings:
    """Tests for read_webauthn_settings."""

    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_disabled_when_unset_or_blank(self, monkeypatch, value):
        """Passkeys are off unless WEBAUTHN_RP_ID has a value."""
        if value is not None:
            monkeypatch.setenv("WEBAUTHN_RP_ID", value)
        assert read_webauthn_settings() is None

    def test_defaults(self, monkeypatch):
        """Only the RP ID is needed; the name and origin have defaults."""
        monkeypatch.setenv("WEBAUTHN_RP_ID", "aft.example.com")
        settings = read_webauthn_settings()
        assert settings.rp_id == "aft.example.com"
        assert settings.rp_name == DEFAULT_RP_NAME
        assert settings.origins == ("https://aft.example.com",)

    def test_custom_name_and_origins(self, monkeypatch):
        """Origins are normalised and duplicates dropped; subdomains and ports are allowed."""
        monkeypatch.setenv("WEBAUTHN_RP_ID", "example.com")
        monkeypatch.setenv("WEBAUTHN_RP_NAME", " Team boards ")
        monkeypatch.setenv(
            "WEBAUTHN_ORIGINS",
            "https://example.com/, https://aft.example.com:8443,https://example.com,",
        )
        settings = read_webauthn_settings()
        assert settings.rp_name == "Team boards"
        assert settings.origins == ("https://example.com", "https://aft.example.com:8443")

    def test_localhost_may_use_http(self, monkeypatch):
        """Browsers treat http://localhost as secure, so it is allowed for development."""
        monkeypatch.setenv("WEBAUTHN_RP_ID", "localhost")
        monkeypatch.setenv("WEBAUTHN_ORIGINS", "http://localhost,https://localhost")
        assert read_webauthn_settings().origins == ("http://localhost", "https://localhost")

    @pytest.mark.parametrize("rp_id", [
        "AFT.example.com",
        "192.168.1.10",
        "::1",
        "[::1]",
        "https://aft.example.com",
        "aft.example.com:443",
        "aft.example.com/path",
        "-bad.example.com",
        "bad..example.com",
    ])
    def test_invalid_rp_id(self, monkeypatch, rp_id):
        """The RP ID must be a bare, lower-case domain name."""
        monkeypatch.setenv("WEBAUTHN_RP_ID", rp_id)
        with pytest.raises(ValueError, match="WEBAUTHN_RP_ID"):
            read_webauthn_settings()

    @pytest.mark.parametrize("origin", [
        "http://aft.example.com",
        "https://other.example",
        "https://notexample.com",
        "https://example.com/login",
        "https://example.com?x=1",
        "ftp://example.com",
        "example.com",
        "https://user@example.com",
    ])
    def test_invalid_origin(self, monkeypatch, origin):
        """Origins must be https (except localhost), on the RP ID, with no path."""
        monkeypatch.setenv("WEBAUTHN_RP_ID", "example.com")
        monkeypatch.setenv("WEBAUTHN_ORIGINS", origin)
        with pytest.raises(ValueError, match="WEBAUTHN_ORIGINS"):
            read_webauthn_settings()

    def test_rp_name_too_long(self, monkeypatch):
        monkeypatch.setenv("WEBAUTHN_RP_ID", "example.com")
        monkeypatch.setenv("WEBAUTHN_RP_NAME", "x" * 65)
        with pytest.raises(ValueError, match="WEBAUTHN_RP_NAME"):
            read_webauthn_settings()

    def test_requires_redis(self, monkeypatch):
        """Challenges are stored in Redis, so passkeys need REDIS_URL."""
        monkeypatch.setenv("WEBAUTHN_RP_ID", "example.com")
        monkeypatch.delenv("REDIS_URL")
        with pytest.raises(ValueError, match="REDIS_URL"):
            read_webauthn_settings()
