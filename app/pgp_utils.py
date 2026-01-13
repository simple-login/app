import os
from io import BytesIO
from typing import Union

import gnupg
import pgpy
from memory_profiler import memory_usage
from pgpy import PGPMessage
from sl_pgp import PgpContext, PgpException

from app.config import GNUPGHOME, PGP_SENDER_PRIVATE_KEY, USE_RUST_PGP
from app.log import LOG
from app.models import Mailbox, Contact

gpg = gnupg.GPG(gnupghome=GNUPGHOME)
gpg.encoding = "utf-8"


class PGPException(Exception):
    pass


def load_public_key(
    public_key: str, ctx: PgpContext, force_use_rust: bool = False
) -> str:
    """Load a public key into keyring and return the fingerprint. If error, raise Exception"""
    if force_use_rust or USE_RUST_PGP:
        try:
            return ctx.load_public_key(public_key)
        except PgpException as e:
            raise PGPException("Cannot load key") from e
    else:
        try:
            import_result = gpg.import_keys(public_key)
            return import_result.fingerprints[0]
        except Exception as e:
            raise PGPException("Cannot load key") from e


def load_public_key_and_check(
    public_key: str, ctx: PgpContext, force_use_rust: bool = False
) -> str:
    """Same as load_public_key but will try an encryption using the new key.
    If the encryption fails, remove the newly created fingerprint.
    Return the fingerprint
    """
    if force_use_rust or USE_RUST_PGP:
        try:
            return ctx.load_public_key_and_check(public_key)
        except PgpException as e:
            raise PGPException("Cannot load key or encryption fails") from e
    else:
        try:
            import_result = gpg.import_keys(public_key)
            fingerprint = import_result.fingerprints[0]
        except Exception as e:
            raise PGPException("Cannot load key") from e
        else:
            dummy_data = BytesIO(b"test")
            try:
                encrypt_file(dummy_data, fingerprint, ctx)
            except Exception as e:
                LOG.w(
                    "Cannot encrypt using the imported key %s %s",
                    fingerprint,
                    public_key,
                )
                # remove the fingerprint
                gpg.delete_keys([fingerprint])
                raise PGPException("Encryption fails with the key") from e

            return fingerprint


def hard_exit():
    pid = os.getpid()
    LOG.w("kill pid %s", pid)
    os.kill(pid, 9)


def encrypt_file(
    data: BytesIO, fingerprint: str, ctx: PgpContext, force_use_rust: bool = False
) -> str:
    LOG.d("encrypt for %s", fingerprint)

    if force_use_rust or USE_RUST_PGP:
        try:
            # Read data from BytesIO
            data_bytes = data.read()
            # Check if the key is already loaded
            if not ctx.has_public_key(fingerprint):
                # Try to load the key from mailbox or contact
                mailbox = Mailbox.get_by(
                    pgp_finger_print=fingerprint, disable_pgp=False
                )
                if mailbox:
                    LOG.d("(re-)load public key for %s", mailbox)
                    ctx.load_public_key(mailbox.pgp_public_key)

                contact = Contact.get_by(pgp_finger_print=fingerprint)
                if contact:
                    LOG.d("(re-)load public key for %s", contact)
                    ctx.load_public_key(contact.pgp_public_key)

            return ctx.encrypt(data_bytes, fingerprint)
        except PgpException as e:
            raise PGPException(f"Cannot encrypt: {e}") from e
    else:
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
                load_public_key(mailbox.pgp_public_key, ctx)
                found = True

            # searching for the key in contact
            contact = Contact.get_by(pgp_finger_print=fingerprint)
            if contact:
                LOG.d("(re-)load public key for %s", contact)
                load_public_key(contact.pgp_public_key, ctx)
                found = True

            if found:
                LOG.d("retry to encrypt")
                data.seek(0)
                r = gpg.encrypt_file(data, fingerprint, always_trust=True)

            if not r.ok:
                raise PGPException(f"Cannot encrypt, status: {r.status}")

        return str(r)


def encrypt_file_with_pgpy(
    data: bytes, public_key: str, ctx: PgpContext, force_use_rust: bool = False
) -> Union[PGPMessage, str]:
    """Encrypt data using pgpy library or sl-pgp if USE_RUST_PGP is True.

    Returns:
        When USE_RUST_PGP is False: PGPMessage object
        When USE_RUST_PGP is True: str (armored ciphertext)
    """
    if force_use_rust or USE_RUST_PGP:
        try:
            return ctx.encrypt_with_key(data, public_key)
        except PgpException as e:
            raise PGPException(f"Cannot encrypt with key: {e}") from e
    else:
        key = pgpy.PGPKey()
        key.parse(public_key)
        msg = pgpy.PGPMessage.new(data, encoding="utf-8")
        r = key.encrypt(msg)

        return r


# Initialize signing key for legacy implementation
if PGP_SENDER_PRIVATE_KEY and not USE_RUST_PGP:
    _SIGN_KEY_ID = gpg.import_keys(PGP_SENDER_PRIVATE_KEY).fingerprints[0]


def create_pgp_context() -> PgpContext:
    """Create and configure a PgpContext for use in a request/process.

    Returns:
        A configured PgpContext.
    """
    ctx = PgpContext()
    return ctx


def sign_data(
    data: Union[str, bytes], ctx: PgpContext, force_use_rust: bool = False
) -> str:
    if force_use_rust or USE_RUST_PGP:
        # Ensure the signing key is loaded
        if PGP_SENDER_PRIVATE_KEY:
            ctx.set_signing_key(PGP_SENDER_PRIVATE_KEY)
        try:
            if isinstance(data, str):
                data = data.encode("utf-8")
            return ctx.sign_detached(data)
        except PgpException as e:
            raise PGPException(f"Cannot sign data: {e}") from e
    else:
        signature = str(gpg.sign(data, keyid=_SIGN_KEY_ID, detach=True))
        return signature


def sign_data_with_pgpy(data: Union[str, bytes]) -> str:
    """Sign data using pgpy library.

    Note: This function is legacy-only and is kept for fallback purposes.
    When USE_RUST_PGP is True, use sign_data() instead.
    """
    key = pgpy.PGPKey()
    key.parse(PGP_SENDER_PRIVATE_KEY)
    signature = str(key.sign(data))
    return signature
