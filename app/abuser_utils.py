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

from app import config, constants
from app.abuser_audit_log_utils import emit_abuser_audit_log, AbuserAuditLogAction
from app.db import Session
from app.log import LOG
from app.models import User, Alias, Mailbox, AbuserData, AbuserLookup


def _derive_key_for_identifier(master_key: bytes, identifier_address: str) -> bytes:
    if not identifier_address or not isinstance(identifier_address, str):
        raise ValueError(
            "Identifier address must be a non-empty string for key derivation."
        )

    normalized_identifier = identifier_address.lower()
    hkdf_info = (constants.HKDF_INFO_TEMPLATE % normalized_identifier).encode("utf-8")
    hkdf = HKDF(
        algorithm=crypto_hashes.SHA256(),
        length=32,
        salt=config.ABUSER_HKDF_SALT,
        info=hkdf_info,
        backend=default_backend(),
    )

    return hkdf.derive(master_key)


def check_if_abuser_email(new_address: str) -> Optional[AbuserLookup]:
    """
    Returns AbuserLookup, if the given address (after hashing) is found in abuser_lookup.
    """
    mac_key_bytes = config.MAC_KEY
    normalized_address = new_address.lower()
    check_hmac = hmac.new(
        mac_key_bytes, normalized_address.encode("utf-8"), sha256
    ).hexdigest()

    return (
        AbuserLookup.filter(AbuserLookup.hashed_address == check_hmac).limit(1).first()
    )


def store_abuse_data(user: User) -> None:
    """
    Archive the given abusive user's data and update blocklist/lookup tables.
    """
    if not user.email:
        raise ValueError(f"User ID {user.id} must have a primary email to be archived.")

    try:
        primary_email: str = user.email.lower()
        aliases: List[Alias] = (
            Alias.filter_by(user_id=user.id)
            .enable_eagerloads(False)
            .yield_per(500)
            .all()
        )
        mailboxes: List[Mailbox] = Mailbox.filter_by(user_id=user.id).all()
        bundle = {
            "account_id": str(user.id),
            "email": primary_email,
            "user_created_at": user.created_at.isoformat() if user.created_at else None,
            "aliases": [
                {
                    "address": alias.email.lower() if alias.email else None,
                    "created_at": alias.created_at.isoformat()
                    if alias.created_at
                    else None,
                }
                for alias in aliases
                if alias.email
            ],
            "mailboxes": [
                {
                    "address": mailbox.email.lower() if mailbox.email else None,
                    "created_at": mailbox.created_at.isoformat()
                    if mailbox.created_at
                    else None,
                }
                for mailbox in mailboxes
                if mailbox.email
            ],
        }
        bundle_json_bytes = json.dumps(bundle, sort_keys=True).encode("utf-8")
        k_bundle_random = AESGCM.generate_key(bit_length=256)
        aesgcm_bundle_enc = AESGCM(k_bundle_random)
        nonce_bundle = secrets.token_bytes(12)
        encrypted_bundle_data = nonce_bundle + aesgcm_bundle_enc.encrypt(
            nonce_bundle,
            bundle_json_bytes,
            f"{constants.AEAD_AAD_DATA}.bundle".encode("utf-8"),
        )
        abuser_data_entry = AbuserData(
            user_id=user.id, encrypted_bundle=encrypted_bundle_data
        )

        Session.add(abuser_data_entry)
        Session.flush()

        blob_id = abuser_data_entry.id
        all_identifiers_raw = (
            [primary_email]
            + [a.email for a in aliases if a.email]
            + [m.email for m in mailboxes if m.email]
        )
        seen_normalized_identifiers = set()
        mac_key_bytes = config.MAC_KEY
        master_key_bytes = config.MASTER_ENC_KEY

        for idx, raw_identifier_address in enumerate(all_identifiers_raw):
            if not raw_identifier_address:
                continue

            normalized_identifier = raw_identifier_address.lower()

            if normalized_identifier in seen_normalized_identifiers:
                continue

            seen_normalized_identifiers.add(normalized_identifier)
            identifier_hmac = hmac.new(
                mac_key_bytes, normalized_identifier.encode("utf-8"), sha256
            ).hexdigest()

            k_identifier_derived = _derive_key_for_identifier(
                master_key_bytes, normalized_identifier
            )
            aesgcm_key_enc = AESGCM(k_identifier_derived)
            nonce_key_encryption = secrets.token_bytes(12)
            encrypted_k_bundle_for_this_identifier = (
                nonce_key_encryption
                + aesgcm_key_enc.encrypt(
                    nonce_key_encryption,
                    k_bundle_random,
                    f"{constants.AEAD_AAD_DATA}.key".encode("utf-8"),
                )
            )
            abuser_lookup_entry = AbuserLookup(
                hashed_address=identifier_hmac,
                abuser_data_id=blob_id,
                bundle_k=encrypted_k_bundle_for_this_identifier,
            )

            Session.add(abuser_lookup_entry)

            if idx % 1000 == 0:
                Session.flush()

        Session.commit()
    except Exception:
        Session.rollback()
        LOG.exception("Error during archive_abusive_user")
        raise


def get_abuser_bundles_for_address(target_address: str, admin_id: int) -> List[Dict]:
    """
    Given a target address (email, alias, or mailbox address),
    return all decrypted bundle_json's that reference this address.
    """
    if not target_address:
        return []

    normalized_target_address = target_address.lower()
    mac_key_bytes = config.MAC_KEY
    master_key_bytes = config.MASTER_ENC_KEY

    target_hmac = hmac.new(
        mac_key_bytes, normalized_target_address.encode("utf-8"), sha256
    ).hexdigest()
    lookup_entries: List[AbuserLookup] = AbuserLookup.filter(
        AbuserLookup.hashed_address == target_hmac
    ).all()

    if not lookup_entries:
        return []

    decrypted_bundles: List[Dict] = []

    try:
        k_target_address_derived = _derive_key_for_identifier(
            master_key_bytes, normalized_target_address
        )
        aesgcm_key_dec = AESGCM(k_target_address_derived)
    except ValueError as ve_derive:
        LOG.e(
            f"Error deriving key for target_address '{normalized_target_address}': {ve_derive}"
        )
        return []

    for entry in lookup_entries:
        blob_id = entry.abuser_data_id
        encrypted_k_bundle_from_entry = entry.bundle_k
        abuser_data_record: Optional[AbuserData] = AbuserData.filter_by(
            id=blob_id
        ).first()

        if not abuser_data_record:
            LOG.e(
                f"Error: No AbuserData found for blob_id {blob_id} linked to target_address '{normalized_target_address}'. Skipping."
            )
            continue

        encrypted_main_bundle_data = abuser_data_record.encrypted_bundle

        try:
            nonce_k_decryption = encrypted_k_bundle_from_entry[:12]
            ciphertext_k_decryption = encrypted_k_bundle_from_entry[12:]
            plaintext_k_bundle = aesgcm_key_dec.decrypt(
                nonce_k_decryption,
                ciphertext_k_decryption,
                f"{constants.AEAD_AAD_DATA}.key".encode("utf-8"),
            )
            aesgcm_bundle_dec = AESGCM(plaintext_k_bundle)
            nonce_main_bundle = encrypted_main_bundle_data[:12]
            ciphertext_main_bundle = encrypted_main_bundle_data[12:]
            decrypted_bundle_json_bytes = aesgcm_bundle_dec.decrypt(
                nonce_main_bundle,
                ciphertext_main_bundle,
                f"{constants.AEAD_AAD_DATA}.bundle".encode("utf-8"),
            )
            bundle = json.loads(decrypted_bundle_json_bytes.decode("utf-8"))
            decrypted_bundles.append(bundle)
        except InvalidTag:
            LOG.e(
                f"Error: AEAD decryption failed for blob_id {blob_id} (either K_bundle or main bundle). InvalidTag. Target address: '{normalized_target_address}'."
            )
            continue
        except ValueError as ve:
            LOG.e(
                f"Error: Decryption ValueError for blob_id {blob_id}: {ve}. Target address: '{normalized_target_address}'."
            )
            continue
        except Exception:
            LOG.e(
                f"Error: General decryption exception for blob_id {blob_id}. Target address: '{normalized_target_address}'."
            )
            continue

        emit_abuser_audit_log(
            user_id=abuser_data_record.user_id,
            admin_id=admin_id,
            action=AbuserAuditLogAction.GetAbuserBundles,
            message="The abuser bundle was requested.",
        )

    return decrypted_bundles
