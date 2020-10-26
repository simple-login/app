import os
from io import BytesIO

import gnupg
from memory_profiler import memory_usage

from app.config import GNUPGHOME
from app.log import LOG
from app.models import Mailbox, Contact
from app.utils import random_string

gpg = gnupg.GPG(gnupghome=GNUPGHOME)
gpg.encoding = "utf-8"


class PGPException(Exception):
    pass


def load_public_key(public_key: str) -> str:
    """Load a public key into keyring and return the fingerprint. If error, raise Exception"""
    import_result = gpg.import_keys(public_key)
    try:
        return import_result.fingerprints[0]
    except Exception as e:
        raise PGPException("Cannot load key") from e


def hard_exit():
    pid = os.getpid()
    LOG.warning("kill pid %s", pid)
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
        mailbox = Mailbox.get_by(pgp_finger_print=fingerprint)
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
            # save the data for debugging
            data.seek(0)
            file_path = f"/tmp/{random_string(10)}.eml"
            with open(file_path, "wb") as f:
                f.write(data.getbuffer())

            raise PGPException(f"Cannot encrypt, status: {r.status}, {file_path}")

    return str(r)
