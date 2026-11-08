"""AES-256-GCM authenticated encryption for staged CSV uploads.

Blob layout: b"FL1" | 12-byte random nonce | ciphertext+16-byte GCM tag.
The associated data binds a blob to its owner and upload id, so a ciphertext copied
into another user's row fails authentication instead of decrypting.
"""
from __future__ import annotations

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

_MAGIC = b"FL1"
_NONCE_LEN = 12


class DecryptionError(Exception):
    pass


def associated_data(user_id: int, upload_id: str) -> bytes:
    return f"foliolens:csv:user={user_id}:upload={upload_id}".encode()


def encrypt(plaintext: bytes, aad: bytes, key: bytes | None = None) -> bytes:
    key = key or get_settings().csv_key_bytes()
    nonce = os.urandom(_NONCE_LEN)
    return _MAGIC + nonce + AESGCM(key).encrypt(nonce, plaintext, aad)


def decrypt(blob: bytes, aad: bytes, key: bytes | None = None) -> bytes:
    key = key or get_settings().csv_key_bytes()
    if len(blob) < len(_MAGIC) + _NONCE_LEN + 16 or not blob.startswith(_MAGIC):
        raise DecryptionError("Malformed ciphertext")
    nonce = blob[len(_MAGIC):len(_MAGIC) + _NONCE_LEN]
    try:
        return AESGCM(key).decrypt(nonce, blob[len(_MAGIC) + _NONCE_LEN:], aad)
    except InvalidTag as exc:
        raise DecryptionError("Ciphertext failed authentication") from exc
