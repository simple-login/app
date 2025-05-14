import json
import secrets
from hashlib import sha256
from typing import List, Dict

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.db import Session
from app.models import User, Alias, Mailbox, AbuserData, AbuserLookup


def check_if_abuser_email(new_address: str) -> bool:
    """
    Returns False, if the given address (after hashing) is found in abuser_lookup.
    """
    # Compute SHA-256 hash of the input address, encoded as UTF-8
    check_hash = sha256(new_address.encode("utf-8")).hexdigest()
    found = (
        AbuserLookup.filter(AbuserLookup.hashed_address == check_hash).limit(1).first()
    )

    return found


def archive_abusive_user(user: User) -> None:
    """
    Archive the given abusive user's data and update blocklist/lookup tables.
    """
    # assert user.email, "User must have a primary email"

    try:
        primary_email: str = user.email
        aliases: List[Alias] = Alias.filter_by(user_id=user.id).all()
        mailboxes: List[Mailbox] = Mailbox.filter_by(user_id=user.id).all()

        # Create Bundle
        bundle = {
            "account_id": user.id,
            "email": primary_email,
            "created_at": user.created_at.isoformat(),
            "aliases": [
                {
                    "address": alias.email,
                    "created_at": alias.created_at.isoformat(),
                }
                for alias in aliases
            ],
            "mailboxes": [
                {
                    "address": mailbox.email,
                    "created_at": mailbox.created_at.isoformat(),
                }
                for mailbox in mailboxes
            ],
        }
        bundle_json = json.dumps(bundle).encode("utf-8")

        # Generate Bundle Key
        k_bundle = AESGCM.generate_key(bit_length=256)
        aesgcm = AESGCM(k_bundle)
        nonce = secrets.token_bytes(12)

        # Encrypt Bundle
        encrypted_bundle = nonce + aesgcm.encrypt(nonce, bundle_json, None)

        # Store Encrypted Bundle
        abuser_data = AbuserData(user_id=user.id, encrypted_bundle=encrypted_bundle)
        Session.add(abuser_data)
        Session.flush()

        # Get Bundle ID
        blob_id = abuser_data.id

        # Process Each Identifier (Primary Email + All Aliases)
        all_addresses = (
            [primary_email] + [a.email for a in aliases] + [m.email for m in mailboxes]
        )
        seen = set()

        for address in all_addresses:
            if address in seen:
                continue

            seen.add(address)

            # a. Hash Address
            hashed_address = sha256(address.encode("utf-8")).hexdigest()

            # b. Derive Key from Address
            k_addr = sha256(address.encode("utf-8")).digest()

            # c. Encrypt Bundle Key
            aesgcm_addr = AESGCM(k_addr)
            nonce_enc = secrets.token_bytes(12)
            encrypted_k_bundle = nonce_enc + aesgcm_addr.encrypt(
                nonce_enc, k_bundle, None
            )

            # d. Store Lookup Entry
            abuser_lookup = AbuserLookup(
                hashed_address=hashed_address,
                blob_id=blob_id,
                encrypted_k_bundle=encrypted_k_bundle,
            )

            Session.add(abuser_lookup)

        Session.commit()
    except Exception:
        Session.rollback()
        raise


def unarchive_abusive_user(user_id: int) -> None:
    """
    Fully remove abuser archive and lookup data for a given user_id.
    This reverses the effects of archive_abusive_user().
    """
    abuser_data = AbuserData.get_by(user_id=user_id)

    if not abuser_data:
        return

    # I'm relying here on cascade removal
    Session.delete(abuser_data)
    Session.commit()


def get_abuser_bundles_for_address(address: str) -> List[Dict]:
    """
    Given a target address (email, alias, or mailbox address),
    return all decrypted bundle_json's that reference this address.
    """
    # Hash Target Address
    search_hash = sha256(address.encode("utf-8")).hexdigest()

    # Lookup Entries
    lookup_entries = AbuserLookup.query().filter_by(hashed_address=search_hash).all()

    if not lookup_entries:
        # If no rows are found
        return []

    # Derive Key for Decryption
    k_addr = sha256(address.encode("utf-8")).digest()
    aesgcm_k = AESGCM(k_addr)

    results = []

    # For each retrieved row
    for entry in lookup_entries:
        encrypted_k_bundle = entry.encrypted_k_bundle
        blob_id = entry.blob_id

        try:
            # Decrypt Bundle Key
            nonce_k = encrypted_k_bundle[:12]
            ciphertext_k = encrypted_k_bundle[12:]
            k_bundle = aesgcm_k.decrypt(nonce_k, ciphertext_k, None)

            # Fetch Encrypted Bundle
            abuser_data = AbuserData.get_by(id=blob_id)
            if not abuser_data:
                # Something wrong with decryption, I need to log it somehow
                continue

            # Decrypt Bundle
            encrypted_bundle = abuser_data.encrypted_bundle
            nonce_bundle = encrypted_bundle[:12]
            ciphertext_bundle = encrypted_bundle[12:]

            aesgcm_bundle = AESGCM(k_bundle)
            bundle_json = aesgcm_bundle.decrypt(nonce_bundle, ciphertext_bundle, None)
            bundle = json.loads(bundle_json.decode("utf-8"))

            results.append(bundle)

        except Exception:
            # Log decryption error
            continue

    return results
