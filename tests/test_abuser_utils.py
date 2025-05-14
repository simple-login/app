import json
from hashlib import sha256

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.abuser_utils import (
    archive_abusive_user,
    check_if_abuser_email,
    get_abuser_bundles_for_address,
    unarchive_abusive_user,
)
from app.db import Session
from app.models import AbuserLookup, AbuserData, Alias, Mailbox
from tests.utils import random_email, create_new_user


def hash_address(address: str) -> str:
    return sha256(address.encode("utf-8")).hexdigest()


def decrypt_bundle(encrypted_bundle: bytes, k_bundle: bytes) -> bytes:
    nonce = encrypted_bundle[:12]
    ciphertext = encrypted_bundle[12:]

    return AESGCM(k_bundle).decrypt(nonce, ciphertext, None)


def derive_key(address: str) -> bytes:
    return sha256(address.encode("utf-8")).digest()


def get_lookup_count_for_address(address: str) -> int:
    hashed = sha256(address.encode("utf-8")).hexdigest()

    return (
        Session.query(AbuserLookup)
        .filter(AbuserLookup.hashed_address == hashed)
        .count()
    )


def test_blocked_address_is_denied(flask_client):
    bad_address = "spam@shtepan.com"
    hashed = hash_address(bad_address)

    a_data = AbuserData.create(
        user_id=123,
        encrypted_bundle="test".encode("utf-8"),
        commit=True,
    )
    AbuserLookup.create(
        hashed_address=hashed,
        blob_id=a_data.id,
        encrypted_k_bundle="test".encode("utf-8"),
        commit=True,
    )

    assert check_if_abuser_email(bad_address)


def test_non_blocked_address_is_allowed(flask_client):
    safe_address = random_email()
    hashed = hash_address(safe_address)

    assert AbuserLookup.filter(AbuserLookup.hashed_address == hashed).first() is None
    assert not check_if_abuser_email(safe_address)


def test_archive_basic_user(flask_client):
    user = create_new_user()
    alias1 = Alias.create(
        email=random_email(),
        user_id=user.id,
        mailbox_id=user.default_mailbox_id,
        commit=True,
    )
    mailbox1 = Mailbox.get(user.default_mailbox_id)

    Session.commit()

    archive_abusive_user(user)

    ab_data = AbuserData.get_by(user_id=user.id)

    assert ab_data is not None
    assert ab_data.encrypted_bundle

    all_identifiers = {user.email, alias1.email, mailbox1.email}
    for address in all_identifiers:
        hashed = sha256(address.encode("utf-8")).hexdigest()
        entry = AbuserLookup.get_by(hashed_address=hashed)

        assert entry is not None
        assert entry.encrypted_k_bundle

        nonce_k = entry.encrypted_k_bundle[:12]
        ciphertext_k = entry.encrypted_k_bundle[12:]
        derived_key = derive_key(address)
        k_bundle = AESGCM(derived_key).decrypt(nonce_k, ciphertext_k, None)
        decrypted_bundle_json = decrypt_bundle(ab_data.encrypted_bundle, k_bundle)
        bundle = json.loads(decrypted_bundle_json.decode("utf-8"))

        assert bundle["account_id"] == user.id
        assert bundle["email"] == user.email


def test_archive_user_with_no_aliases_or_mailboxes(flask_client):
    user = create_new_user()
    user.default_mailbox_id = None  # I need this to avoid ForeignKeyViolation exception
    Session.commit()

    Alias.filter_by(user_id=user.id).delete()
    Mailbox.filter_by(user_id=user.id).delete()
    Session.commit()

    archive_abusive_user(user)

    ab_data = AbuserData.get_by(user_id=user.id)

    assert ab_data is not None


def test_duplicate_addresses_do_not_create_duplicate_lookups(flask_client):
    user = create_new_user()
    duplicate_email = random_email()
    Alias.create(
        email=duplicate_email,
        user_id=user.id,
        mailbox_id=user.default_mailbox_id,
        commit=True,
    )
    Mailbox.create(
        email=duplicate_email,
        user_id=user.id,
        commit=True,
    )

    Session.commit()

    archive_abusive_user(user)

    hashed = sha256(duplicate_email.encode("utf-8")).hexdigest()
    matches = Session.query(AbuserLookup).filter_by(hashed_address=hashed).all()

    assert len(matches) == 1


def test_invalid_user_fails_gracefully(flask_client):
    user = create_new_user()
    user.email = None

    with pytest.raises(Exception):
        archive_abusive_user(user)

    with Session.no_autoflush:
        assert AbuserData.get_by(user_id=user.id) is None


def test_can_decrypt_bundle_for_all_identifiers(flask_client):
    user = create_new_user()
    alias1 = Alias.create(
        email=random_email(),
        user_id=user.id,
        mailbox_id=user.default_mailbox_id,
        commit=True,
    )
    mailbox1 = Mailbox.get(user.default_mailbox_id)

    archive_abusive_user(user)
    ab_data = AbuserData.get_by(user_id=user.id)

    all_addresses = [user.email, alias1.email, mailbox1.email]

    for addr in all_addresses:
        hashed = sha256(addr.encode("utf-8")).hexdigest()
        entry = AbuserLookup.get_by(hashed_address=hashed)
        k_addr = sha256(addr.encode("utf-8")).digest()
        nonce_k = entry.encrypted_k_bundle[:12]
        ciphertext_k = entry.encrypted_k_bundle[12:]
        k_bundle = AESGCM(k_addr).decrypt(nonce_k, ciphertext_k, None)
        decrypted_bundle_json = decrypt_bundle(ab_data.encrypted_bundle, k_bundle)
        bundle = json.loads(decrypted_bundle_json.decode("utf-8"))

        assert bundle["account_id"] == user.id


def test_db_rollback_on_error(monkeypatch, flask_client):
    user = create_new_user()
    monkeypatch.setattr(
        Session, "commit", lambda: (_ for _ in ()).throw(RuntimeError("DB failure"))
    )

    with pytest.raises(RuntimeError):
        archive_abusive_user(user)

    assert AbuserData.get_by(user_id=user.id) is None
    assert (
        Session.query(AbuserLookup)
        .filter(
            AbuserLookup.hashed_address
            == sha256(user.email.encode("utf-8")).hexdigest()
        )
        .count()
        == 0
    )


def test_unarchive_abusive_user_removes_data(flask_client):
    user = create_new_user()
    email = user.email
    archive_abusive_user(user)

    assert AbuserData.get_by(user_id=user.id)
    assert get_lookup_count_for_address(email) > 0

    unarchive_abusive_user(user.id)

    assert AbuserData.get_by(user_id=user.id) is None
    assert get_lookup_count_for_address(email) == 0


def test_unarchive_idempotent_on_missing_data(flask_client):
    user = create_new_user()

    assert AbuserData.get_by(user_id=user.id) is None

    unarchive_abusive_user(user.id)

    assert AbuserData.get_by(user_id=user.id) is None


def test_abuser_data_deletion_cascades_to_lookup(flask_client):
    user = create_new_user()
    archive_abusive_user(user)
    ab_data = AbuserData.get_by(user_id=user.id)
    blob_id = ab_data.id

    assert Session.query(AbuserLookup).filter_by(blob_id=blob_id).count() > 0

    Session.delete(ab_data)
    Session.commit()

    assert Session.query(AbuserLookup).filter_by(blob_id=blob_id).count() == 0


def test_archive_then_unarchive_then_rearchive_is_consistent(flask_client):
    user = create_new_user()

    archive_abusive_user(user)
    ab_data1 = AbuserData.get_by(user_id=user.id)

    assert ab_data1

    unarchive_abusive_user(user.id)

    assert AbuserData.get_by(user_id=user.id) is None

    archive_abusive_user(user)
    ab_data2 = AbuserData.get_by(user_id=user.id)

    assert ab_data2
    assert ab_data2.id != ab_data1.id


def test_get_abuser_bundles_returns_bundle(flask_client):
    user = create_new_user()
    email = user.email
    archive_abusive_user(user)
    bundles = get_abuser_bundles_for_address(email)

    assert len(bundles) == 1
    assert bundles[0]["email"] == email
    assert "aliases" in bundles[0]
    assert "mailboxes" in bundles[0]


def test_get_abuser_bundles_no_match_returns_empty(flask_client):
    bundles = get_abuser_bundles_for_address("goodboy@shtepan.com")
    assert bundles == []


def test_get_abuser_bundles_from_alias_address(flask_client):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    Session.commit()

    archive_abusive_user(user)

    results = get_abuser_bundles_for_address(alias.email)

    assert len(results) == 1

    bundle = results[0]

    assert any(a["address"] == alias.email for a in bundle["aliases"])


def test_get_abuser_bundles_from_mailbox_address(flask_client):
    user = create_new_user()
    mailbox = user.default_mailbox

    archive_abusive_user(user)

    results = get_abuser_bundles_for_address(mailbox.email)

    assert len(results) == 1

    bundle = results[0]

    assert any(m["address"] == mailbox.email for m in bundle["mailboxes"])


def test_get_abuser_bundles_with_corrupt_entry_is_skipped(flask_client):
    user = create_new_user()
    archive_abusive_user(user)
    hashed = hash_address(user.email)
    lookup = Session.query(AbuserLookup).filter_by(hashed_address=hashed).first()

    assert lookup is not None

    lookup.encrypted_k_bundle = b"\x00" * len(lookup.encrypted_k_bundle)
    Session.commit()
    bundles = get_abuser_bundles_for_address(user.email)

    assert bundles == []


def test_archive_and_fetch_flow(flask_client):
    user = create_new_user()
    mailbox = user.default_mailbox
    archive_abusive_user(user)
    data = get_abuser_bundles_for_address(user.email)

    assert data
    assert data[0]["email"] == user.email
    assert any(mb["address"] == mailbox.email for mb in data[0]["mailboxes"])
