import os
from io import BytesIO
from typing import Union

import gnupg
import pgpy
from memory_profiler import memory_usage
from pgpy import PGPMessage

from app.config import GNUPGHOME, PGP_SENDER_PRIVATE_KEY
from app.log import LOG
from app.models import Mailbox, Contact

gpg = gnupg.GPG(gnupghome=GNUPGHOME)
gpg.encoding = "utf-8"


class PGPException(Exception):
    pass


def load_public_key(public_key: str) -> str:
    """Load a public key into keyring and return the fingerprint. If error, raise Exception"""
    try:
        import_result = gpg.import_keys(public_key)
        return import_result.fingerprints[0]
    except Exception as e:
        raise PGPException("Cannot load key") from e


def load_public_key_and_check(public_key: str) -> str:
    """Same as load_public_key but will try an encryption using the new key.
    If the encryption fails, remove the newly created fingerprint.
    Return the fingerprint
    """
    try:
        import_result = gpg.import_keys(public_key)
        fingerprint = import_result.fingerprints[0]
    except Exception as e:
        raise PGPException("Cannot load key") from e
    else:
        dummy_data = BytesIO(b"test")
        try:
            encrypt_file(dummy_data, fingerprint)
        except Exception as e:
            LOG.w(
                "Cannot encrypt using the imported key %s %s", fingerprint, public_key
            )
            # remove the fingerprint
            gpg.delete_keys([fingerprint])
            raise PGPException("Encryption fails with the key") from e

        return fingerprint


def hard_exit():
    pid = os.getpid()
    LOG.w("kill pid %s", pid)
    os.kill(pid, 9)


def encrypt_file(data: BytesIO, fingerprint: str) -> str:
    LOG.d("encrypt for %s", fingerprint)
    mem_usage = memory_usage(-1, interval=1, timeout=1)[0]
    LOG.d("mem_usage %s", mem_usage)

    r = gpg.encrypt_file(data, fingerprint, always_trust=True)
    if not r.ok:
        # maybe the fingerprint is not loaded on this host, try to load it
        found = False
        # searching for the key in mailbox
        mailbox = Mailbox.get_by(pgp_finger_print=fingerprint, disable_pgp=False)
        if mailbox:
            LOG.d("(re-)load public key for %s", mailbox)
            load_public_key(mailbox.pgp_public_key)
            found = True

        # searching for the key in contact
        contact = Contact.get_by(pgp_finger_print=fingerprint)
        if contact:
            LOG.d("(re-)load public key for %s", contact)
            load_public_key(contact.pgp_public_key)
            found = True

        if found:
            LOG.d("retry to encrypt")
            data.seek(0)
            r = gpg.encrypt_file(data, fingerprint, always_trust=True)

        if not r.ok:
            raise PGPException(f"Cannot encrypt, status: {r.status}")

    return str(r)


def encrypt_file_with_pgpy(data: bytes, public_key: str) -> PGPMessage:
    key = pgpy.PGPKey()
    key.parse(public_key)
    msg = pgpy.PGPMessage.new(data, encoding="utf-8")
    r = key.encrypt(msg)

    return r


if PGP_SENDER_PRIVATE_KEY:
    _SIGN_KEY_ID = gpg.import_keys(PGP_SENDER_PRIVATE_KEY).fingerprints[0]


def sign_data(data: Union[str, bytes]) -> str:
    signature = str(gpg.sign(data, keyid=_SIGN_KEY_ID, detach=True))
    return signature


def sign_data_with_pgpy(data: Union[str, bytes]) -> str:
    key = pgpy.PGPKey()
    key.parse(PGP_SENDER_PRIVATE_KEY)
    signature = str(key.sign(data))
    return signature
