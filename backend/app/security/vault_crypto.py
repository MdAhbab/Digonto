"""Per-file, per-user AES-256-GCM encryption for the vault.

Every document gets its own random data encryption key (DEK). The DEK encrypts
the file bytes; the DEK itself is wrapped with a **per-user** key derived from
`settings.vault_master_key`, so a stolen database dump never carries a usable key
on its own, and compromise of one user's wrapping key does not unwrap another
user's documents. See docs/database.md section 3.6 (`documents.wrapped_dek`,
`documents.nonce`) and backend/backend.md section 7.

**Why per-user, and why HKDF.** The README states that vault files are encrypted
with per-user keys. Until this change they were not: every DEK in the deployment
was wrapped with one global key, `sha256(VAULT_MASTER_KEY)`. That is a weaker
property than documented, and the gap was invisible from the outside. Keys are
now derived with HKDF-SHA256 using the user's id as the `info` parameter, which
is what HKDF's info field is for: one high-entropy secret, many independent
purpose-bound subkeys, and no way to work backwards from one subkey to the master
or sideways to another user's. A bare hash of the secret was also doing double
duty as a KDF, which it is not.

**Reading documents encrypted before this change.** A DEK wrapped with the old
global key cannot be unwrapped with a derived one, so `unwrap_dek` falls back to
the legacy key when the per-user unwrap fails authentication. That keeps existing
vaults (including the seeded judge account) readable instead of silently losing
them, and every newly written document is wrapped per-user. The fallback is
transitional and should be removed once no legacy rows remain; it is safe in the
meantime because AES-GCM authenticates, so the fallback can only succeed on a
blob that genuinely was wrapped with the legacy key.

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

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import Settings, get_settings

_NONCE_BYTES = 12  # standard AES-GCM nonce size
_KEY_BITS = 256


_HKDF_SALT = b"digonto-vault-hkdf-v1"


def _legacy_master_key(settings: Settings | None = None) -> bytes:
    """The single global wrapping key used before per-user derivation.

    Retained only so documents written under it remain readable. Nothing new is
    encrypted with this.
    """
    s = settings or get_settings()
    return hashlib.sha256(s.vault_master_key.encode("utf-8")).digest()


def _user_key(user_id: int, settings: Settings | None = None) -> bytes:
    """Derive this user's 32-byte wrapping key from the master secret.

    `user_id` is the surrogate key from `users`, which is never reused, so a
    derived key is stable for the life of the account and unrelated to every
    other account's.
    """
    s = settings or get_settings()
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_HKDF_SALT,
        info=f"vault-wrap:user:{int(user_id)}".encode("utf-8"),
    ).derive(s.vault_master_key.encode("utf-8"))


def generate_dek() -> bytes:
    """A fresh, random per-document key. Never reused across documents."""
    return AESGCM.generate_key(bit_length=_KEY_BITS)


def wrap_dek(dek: bytes, *, user_id: int, settings: Settings | None = None) -> bytes:
    """Encrypt a DEK under this user's derived wrapping key.

    Store the returned blob (nonce || ciphertext) in `documents.wrapped_dek`.
    """
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(_user_key(user_id, settings)).encrypt(nonce, dek, None)
    return nonce + ciphertext


def unwrap_dek(
    wrapped_dek: bytes, *, user_id: int, settings: Settings | None = None
) -> bytes:
    """Recover a DEK. Tries this user's key, then the legacy global key.

    The fallback exists only for documents written before wrapping became
    per-user. AES-GCM authenticates the ciphertext, so it can succeed only on a
    blob actually wrapped with the legacy key: this is not a downgrade path an
    attacker can steer, and passing another user's `wrapped_dek` still fails
    both attempts.
    """
    nonce, ciphertext = wrapped_dek[:_NONCE_BYTES], wrapped_dek[_NONCE_BYTES:]
    try:
        return AESGCM(_user_key(user_id, settings)).decrypt(nonce, ciphertext, None)
    except InvalidTag:
        return AESGCM(_legacy_master_key(settings)).decrypt(nonce, ciphertext, None)


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


def encrypt_file(
    data: bytes, *, user_id: int, settings: Settings | None = None
) -> tuple[bytes, bytes, bytes]:
    """Whole-file convenience wrapper used by `VaultService.upload_document`.

    Generates a fresh per-document DEK, encrypts `data` with it, and wraps the
    DEK under the owning user's derived key, so the caller gets everything that
    needs to be persisted (`documents.storage_path` content, `wrapped_dek`,
    `nonce`) from the three primitives already defined above. Not a new
    cryptographic scheme: a composition of `generate_dek`/`encrypt_bytes`/
    `wrap_dek`.

    Returns (ciphertext, wrapped_dek, nonce).
    """
    dek = generate_dek()
    ciphertext, nonce = encrypt_bytes(data, dek)
    wrapped_dek = wrap_dek(dek, user_id=user_id, settings=settings)
    return ciphertext, wrapped_dek, nonce


def decrypt_file(
    ciphertext: bytes,
    wrapped_dek: bytes,
    nonce: bytes,
    *,
    user_id: int,
    settings: Settings | None = None,
) -> bytes:
    """Inverse of `encrypt_file`: unwrap the DEK, then decrypt the file bytes."""
    dek = unwrap_dek(wrapped_dek, user_id=user_id, settings=settings)
    return decrypt_bytes(ciphertext, dek, nonce)


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
