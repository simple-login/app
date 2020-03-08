import gnupg

from app.config import GNUPGHOME

gpg = gnupg.GPG(gnupghome=GNUPGHOME)


class PGPException(Exception):
    pass


def load_public_key(public_key: str) -> str:
    """Load a public key into keyring and return the fingerprint. If error, raise Exception"""
    import_result = gpg.import_keys(public_key)
    try:
        return import_result.fingerprints[0]
    except Exception as e:
        raise PGPException("Cannot load key") from e


def encrypt(data: str, fingerprint: str) -> str:
    r = gpg.encrypt(data, fingerprint, always_trust=True)
    if not r.ok:
        raise PGPException("Cannot encrypt")

    return str(r)
