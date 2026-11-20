"""Encryption of provider tokens at rest (AES-256-GCM).

Each value is bound to its user and provider as associated data, so a ciphertext copied into
another row does not decrypt. The format carries a version prefix ("v1:") so the key or the
algorithm can be rotated later without guessing what an old value is.
"""

import base64
import binascii
import os
import uuid

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

VERSION = "v1"
NONCE_BYTES = 12


class TokenKeyMissingError(RuntimeError):
    """INTEGRATIONS_TOKEN_KEY is not configured: no provider account can be connected."""


class TokenDecryptionError(RuntimeError):
    """A stored token cannot be decrypted (wrong key, or the value was moved or tampered with)."""


def _key(raw: str | None) -> bytes:
    if not raw:
        raise TokenKeyMissingError("INTEGRATIONS_TOKEN_KEY is not set")
    try:
        key = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as error:
        raise TokenKeyMissingError("INTEGRATIONS_TOKEN_KEY is not valid base64") from error
    if len(key) != 32:
        raise TokenKeyMissingError("INTEGRATIONS_TOKEN_KEY must decode to 32 bytes")
    return key


class TokenCipher:
    """Encrypts with the current key; decrypts with the current key or any previous one, so the
    key can be rotated without downtime (INTEGRATIONS_TOKEN_PREVIOUS_KEYS, then
    `python -m app.cli rotate-token-key`)."""

    def __init__(self, key: bytes, previous: list[bytes] | None = None) -> None:
        self._aead = AESGCM(key)
        self._readers = [self._aead, *(AESGCM(k) for k in previous or [])]

    @classmethod
    def from_settings(cls) -> "TokenCipher":
        settings = get_settings()
        return cls(
            _key(settings.integrations_token_key),
            [_key(raw) for raw in settings.integrations_token_previous_keys],
        )

    @staticmethod
    def _context(user_id: uuid.UUID, provider: str) -> bytes:
        return f"{user_id}:{provider}".encode()

    def encrypt(self, plaintext: str, user_id: uuid.UUID, provider: str) -> str:
        nonce = os.urandom(NONCE_BYTES)
        sealed = self._aead.encrypt(nonce, plaintext.encode(), self._context(user_id, provider))
        return f"{VERSION}:{base64.b64encode(nonce + sealed).decode()}"

    def decrypt(self, value: str, user_id: uuid.UUID, provider: str) -> str:
        version, _, payload = value.partition(":")
        if version != VERSION:
            raise TokenDecryptionError(f"unknown token format {version!r}")
        try:
            raw = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError) as error:
            raise TokenDecryptionError("stored token cannot be decrypted") from error
        for reader in self._readers:
            try:
                plain = reader.decrypt(
                    raw[:NONCE_BYTES], raw[NONCE_BYTES:], self._context(user_id, provider)
                )
            except (ValueError, InvalidTag):
                continue
            return plain.decode()
        raise TokenDecryptionError("stored token cannot be decrypted")

    def is_current(self, value: str, user_id: uuid.UUID, provider: str) -> bool:
        """Whether `value` is encrypted with the current key (rotation progress)."""
        _, _, payload = value.partition(":")
        try:
            raw = base64.b64decode(payload, validate=True)
            context = self._context(user_id, provider)
            self._aead.decrypt(raw[:NONCE_BYTES], raw[NONCE_BYTES:], context)
        except (binascii.Error, ValueError, InvalidTag):
            return False
        return True


def configured() -> bool:
    try:
        _key(get_settings().integrations_token_key)
    except TokenKeyMissingError:
        return False
    return True
