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
    def __init__(self, key: bytes) -> None:
        self._aead = AESGCM(key)

    @classmethod
    def from_settings(cls) -> "TokenCipher":
        return cls(_key(get_settings().integrations_token_key))

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
            plain = self._aead.decrypt(
                raw[:NONCE_BYTES], raw[NONCE_BYTES:], self._context(user_id, provider)
            )
        except (binascii.Error, ValueError, InvalidTag) as error:
            raise TokenDecryptionError("stored token cannot be decrypted") from error
        return plain.decode()


def configured() -> bool:
    try:
        _key(get_settings().integrations_token_key)
    except TokenKeyMissingError:
        return False
    return True
