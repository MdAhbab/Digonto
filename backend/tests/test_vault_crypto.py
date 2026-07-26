"""Per-user vault key derivation.

The README states vault files are encrypted with per-user keys. They were not:
every DEK in the deployment was wrapped with one global `sha256(VAULT_MASTER_KEY)`,
so the documented isolation did not exist and nothing would have revealed that.
These tests pin the property down, including the transitional path that keeps
documents written under the old scheme readable.
"""

from __future__ import annotations

import os

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import Settings
from app.security import vault_crypto as vc


@pytest.fixture
def settings() -> Settings:
    return Settings(
        app_env="development",
        vault_master_key="test-master-secret-not-a-real-key",
        jwt_secret="x" * 40,
    )


def test_round_trip_with_the_owning_user(settings: Settings) -> None:
    plaintext = b"a passport scan's bytes"
    ct, wrapped, nonce = vc.encrypt_file(plaintext, user_id=7, settings=settings)
    assert ct != plaintext, "must not be stored in the clear"
    assert vc.decrypt_file(ct, wrapped, nonce, user_id=7, settings=settings) == plaintext


def test_another_user_cannot_unwrap_the_dek(settings: Settings) -> None:
    """The isolation property the README claims, made testable."""
    _ct, wrapped, _nonce = vc.encrypt_file(b"secret", user_id=7, settings=settings)
    with pytest.raises(InvalidTag):
        vc.unwrap_dek(wrapped, user_id=8, settings=settings)


def test_derived_keys_differ_per_user(settings: Settings) -> None:
    keys = {vc._user_key(i, settings) for i in range(25)}
    assert len(keys) == 25


def test_derived_key_is_stable_for_one_user(settings: Settings) -> None:
    """A key that changed between calls would make every document unreadable."""
    assert vc._user_key(7, settings) == vc._user_key(7, settings)


def test_derived_key_is_not_the_master_secret(settings: Settings) -> None:
    assert vc._user_key(7, settings) != settings.vault_master_key.encode()
    assert vc._user_key(7, settings) != vc._legacy_master_key(settings)


def test_a_different_master_secret_changes_every_derived_key() -> None:
    a = Settings(app_env="development", vault_master_key="secret-a", jwt_secret="x" * 40)
    b = Settings(app_env="development", vault_master_key="secret-b", jwt_secret="x" * 40)
    assert vc._user_key(7, a) != vc._user_key(7, b)


def test_legacy_wrapped_dek_is_still_readable(settings: Settings) -> None:
    """Documents encrypted before per-user wrapping must not become unreadable."""
    dek = vc.generate_dek()
    nonce = os.urandom(12)
    legacy = nonce + AESGCM(vc._legacy_master_key(settings)).encrypt(nonce, dek, None)
    assert vc.unwrap_dek(legacy, user_id=7, settings=settings) == dek


def test_garbage_fails_both_paths(settings: Settings) -> None:
    """The legacy fallback must not become a way to accept anything."""
    with pytest.raises(InvalidTag):
        vc.unwrap_dek(os.urandom(60), user_id=7, settings=settings)


def test_every_document_gets_its_own_dek(settings: Settings) -> None:
    a = vc.encrypt_file(b"same bytes", user_id=7, settings=settings)
    b = vc.encrypt_file(b"same bytes", user_id=7, settings=settings)
    assert a[0] != b[0], "identical plaintext must not produce identical ciphertext"
    assert a[1] != b[1] and a[2] != b[2]


def test_field_encryption_uses_the_document_dek(settings: Settings) -> None:
    dek = vc.generate_dek()
    blob = vc.encrypt_field("MD RAFIUL KARIM", dek)
    assert b"RAFIUL" not in blob
    assert vc.decrypt_field(blob, dek) == "MD RAFIUL KARIM"
