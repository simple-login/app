import os
from io import BytesIO

import pgpy
from pgpy import PGPMessage

from app.config import ROOT_DIR
from app.pgp_utils import (
    load_public_key,
    gpg,
    encrypt_file,
    encrypt_file_with_pgpy,
    sign_data,
    sign_data_with_pgpy,
)


def test_load_public_key():
    public_key_path = os.path.join(ROOT_DIR, "local_data/public-pgp.asc")
    public_key = open(public_key_path).read()
    load_public_key(public_key)
    assert len(gpg.list_keys()) == 1


def test_encrypt():
    public_key_path = os.path.join(ROOT_DIR, "local_data/public-pgp.asc")
    public_key = open(public_key_path).read()
    fingerprint = load_public_key(public_key)
    secret = encrypt_file(BytesIO(b"abcd"), fingerprint)
    assert secret != ""


def test_encrypt_file_with_pgpy():
    encrypt_decrypt_text("heyhey")
    encrypt_decrypt_text("👍💪")
    encrypt_decrypt_text("éèù")
    encrypt_decrypt_text("片仮名")


def encrypt_decrypt_text(text: str):
    public_key_path = os.path.join(ROOT_DIR, "local_data/public-pgp.asc")
    public_key = open(public_key_path).read()

    encrypted: PGPMessage = encrypt_file_with_pgpy(text.encode(), public_key)

    # decrypt
    private_key_path = os.path.join(ROOT_DIR, "local_data/private-pgp.asc")
    private_key = open(private_key_path).read()
    priv = pgpy.PGPKey()
    priv.parse(private_key)
    decrypted = priv.decrypt(encrypted).message
    if type(decrypted) == str:
        assert decrypted == text
    elif type(decrypted) == bytearray:
        assert decrypted.decode() == text


def test_sign_data():
    assert sign_data("heyhey")
    assert sign_data(b"bytes")


def test_sign_data_with_pgpy():
    assert sign_data_with_pgpy("unicode")
    assert sign_data_with_pgpy(b"bytes")
