"""A minimal software WebAuthn authenticator for API tests.

Produces the same JSON a browser sends after navigator.credentials.create()
and .get() (binary values base64url-encoded), signed with a real P-256 key, so
passkey endpoints can be tested through the API without a browser.
"""

import base64
import hashlib
import json
import os
import struct

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

FLAG_UP = 0x01  # user present
FLAG_UV = 0x04  # user verified
FLAG_BE = 0x08  # backup eligible
FLAG_BS = 0x10  # backed up
FLAG_AT = 0x40  # attested credential data included


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class SoftAuthenticator:
    """One passkey held by a software authenticator.

    Args:
        rp_id: The relying party ID the passkey is created for.
        origin: The page origin the browser would report.
        synced: Report the passkey as backed up, like a synced passkey.
    """

    def __init__(self, rp_id: str, origin: str, synced: bool = False):
        self.rp_id = rp_id
        self.origin = origin
        self.synced = synced
        self.private_key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(32)
        self.user_handle = None
        self.sign_count = 0

    def _flags(self, user_verified: bool, attested: bool = False) -> int:
        flags = FLAG_UP
        if user_verified:
            flags |= FLAG_UV
        if self.synced:
            flags |= FLAG_BE | FLAG_BS
        if attested:
            flags |= FLAG_AT
        return flags

    def _cose_public_key(self) -> bytes:
        numbers = self.private_key.public_key().public_numbers()
        return cbor2.dumps({
            1: 2,  # kty: EC2
            3: -7,  # alg: ES256
            -1: 1,  # crv: P-256
            -2: numbers.x.to_bytes(32, "big"),
            -3: numbers.y.to_bytes(32, "big"),
        })

    def _client_data(self, ceremony: str, challenge: str, origin: str | None) -> bytes:
        return json.dumps({
            "type": ceremony,
            "challenge": challenge,
            "origin": origin or self.origin,
            "crossOrigin": False,
        }).encode("utf-8")

    def create(self, options: dict, *, user_verified: bool = True,
               origin: str | None = None, rp_id: str | None = None) -> dict:
        """Return a registration credential for server-issued creation options."""
        self.user_handle = options["user"]["id"]
        client_data = self._client_data("webauthn.create", options["challenge"], origin)
        attested_data = (
            bytes(16)  # AAGUID: none
            + struct.pack(">H", len(self.credential_id))
            + self.credential_id
            + self._cose_public_key()
        )
        auth_data = (
            hashlib.sha256((rp_id or self.rp_id).encode()).digest()
            + bytes([self._flags(user_verified, attested=True)])
            + struct.pack(">I", self.sign_count)
            + attested_data
        )
        attestation_object = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {
            "id": b64url(self.credential_id),
            "rawId": b64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64url(client_data),
                "attestationObject": b64url(attestation_object),
                "transports": ["internal"],
            },
            "clientExtensionResults": {},
        }

    def get(self, options: dict, *, user_verified: bool = True, origin: str | None = None,
            user_handle: str | None = None, sign_count: int | None = None) -> dict:
        """Return an authentication credential for server-issued request options."""
        if sign_count is not None:
            self.sign_count = sign_count
        elif not self.synced:
            self.sign_count += 1
        client_data = self._client_data("webauthn.get", options["challenge"], origin)
        auth_data = (
            hashlib.sha256(self.rp_id.encode()).digest()
            + bytes([self._flags(user_verified)])
            + struct.pack(">I", self.sign_count)
        )
        signature = self.private_key.sign(
            auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256())
        )
        return {
            "id": b64url(self.credential_id),
            "rawId": b64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64url(client_data),
                "authenticatorData": b64url(auth_data),
                "signature": b64url(signature),
                "userHandle": user_handle if user_handle is not None else self.user_handle,
            },
            "clientExtensionResults": {},
        }
