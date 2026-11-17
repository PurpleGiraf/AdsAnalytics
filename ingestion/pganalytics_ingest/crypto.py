"""AES-256-GCM encryption for per-client tokens in reporting.connection_secrets.

Wire format (must match web/lib/crypto.ts byte for byte):

    base64( nonce (12 bytes) || ciphertext || tag (16 bytes) )

Standard base64 with padding. The key version is stored next to the ciphertext in
connection_secrets.key_version, not inside the blob.

Associated data: callers storing a connection secret pass the connection's UUID (as its
canonical lowercase string, UTF-8) as `associated_data`. That binds a ciphertext to its
row, so copying one connection's secret onto another connection fails to decrypt.

Key rotation: PGA_ENCRYPTION_KEY is the current key, PGA_ENCRYPTION_KEY_VERSION its
version. Old keys go in PGA_ENCRYPTION_KEYS_PREVIOUS ("1:<base64>,2:<base64>") until
every row has been re-encrypted with the current key. See docs/04-runbook.md.
"""

from __future__ import annotations

import base64
import binascii
import os
from dataclasses import dataclass, field

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from pganalytics_ingest.settings import Settings

NONCE_BYTES = 12
TAG_BYTES = 16
KEY_BYTES = 32


class CryptoError(Exception):
    """Raised for bad keys or ciphertext. Messages never include key or plaintext."""


def _decode_key(encoded: str, label: str) -> bytes:
    try:
        key = base64.b64decode(encoded.strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise CryptoError(f"{label} is not valid base64") from exc
    if len(key) != KEY_BYTES:
        raise CryptoError(f"{label} must decode to {KEY_BYTES} bytes, got {len(key)}")
    return key


def generate_key() -> str:
    """A new base64 key, same as scripts/gen-key.sh."""
    return base64.b64encode(os.urandom(KEY_BYTES)).decode("ascii")


@dataclass(frozen=True)
class Keyring:
    current_version: int
    keys: dict[int, bytes] = field(repr=False)

    def __post_init__(self) -> None:
        if self.current_version not in self.keys:
            raise CryptoError("the current key version has no key")

    @classmethod
    def from_keys(cls, current_version: int, keys: dict[int, str]) -> Keyring:
        decoded = {v: _decode_key(k, f"key version {v}") for v, k in keys.items()}
        return cls(current_version=current_version, keys=decoded)

    @classmethod
    def from_settings(cls, settings: Settings) -> Keyring:
        if settings.pga_encryption_key is None:
            raise CryptoError("PGA_ENCRYPTION_KEY is not set")
        keys = {settings.pga_encryption_key_version: settings.pga_encryption_key.get_secret_value()}
        if settings.pga_encryption_keys_previous is not None:
            raw = settings.pga_encryption_keys_previous.get_secret_value()
            for entry in filter(None, (e.strip() for e in raw.split(","))):
                version, sep, key = entry.partition(":")
                if not sep or not version.strip().isdigit():
                    raise CryptoError("PGA_ENCRYPTION_KEYS_PREVIOUS must look like 1:<base64>")
                if int(version) == settings.pga_encryption_key_version:
                    raise CryptoError("a previous key reuses the current key version")
                keys[int(version)] = key
        return cls.from_keys(settings.pga_encryption_key_version, keys)

    def encrypt(self, plaintext: str, associated_data: bytes | None = None) -> tuple[str, int]:
        """Returns (base64 blob, key_version). Always uses the current key."""
        nonce = os.urandom(NONCE_BYTES)
        sealed = AESGCM(self.keys[self.current_version]).encrypt(
            nonce, plaintext.encode("utf-8"), associated_data
        )
        return base64.b64encode(nonce + sealed).decode("ascii"), self.current_version

    def decrypt(self, blob: str, key_version: int, associated_data: bytes | None = None) -> str:
        key = self.keys.get(key_version)
        if key is None:
            raise CryptoError(f"no key loaded for key version {key_version}")
        try:
            raw = base64.b64decode(blob, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise CryptoError("ciphertext is not valid base64") from exc
        if len(raw) < NONCE_BYTES + TAG_BYTES:
            raise CryptoError("ciphertext is too short")
        nonce, sealed = raw[:NONCE_BYTES], raw[NONCE_BYTES:]
        try:
            return AESGCM(key).decrypt(nonce, sealed, associated_data).decode("utf-8")
        except InvalidTag as exc:
            raise CryptoError(
                "could not decrypt: wrong key, wrong associated data, or tampered ciphertext"
            ) from exc

    def needs_reencrypt(self, key_version: int) -> bool:
        return key_version != self.current_version
