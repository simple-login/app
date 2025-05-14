import hmac
import json
import secrets
from hashlib import sha256
from typing import List, Dict, Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes as crypto_hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app import config
from app.db import Session
from app.log import LOG
from app.models import User, Alias, Mailbox, AbuserData, AbuserLookup


def _derive_encryption_key(master_key: bytes, user_id: int) -> bytes:
    if user_id is None or not isinstance(user_id, int) or user_id <= 0:
        raise ValueError("User ID must be a valid positive integer for key derivation.")

    hkdf_info = (config.HKDF_INFO_TEMPLATE % str(user_id)).encode("utf-8")
    hkdf = HKDF(
        algorithm=crypto_hashes.SHA256(),
        length=32,
        salt=None,
        info=hkdf_info,
        backend=default_backend(),
    )

    return hkdf.derive(master_key)


def check_if_abuser_email(new_address: str) -> Optional[AbuserLookup]:
    """
    Returns False, if the given address (after hashing) is found in abuser_lookup.
    """
    mac_key_bytes = config.MAC_KEY
    check_hmac = hmac.new(
        mac_key_bytes, new_address.encode("utf-8"), sha256
    ).hexdigest()

    return (
        AbuserLookup.filter(AbuserLookup.hashed_address == check_hmac).limit(1).first()
    )


def archive_abusive_user(user: User) -> None:
    """
    Archive the given abusive user's data and update blocklist/lookup tables.
    """
    if not user.email:
        raise ValueError(f"User ID {user.id} must have a primary email to be archived.")

    try:
        primary_email: str = user.email
        aliases: List[Alias] = Alias.filter_by(user_id=user.id).all()
        mailboxes: List[Mailbox] = Mailbox.filter_by(user_id=user.id).all()
        bundle = {
            "account_id": user.id,
            "email": primary_email,
            "user_created_at": user.created_at.isoformat() if user.created_at else None,
            "aliases": [
                {
                    "address": alias.email,
                    "created_at": alias.created_at.isoformat()
                    if alias.created_at
                    else None,
                }
                for alias in aliases
            ],
            "mailboxes": [
                {
                    "address": mailbox.email,
                    "created_at": mailbox.created_at.isoformat()
                    if mailbox.created_at
                    else None,
                }
                for mailbox in mailboxes
            ],
        }
        bundle_json_bytes = json.dumps(bundle, sort_keys=True).encode("utf-8")
        derived_enc_key = _derive_encryption_key(config.MASTER_ENC_KEY, user.id)
        aesgcm = AESGCM(derived_enc_key)
        nonce = secrets.token_bytes(12)
        aad_bytes = config.AEAD_AAD_DATA.encode("utf-8")
        encrypted_bundle_data = nonce + aesgcm.encrypt(
            nonce, bundle_json_bytes, aad_bytes
        )
        abuser_data_entry = AbuserData(
            user_id=user.id, encrypted_bundle=encrypted_bundle_data
        )

        Session.add(abuser_data_entry)
        Session.flush()

        blob_id = abuser_data_entry.id
        all_identifiers = (
            [primary_email] + [a.email for a in aliases] + [m.email for m in mailboxes]
        )
        seen_identifiers = set()
        mac_key_bytes = config.MAC_KEY

        for identifier_address in all_identifiers:
            if not identifier_address or identifier_address in seen_identifiers:
                continue

            seen_identifiers.add(identifier_address)

            identifier_hmac = hmac.new(
                mac_key_bytes, identifier_address.lower().encode("utf-8"), sha256
            ).hexdigest()
            abuser_lookup_entry = AbuserLookup(
                hashed_address=identifier_hmac, abuser_data_id=blob_id
            )

            Session.add(abuser_lookup_entry)

        Session.commit()
    except Exception:
        Session.rollback()
        raise


def unarchive_abusive_user(user_id: int) -> None:
    """
    Fully remove abuser archive and lookup data for a given user_id.
    This reverses the effects of archive_abusive_user().
    """
    abuser_data_entry = AbuserData.filter_by(user_id=user_id).first()

    if not abuser_data_entry:
        LOG.e("No abuser data found for user %s", user_id)
        return

    Session.delete(abuser_data_entry)
    Session.commit()


def get_abuser_bundles_for_address(target_address: str) -> List[Dict]:
    """
    Given a target address (email, alias, or mailbox address),
    return all decrypted bundle_json's that reference this address.
    """
    if not target_address:
        return []

    mac_key_bytes = config.MAC_KEY
    master_key_bytes = config.MASTER_ENC_KEY

    target_hmac = hmac.new(
        mac_key_bytes, target_address.encode("utf-8"), sha256
    ).hexdigest()

    lookup_entries: List[AbuserLookup] = AbuserLookup.filter(
        AbuserLookup.hashed_address == target_hmac
    ).all()

    if not lookup_entries:
        return []

    decrypted_bundles: List[Dict] = []
    aad_bytes = config.AEAD_AAD_DATA.encode("utf-8")

    for entry in lookup_entries:
        blob_id = entry.abuser_data_id
        abuser_data_record: Optional[AbuserData] = AbuserData.filter_by(
            id=blob_id
        ).first()

        if not abuser_data_record:
            LOG.e(f"Error: No AbuserData found for blob_id {blob_id}")
            continue

        owner_user_id = abuser_data_record.user_id
        encrypted_bundle_data = abuser_data_record.encrypted_bundle

        try:
            derived_enc_key = _derive_encryption_key(master_key_bytes, owner_user_id)
            nonce = encrypted_bundle_data[:12]
            ciphertext = encrypted_bundle_data[12:]
            aesgcm = AESGCM(derived_enc_key)
            decrypted_bundle_json_bytes = aesgcm.decrypt(nonce, ciphertext, aad_bytes)
            bundle = json.loads(decrypted_bundle_json_bytes.decode("utf-8"))
            decrypted_bundles.append(bundle)
        except InvalidTag:
            LOG.e(f"Error: AEAD decryption failed for blob_id {blob_id}. InvalidTag.")
            continue
        except ValueError as ve:
            LOG.e(f"Error: Decryption ValueError for blob_id {blob_id}: {ve}")
            continue
        except Exception as e:
            LOG.e(f"Error: General decryption exception for blob_id {blob_id}: {e}")
            continue

    return decrypted_bundles
