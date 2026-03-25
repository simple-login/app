import os
from io import BytesIO

import pgpy
import pytest
from pgpy import PGPMessage

from app.config import ROOT_DIR
from app.pgp_utils import (
    load_public_key,
    gpg,
    encrypt_file,
    encrypt_file_with_pgpy,
    sign_data,
    sign_data_with_pgpy,
    create_pgp_context,
    load_public_key_and_check,
)


@pytest.fixture
def public_key():
    public_key_path = os.path.join(ROOT_DIR, "local_data/public-pgp.asc")
    return open(public_key_path).read()


@pytest.fixture
def private_key():
    private_key_path = os.path.join(ROOT_DIR, "local_data/private-pgp.asc")
    return open(private_key_path).read()


@pytest.fixture
def ctx():
    return create_pgp_context()


class TestLegacyImplementation:
    """Tests for the legacy gnupg/pgpy implementation (force_use_rust=False)."""

    def test_load_public_key(self, public_key, ctx):
        load_public_key(public_key, ctx, force_use_rust=False)
        assert len(gpg.list_keys()) >= 1

    def test_encrypt(self, public_key, ctx):
        fingerprint = load_public_key(public_key, ctx, force_use_rust=False)
        secret = encrypt_file(BytesIO(b"abcd"), fingerprint, ctx, force_use_rust=False)
        assert secret != ""

    def test_encrypt_file_with_pgpy(self, public_key, private_key, ctx):
        for text in ["heyhey", "👍💪", "éèù", "片仮名"]:
            encrypted: PGPMessage = encrypt_file_with_pgpy(
                text.encode(), public_key, ctx, force_use_rust=False
            )
            # decrypt
            priv = pgpy.PGPKey()
            priv.parse(private_key)
            decrypted = priv.decrypt(encrypted).message
            if isinstance(decrypted, str):
                assert decrypted == text
            elif isinstance(decrypted, bytearray):
                assert decrypted.decode() == text

    def test_sign_data(self, ctx):
        assert sign_data("heyhey", ctx, force_use_rust=False)
        assert sign_data(b"bytes", ctx, force_use_rust=False)

    def test_sign_data_with_pgpy(self):
        assert sign_data_with_pgpy("unicode")
        assert sign_data_with_pgpy(b"bytes")

    def test_load_public_key_and_check(self, public_key, ctx):
        fingerprint = load_public_key_and_check(public_key, ctx, force_use_rust=False)
        assert fingerprint != ""


class TestRustImplementation:
    """Tests for the Rust sl-pgp implementation (force_use_rust=True)."""

    def test_load_public_key(self, public_key, ctx):
        fingerprint = load_public_key(public_key, ctx, force_use_rust=True)
        assert fingerprint != ""
        assert ctx.has_public_key(fingerprint)

    def test_encrypt(self, public_key, ctx):
        fingerprint = load_public_key(public_key, ctx, force_use_rust=True)
        secret = encrypt_file(BytesIO(b"abcd"), fingerprint, ctx, force_use_rust=True)
        assert secret != ""
        # The encrypted data should be armored PGP message
        assert "-----BEGIN PGP MESSAGE-----" in secret

    def test_encrypt_file_with_pgpy(self, public_key, private_key, ctx):
        """Test encryption using encrypt_with_key in Rust mode."""
        for text in ["heyhey", "👍💪", "éèù", "片仮名"]:
            encrypted = encrypt_file_with_pgpy(
                text.encode(), public_key, ctx, force_use_rust=True
            )
            assert isinstance(encrypted, str)
            assert "-----BEGIN PGP MESSAGE-----" in encrypted
            # Decrypt with pgpy to verify
            priv = pgpy.PGPKey()
            priv.parse(private_key)
            enc_msg = pgpy.PGPMessage.from_blob(encrypted)
            decrypted = priv.decrypt(enc_msg).message
            if isinstance(decrypted, str):
                assert decrypted == text
            elif isinstance(decrypted, (bytes, bytearray)):
                assert decrypted.decode() == text

    def test_sign_data(self, ctx):
        signature = sign_data("heyhey", ctx, force_use_rust=True)
        assert signature != ""
        assert "-----BEGIN PGP SIGNATURE-----" in signature

    def test_sign_data_bytes(self, ctx):
        signature = sign_data(b"bytes", ctx, force_use_rust=True)
        assert signature != ""
        assert "-----BEGIN PGP SIGNATURE-----" in signature

    def test_load_public_key_and_check(self, public_key, ctx):
        fingerprint = load_public_key_and_check(public_key, ctx, force_use_rust=True)
        assert fingerprint != ""

    def test_create_pgp_context(self):
        ctx = create_pgp_context()
        assert ctx is not None


class TestContextReuse:
    """Tests verifying that context reuse works correctly with Rust implementation."""

    def test_multiple_operations_same_context(self, public_key, ctx):
        """Test that multiple operations can share the same context."""
        # Load key
        fingerprint = load_public_key(public_key, ctx, force_use_rust=True)
        assert ctx.has_public_key(fingerprint)

        # Encrypt multiple times
        for i in range(3):
            data = f"test data {i}".encode()
            encrypted = encrypt_file(
                BytesIO(data), fingerprint, ctx, force_use_rust=True
            )
            assert "-----BEGIN PGP MESSAGE-----" in encrypted

    def test_key_loaded_in_context_is_available(self, public_key, ctx):
        """Test that a key loaded in one call is available in subsequent calls."""
        # Load key using load_public_key
        fingerprint = load_public_key(public_key, ctx, force_use_rust=True)

        # The key should be available in the context for encryption
        assert ctx.has_public_key(fingerprint)

        # Encryption should work without re-loading the key
        encrypted = encrypt_file(
            BytesIO(b"test"), fingerprint, ctx, force_use_rust=True
        )
        assert encrypted != ""


# Parametrized tests to run the same test with both implementations
@pytest.mark.parametrize("use_rust", [False, True])
class TestBothImplementations:
    """Tests that run with both implementations to verify compatibility."""

    def test_load_and_encrypt(self, public_key, ctx, use_rust):
        fingerprint = load_public_key(public_key, ctx, force_use_rust=use_rust)
        assert fingerprint != ""

        encrypted = encrypt_file(
            BytesIO(b"test data"), fingerprint, ctx, force_use_rust=use_rust
        )
        assert encrypted != ""
        assert "-----BEGIN PGP MESSAGE-----" in encrypted

    def test_sign(self, ctx, use_rust):
        signature = sign_data(b"data to sign", ctx, force_use_rust=use_rust)
        assert signature != ""
        assert "-----BEGIN PGP SIGNATURE-----" in signature
