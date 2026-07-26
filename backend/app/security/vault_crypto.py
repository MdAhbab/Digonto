"""Per-file AES-256-GCM encryption for the vault.

Every document gets its own random data encryption key (DEK). The DEK
encrypts the file bytes; the DEK itself is wrapped with a master key derived
from `settings.vault_master_key` so a stolen database dump never carries a
usable key on its own. See docs/database.md section 3.6
(`documents.wrapped_dek`, `documents.nonce`) and backend/backend.md section 7.

Nonce layout is a judgement call worth recording. `documents.nonce` is a
dedicated column, used for the nonce that encrypts the file's bytes with its
DEK. `document_fields` has no equivalent column (many small values per
document, one row each), so `encrypt_field`/`decrypt_field` and
`wrap_dek`/`unwrap_dek` instead prepend the 12-byte nonce to the ciphertext
and store the concatenation as a single BLOB, matching what those tables'
columns actually look like.
"""

from __future__ import annotations

import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import Settings, get_settings

_NONCE_BYTES = 12  # standard AES-GCM nonce size
_KEY_BITS = 256


def _master_key(settings: Settings | None = None) -> bytes:
    # settings.vault_master_key is an arbitrary-length secret string (see
    # app/config.py, generated with secrets.token_urlsafe in development).
    # Hashing it gives a fixed 32-byte AES-256 key regardless of how the
    # operator generated the underlying secret.
    s = settings or get_settings()
    return hashlib.sha256(s.vault_master_key.encode("utf-8")).digest()


def generate_dek() -> bytes:
    """A fresh, random per-document key. Never reused across documents."""
    return AESGCM.generate_key(bit_length=_KEY_BITS)


def wrap_dek(dek: bytes, *, settings: Settings | None = None) -> bytes:
    """Encrypt a DEK under the master key.

    Store the returned blob (nonce || ciphertext) in `documents.wrapped_dek`.
    """
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(_master_key(settings)).encrypt(nonce, dek, None)
    return nonce + ciphertext


def unwrap_dek(wrapped_dek: bytes, *, settings: Settings | None = None) -> bytes:
    nonce, ciphertext = wrapped_dek[:_NONCE_BYTES], wrapped_dek[_NONCE_BYTES:]
    return AESGCM(_master_key(settings)).decrypt(nonce, ciphertext, None)


def encrypt_bytes(data: bytes, dek: bytes) -> tuple[bytes, bytes]:
    """Encrypt file content with its own DEK.

    Returns (ciphertext, nonce). The ciphertext is written to the path stored
    in `documents.storage_path`; the nonce is stored in `documents.nonce`.
    """
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(dek).encrypt(nonce, data, None)
    return ciphertext, nonce


def decrypt_bytes(ciphertext: bytes, dek: bytes, nonce: bytes) -> bytes:
    return AESGCM(dek).decrypt(nonce, ciphertext, None)


def encrypt_field(value: str, dek: bytes) -> bytes:
    """Encrypt one extracted field value for `document_fields.value_enc`.

    Uses the same DEK as the parent document (already unwrapped by whoever is
    processing that document), so no separate key management is needed for
    fields. Returns nonce || ciphertext as a single blob.
    """
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(dek).encrypt(nonce, value.encode("utf-8"), None)
    return nonce + ciphertext


def decrypt_field(value_enc: bytes, dek: bytes) -> str:
    nonce, ciphertext = value_enc[:_NONCE_BYTES], value_enc[_NONCE_BYTES:]
    return AESGCM(dek).decrypt(nonce, ciphertext, None).decode("utf-8")


def normalised_value_hash(text: str) -> str:
    """A comparison key for `document_fields.value_hash`.

    Case-folded and whitespace-collapsed before hashing, so 'MD RAHIM UDDIN'
    on a passport and 'md   rahim uddin' on a bank statement hash identically.
    Punctuation is deliberately left alone: 'MD.' and 'MD' are not folded
    together, because collapsing that too would risk matching two different
    names, which is worse than missing a formatting variant. Prohori compares
    these hashes to catch a name mismatch across a student's own documents
    without ever decrypting either field (docs/database.md section 3.6).
    """
    normalised = " ".join(text.strip().split()).casefold()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()
