import os
from io import BytesIO

import gnupg
from memory_profiler import memory_usage

from app.config import GNUPGHOME
from app.log import LOG
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

    # todo
    if mem_usage > 300:
        LOG.error("Force exit")
        hard_exit()

    r = gpg.encrypt_file(data, fingerprint, always_trust=True)
    if not r.ok:
        LOG.error("Try encrypt again %s", fingerprint)
        r = gpg.encrypt_file(data, fingerprint, always_trust=True)
        if not r.ok:
            # save the content for debugging
            random_file_name = random_string(20) + ".eml"
            full_path = f"/tmp/{random_file_name}"
            with open(full_path, "wb") as f:
                f.write(data.getbuffer())
            LOG.error("PGP fail - log to %s", full_path)
            raise PGPException("Cannot encrypt")

    return str(r)
