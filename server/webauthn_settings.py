"""Passkey (WebAuthn) settings read from the environment.

Passkeys are off unless WEBAUTHN_RP_ID is set. Kept separate from the routes so
the validation can be unit tested.
"""

import ipaddress
import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

DEFAULT_RP_NAME = "AFT"
MAX_RP_NAME_LENGTH = 64

_LABEL = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")
_LOCAL_HOSTS = {"localhost"}


@dataclass(frozen=True)
class WebAuthnSettings:
    """Validated passkey settings."""

    rp_id: str
    rp_name: str
    origins: tuple[str, ...]


def _validate_rp_id(rp_id: str) -> str:
    """Return the RP ID if it is a usable domain name, else raise ValueError."""
    if rp_id != rp_id.lower():
        raise ValueError(f"WEBAUTHN_RP_ID must be lower case, got {rp_id!r}")
    try:
        ipaddress.ip_address(rp_id.strip("[]"))
    except ValueError:
        pass
    else:
        raise ValueError(
            f"WEBAUTHN_RP_ID must be a domain name, not an IP address, got {rp_id!r}"
        )
    if len(rp_id) > 253 or not all(_LABEL.fullmatch(label) for label in rp_id.split(".")):
        raise ValueError(
            f"WEBAUTHN_RP_ID must be a host name such as aft.example.com "
            f"(no scheme, port or path), got {rp_id!r}"
        )
    return rp_id


def _validate_origin(origin: str, rp_id: str) -> str:
    """Return a normalised origin that may use the RP ID, else raise ValueError."""
    parts = urlsplit(origin)
    host = parts.hostname or ""
    if parts.scheme not in ("http", "https") or not host:
        raise ValueError(f"WEBAUTHN_ORIGINS entry must be http(s)://host[:port], got {origin!r}")
    if parts.path not in ("", "/") or parts.query or parts.fragment or parts.username:
        raise ValueError(f"WEBAUTHN_ORIGINS entry must not include a path, got {origin!r}")
    if parts.scheme == "http" and host not in _LOCAL_HOSTS:
        raise ValueError(
            f"WEBAUTHN_ORIGINS entry {origin!r} uses http. Browsers only allow passkeys "
            f"over https (or http://localhost)."
        )
    if host != rp_id and not host.endswith("." + rp_id):
        raise ValueError(
            f"WEBAUTHN_ORIGINS entry {origin!r} is not on WEBAUTHN_RP_ID {rp_id!r} "
            f"or one of its subdomains"
        )
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{host}{port}"


def read_webauthn_settings() -> WebAuthnSettings | None:
    """Return passkey settings, or None when passkeys are not configured.

    Raises:
        ValueError: If a setting is present but invalid.
    """
    rp_id = os.environ.get("WEBAUTHN_RP_ID", "").strip()
    if not rp_id:
        return None
    rp_id = _validate_rp_id(rp_id)

    rp_name = os.environ.get("WEBAUTHN_RP_NAME", "").strip() or DEFAULT_RP_NAME
    if len(rp_name) > MAX_RP_NAME_LENGTH:
        raise ValueError(f"WEBAUTHN_RP_NAME must be at most {MAX_RP_NAME_LENGTH} characters")

    raw_origins = os.environ.get("WEBAUTHN_ORIGINS", "").strip()
    entries = [o.strip() for o in raw_origins.split(",") if o.strip()] or [f"https://{rp_id}"]
    origins = tuple(dict.fromkeys(_validate_origin(o, rp_id) for o in entries))

    if not os.environ.get("REDIS_URL", "").strip():
        raise ValueError("Passkeys (WEBAUTHN_RP_ID) require REDIS_URL to be set")

    return WebAuthnSettings(rp_id=rp_id, rp_name=rp_name, origins=origins)
