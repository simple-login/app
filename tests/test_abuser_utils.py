import hmac
import json
import secrets
from hashlib import sha256

import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes as crypto_hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.abuser_utils import (
    archive_abusive_user,
    check_if_abuser_email,
    get_abuser_bundles_for_address,
    unarchive_abusive_user,
    _derive_encryption_key,
)
from app.db import Session
from app.models import AbuserLookup, AbuserData, Alias, Mailbox, User
from tests.utils import random_email, create_new_user

MOCK_MASTER_ENC_KEY = secrets.token_bytes(32)
MOCK_MAC_KEY = secrets.token_bytes(32)
MOCK_HKDF_INFO_TEMPLATE = "test_hkdf_info.shtepan.com:user_id:%s"
MOCK_AEAD_AAD_DATA = "test_aead_data.shtepan.com"


@pytest.fixture(autouse=True)
def mock_app_config(monkeypatch):
    class MockConfig:
        MASTER_ENC_KEY = MOCK_MASTER_ENC_KEY
        MAC_KEY = MOCK_MAC_KEY
        HKDF_INFO_TEMPLATE = MOCK_HKDF_INFO_TEMPLATE
        AEAD_AAD_DATA = MOCK_AEAD_AAD_DATA

    monkeypatch.setattr("app.abuser_utils.config", MockConfig)


def calculate_hmac(address: str) -> str:
    return hmac.new(
        MOCK_MAC_KEY,
        address.lower().encode("utf-8"),  # Normalize to lowercase
        sha256,
    ).hexdigest()


def helper_derive_key_for_test(user_id: int) -> bytes:
    hkdf_info_bytes = (MOCK_HKDF_INFO_TEMPLATE % str(user_id)).encode("utf-8")
    hkdf = HKDF(
        algorithm=crypto_hashes.SHA256(),
        length=32,
        salt=None,
        info=hkdf_info_bytes,
        backend=default_backend(),
    )

    return hkdf.derive(MOCK_MASTER_ENC_KEY)


def helper_decrypt_bundle_for_test(
    encrypted_bundle_data: bytes, owner_user_id: int
) -> dict:
    derived_key = helper_derive_key_for_test(owner_user_id)
    aesgcm = AESGCM(derived_key)
    nonce = encrypted_bundle_data[:12]
    ciphertext = encrypted_bundle_data[12:]
    aad_bytes = MOCK_AEAD_AAD_DATA.encode("utf-8")
    decrypted_json_bytes = aesgcm.decrypt(nonce, ciphertext, aad_bytes)

    return json.loads(decrypted_json_bytes.decode("utf-8"))


def get_lookup_count_for_address(address: str) -> int:
    identifier_hmac = calculate_hmac(address.lower())
    return (
        Session.query(AbuserLookup)
        .filter(AbuserLookup.hashed_address == identifier_hmac)
        .count()
    )


def test_blocked_address_is_denied(flask_client, monkeypatch):
    user = create_new_user(email="spam@shtepan.com")
    Session.add(user)
    Session.commit()
    bad_address = "troll@shtepan.com"
    identifier_hmac = calculate_hmac(bad_address)
    a_data = AbuserData.create(
        user_id=user.id,
        encrypted_bundle=secrets.token_bytes(32),
        commit=True,
    )
    AbuserLookup.create(
        hashed_address=identifier_hmac,
        abuser_data_id=a_data.id,
        commit=True,
    )

    assert check_if_abuser_email(bad_address.lower())

    User.delete(user.id)
    Session.commit()


def test_non_blocked_address_is_allowed(flask_client, monkeypatch):
    safe_address = random_email()
    identifier_hmac = calculate_hmac(safe_address)

    assert (
        AbuserLookup.filter(AbuserLookup.hashed_address == identifier_hmac).first()
        is None
    )
    assert not check_if_abuser_email(safe_address)


def test_archive_basic_user(flask_client, monkeypatch):
    user = create_new_user()
    user_email_lower = user.email.lower()
    alias1_email = random_email().lower()
    Alias.create(
        email=alias1_email,
        user_id=user.id,
        mailbox_id=user.default_mailbox_id,
        commit=True,
    )
    mailbox1 = Mailbox.get(user.default_mailbox_id)

    assert mailbox1 is not None

    mailbox1_email_lower = mailbox1.email.lower()
    Session.commit()
    archive_abusive_user(user)
    ab_data = AbuserData.filter_by(user_id=user.id).first()

    assert ab_data is not None
    assert ab_data.encrypted_bundle is not None

    decrypted_bundle = helper_decrypt_bundle_for_test(ab_data.encrypted_bundle, user.id)

    assert decrypted_bundle["account_id"] == user.id
    assert decrypted_bundle["email"] == user_email_lower
    assert len(decrypted_bundle["aliases"]) == 2
    assert any(a["address"] == alias1_email for a in decrypted_bundle["aliases"])
    assert any(
        "simplelogin-newsletter" in a["address"] for a in decrypted_bundle["aliases"]
    )

    all_identifiers_to_check = {user_email_lower, alias1_email, mailbox1_email_lower}
    newsletter_alias = Alias.filter_by(
        user_id=user.id, id=user.newsletter_alias_id
    ).first()

    if newsletter_alias:
        all_identifiers_to_check.add(newsletter_alias.email.lower())

    for address in all_identifiers_to_check:
        identifier_hmac = calculate_hmac(address)
        entry = AbuserLookup.filter_by(hashed_address=identifier_hmac).first()

        assert entry is not None, f"Lookup entry missing for {address}"
        assert entry.abuser_data_id == ab_data.id


def test_archive_user_with_no_aliases_or_mailboxes(flask_client, monkeypatch):
    user = create_new_user()
    user_default_mailbox = Mailbox.get(user.default_mailbox_id)

    Alias.filter_by(user_id=user.id).delete(synchronize_session=False)
    Session.commit()
    archive_abusive_user(user)
    ab_data = AbuserData.filter_by(user_id=user.id).first()

    assert ab_data is not None

    decrypted_bundle = helper_decrypt_bundle_for_test(ab_data.encrypted_bundle, user.id)

    assert decrypted_bundle["account_id"] == user.id
    assert decrypted_bundle["email"] == user.email.lower()
    assert len(decrypted_bundle["aliases"]) == 0

    if user_default_mailbox:
        assert len(decrypted_bundle["mailboxes"]) >= 0


def test_duplicate_addresses_do_not_create_duplicate_lookups(flask_client, monkeypatch):
    user = create_new_user()
    duplicate_email_base = random_email()

    if not user.default_mailbox_id:
        mb = Mailbox.create(
            user_id=user.id,
            email=random_email().lower(),
            verified=True,
            commit=True,
        )
        user.default_mailbox_id = mb.id
        Session.add(user)
        Session.commit()

    Alias.create(
        email=duplicate_email_base.lower(),
        user_id=user.id,
        mailbox_id=user.default_mailbox_id,
        commit=True,
    )
    user_primary_email_orig = user.email
    user.email = random_email().lower()
    Session.add(user)
    Session.commit()

    default_mb = Mailbox.get(user.default_mailbox_id)

    assert default_mb is not None

    default_mb.email = duplicate_email_base.lower()
    Session.add(default_mb)
    Session.commit()
    archive_abusive_user(user)

    identifier_hmac_duplicate = calculate_hmac(duplicate_email_base)
    matches_count_duplicate = AbuserLookup.filter_by(
        hashed_address=identifier_hmac_duplicate
    ).count()

    assert matches_count_duplicate == 1

    identifier_hmac_primary = calculate_hmac(user.email)
    matches_count_primary = AbuserLookup.filter_by(
        hashed_address=identifier_hmac_primary
    ).count()

    assert matches_count_primary == 1

    user.email = user_primary_email_orig
    Session.add(user)
    Session.commit()


def test_invalid_user_fails_gracefully(flask_client, monkeypatch):
    invalid_user_for_kdf = User(id=0, email="bohdan@shtepan.com")

    with pytest.raises(
        ValueError, match="User ID must be a valid positive integer for key derivation."
    ):
        _derive_encryption_key(MOCK_MASTER_ENC_KEY, invalid_user_for_kdf.id)

    user_obj_no_email = User(id=99999, email=None)

    with pytest.raises(
        ValueError,
        match=f"User ID {user_obj_no_email.id} must have a primary email to be archived.",
    ):
        archive_abusive_user(user_obj_no_email)


def test_can_decrypt_bundle_for_all_identifiers(flask_client, monkeypatch):
    user = create_new_user()

    if not user.default_mailbox_id:
        mb = Mailbox.create(
            user_id=user.id,
            email=random_email().lower(),
            verified=True,
            commit=True,
        )
        user.default_mailbox_id = mb.id
        Session.add(user)
        Session.commit()

    alias1_email = random_email().lower()
    alias1 = Alias.create(
        email=alias1_email,
        user_id=user.id,
        mailbox_id=user.default_mailbox_id,
        commit=True,
    )
    mailbox1 = Mailbox.get(user.default_mailbox_id)

    assert mailbox1 is not None

    Session.commit()

    archive_abusive_user(user)
    ab_data = AbuserData.filter_by(user_id=user.id).first()

    assert ab_data is not None

    decrypted_bundle = helper_decrypt_bundle_for_test(ab_data.encrypted_bundle, user.id)

    assert decrypted_bundle["account_id"] == user.id
    assert decrypted_bundle["email"] == user.email.lower()

    all_identifiers_to_check = {
        user.email.lower(),
        alias1.email.lower(),
        mailbox1.email.lower(),
    }

    for addr in all_identifiers_to_check:
        if not addr:
            continue

        identifier_hmac = calculate_hmac(addr)
        entry = AbuserLookup.filter_by(
            hashed_address=identifier_hmac, abuser_data_id=ab_data.id
        ).first()

        assert entry is not None, f"No lookup entry for address: {addr}"


def test_db_rollback_on_error(monkeypatch, flask_client):
    user = create_new_user()
    original_commit = Session.commit

    def mock_commit_failure():
        raise RuntimeError("Simulated DB failure")

    monkeypatch.setattr(Session, "commit", mock_commit_failure)

    with pytest.raises(RuntimeError, match="Simulated DB failure"):
        archive_abusive_user(user)

    monkeypatch.setattr(Session, "commit", original_commit)
    Session.rollback()

    assert AbuserData.filter_by(user_id=user.id).first() is None

    identifier_hmac = calculate_hmac(user.email)

    assert AbuserLookup.filter_by(hashed_address=identifier_hmac).count() == 0


def test_unarchive_abusive_user_removes_data(flask_client, monkeypatch):
    user = create_new_user()
    email = user.email.lower()
    archive_abusive_user(user)

    assert AbuserData.filter_by(user_id=user.id).first() is not None
    assert get_lookup_count_for_address(email) > 0

    unarchive_abusive_user(user.id)

    assert AbuserData.filter_by(user_id=user.id).first() is None
    assert get_lookup_count_for_address(email) == 0


def test_unarchive_idempotent_on_missing_data(flask_client, monkeypatch):
    user = create_new_user()

    assert AbuserData.filter_by(user_id=user.id).first() is None

    unarchive_abusive_user(user.id)

    assert AbuserData.filter_by(user_id=user.id).first() is None


def test_abuser_data_deletion_cascades_to_lookup(flask_client, monkeypatch):
    user = create_new_user()
    archive_abusive_user(user)
    ab_data = AbuserData.filter_by(user_id=user.id).first()

    assert ab_data is not None

    abuser_data_pk_id = ab_data.id

    assert AbuserLookup.filter_by(abuser_data_id=abuser_data_pk_id).count() > 0

    Session.delete(ab_data)
    Session.commit()

    assert AbuserLookup.filter_by(abuser_data_id=abuser_data_pk_id).count() == 0


def test_archive_then_unarchive_then_rearchive_is_consistent(flask_client, monkeypatch):
    user = create_new_user()
    archive_abusive_user(user)
    ab_data1 = AbuserData.filter_by(user_id=user.id).first()

    assert ab_data1 is not None

    unarchive_abusive_user(user.id)

    assert AbuserData.filter_by(user_id=user.id).first() is None

    archive_abusive_user(user)
    ab_data2 = AbuserData.filter_by(user_id=user.id).first()

    assert ab_data2 is not None
    assert ab_data2.id != ab_data1.id


def test_get_abuser_bundles_returns_bundle(flask_client, monkeypatch):
    user = create_new_user()
    email = user.email.lower()
    archive_abusive_user(user)
    bundles = get_abuser_bundles_for_address(email)

    assert len(bundles) == 1

    bundle = bundles[0]

    assert bundle["email"] == email
    assert bundle["account_id"] == user.id
    assert "aliases" in bundle
    assert "mailboxes" in bundle


def test_get_abuser_bundles_no_match_returns_empty(flask_client, monkeypatch):
    bundles = get_abuser_bundles_for_address("bohdan@shtepan.com")
    assert bundles == []


def test_get_abuser_bundles_from_alias_address(flask_client, monkeypatch):
    user = create_new_user()

    if not user.default_mailbox_id:
        mb = Mailbox.create(
            user_id=user.id,
            email=random_email().lower(),
            verified=True,
            commit=True,
        )
        user.default_mailbox_id = mb.id
        Session.add(user)
        Session.commit()

    alias_email = random_email().lower()
    alias = Alias.create(
        email=alias_email,
        user_id=user.id,
        mailbox_id=user.default_mailbox_id,
        commit=True,
    )
    archive_abusive_user(user)
    results = get_abuser_bundles_for_address(alias.email)

    assert len(results) == 1

    bundle = results[0]

    assert bundle["email"] == user.email.lower()
    assert any(a["address"] == alias.email for a in bundle["aliases"])


def test_get_abuser_bundles_from_mailbox_address(flask_client, monkeypatch):
    user = create_new_user()
    mailbox = Mailbox.get(user.default_mailbox_id) if user.default_mailbox_id else None

    if not mailbox or not mailbox.email:
        mailbox_email_for_test = random_email().lower()

        if mailbox:
            mailbox.email = mailbox_email_for_test
        else:
            mailbox = Mailbox.create(
                user_id=user.id,
                email=mailbox_email_for_test,
                verified=True,
                commit=False,
            )
            Session.flush()
            user.default_mailbox_id = mailbox.id
        Session.add(mailbox)

        if not user.default_mailbox_id:
            Session.add(user)

        Session.commit()

    current_mailbox_email = mailbox.email.lower()
    archive_abusive_user(user)

    results = get_abuser_bundles_for_address(current_mailbox_email)

    assert len(results) == 1

    bundle = results[0]

    assert bundle["email"] == user.email.lower()
    assert any(m["address"] == current_mailbox_email for m in bundle["mailboxes"])


def test_get_abuser_bundles_with_corrupt_bundle_data_is_skipped(
    flask_client, monkeypatch
):
    user = create_new_user()
    archive_abusive_user(user)
    ab_data = AbuserData.filter_by(user_id=user.id).first()

    assert ab_data is not None

    original_bundle = ab_data.encrypted_bundle

    if len(original_bundle) > 12 + 16:
        corrupted_bundle = (
            original_bundle[:12]
            + secrets.token_bytes(len(original_bundle) - 12 - 16)
            + original_bundle[-15:]
        )
    else:
        corrupted_bundle = secrets.token_bytes(30)

    ab_data.encrypted_bundle = corrupted_bundle
    Session.add(ab_data)
    Session.commit()

    bundles = get_abuser_bundles_for_address(user.email.lower())

    assert bundles == []

    ab_data.encrypted_bundle = original_bundle
    Session.add(ab_data)
    Session.commit()


def test_archive_and_fetch_flow(flask_client, monkeypatch):
    user = create_new_user()
    mailbox = Mailbox.get(user.default_mailbox_id) if user.default_mailbox_id else None

    if not mailbox:
        mailbox_email_for_test = random_email().lower()
        mailbox = Mailbox.create(
            user_id=user.id,
            email=mailbox_email_for_test,
            verified=True,
            commit=True,
        )
        user.default_mailbox_id = mailbox.id
        Session.add(user)
        Session.commit()

    current_mailbox_email = mailbox.email.lower()
    archive_abusive_user(user)

    bundles = get_abuser_bundles_for_address(user.email.lower())

    assert len(bundles) == 1

    data = bundles[0]

    assert data is not None
    assert data["email"] == user.email.lower()
    assert data["account_id"] == user.id
    assert any(mb["address"] == current_mailbox_email for mb in data["mailboxes"])
