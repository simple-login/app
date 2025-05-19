import hashlib
import hmac
import secrets

import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes as crypto_hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.abuser_utils import (
    mark_user_as_abuser,
    check_if_abuser_email,
    get_abuser_bundles_for_address,
    unmark_as_abusive_user,
    _derive_key_for_identifier,
)
from app import constants
from app.db import Session
from app.models import AbuserLookup, AbuserData, Alias, Mailbox, User
from tests.utils import random_email, create_new_user

MOCK_MASTER_ENC_KEY = secrets.token_bytes(32)
MOCK_MAC_KEY = secrets.token_bytes(32)
MOCK_ABUSER_HKDF_SALT = secrets.token_bytes(32)


@pytest.fixture(autouse=True)
def mock_app_config(monkeypatch):
    class MockConfig:
        MASTER_ENC_KEY = MOCK_MASTER_ENC_KEY
        MAC_KEY = MOCK_MAC_KEY
        ABUSER_HKDF_SALT = MOCK_MASTER_ENC_KEY

    monkeypatch.setattr("app.abuser_utils.config", MockConfig)


def calculate_hmac(address: str) -> str:
    normalized_address = address.lower()

    return hmac.new(
        MOCK_MAC_KEY, normalized_address.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def helper_derive_kek_for_identifier_test(identifier_address: str) -> bytes:
    normalized_identifier = identifier_address.lower()
    hkdf_info_bytes = (constants.HKDF_INFO_TEMPLATE % normalized_identifier).encode(
        "utf-8"
    )
    hkdf = HKDF(
        algorithm=crypto_hashes.SHA256(),
        length=32,
        salt=None,
        info=hkdf_info_bytes,
        backend=default_backend(),
    )

    return hkdf.derive(MOCK_MASTER_ENC_KEY)


def get_lookup_count_for_address(address: str) -> int:
    identifier_hmac = calculate_hmac(address)

    return (
        Session.query(AbuserLookup)
        .filter(AbuserLookup.hashed_address == identifier_hmac)
        .count()
    )


def test_blocked_address_is_denied(flask_client, monkeypatch):
    owner_user_email = random_email()
    owner_user = create_new_user(email=owner_user_email)

    if not owner_user.id:
        Session.flush()

    bad_address_to_block = "troll@shtepan.com"
    identifier_hmac = calculate_hmac(bad_address_to_block)

    a_data = AbuserData.create(
        user_id=owner_user.id,
        encrypted_bundle=secrets.token_bytes(64),
        commit=True,
    )
    AbuserLookup.create(
        hashed_address=identifier_hmac,
        abuser_data_id=a_data.id,
        bundle_k=secrets.token_bytes(48),
        commit=True,
    )

    assert check_if_abuser_email(bad_address_to_block) is not None

    Session.delete(a_data)
    Session.delete(owner_user)
    Session.commit()


def test_non_blocked_address_is_allowed(flask_client, monkeypatch):
    safe_address = random_email()
    identifier_hmac = calculate_hmac(safe_address)

    assert (
        AbuserLookup.filter(AbuserLookup.hashed_address == identifier_hmac).first()
        is None
    )
    assert check_if_abuser_email(safe_address) is None


def test_archive_basic_user(flask_client, monkeypatch):
    user = create_new_user()
    user_primary_email_normalized = user.email.lower()

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

    alias1_email_normalized = random_email().lower()
    Alias.create(
        email=alias1_email_normalized,
        user_id=user.id,
        mailbox_id=user.default_mailbox_id,
        commit=True,
    )
    mailbox1 = Mailbox.get(user.default_mailbox_id)

    assert mailbox1 is not None

    mailbox1_email_normalized = mailbox1.email.lower()
    Session.commit()
    mark_user_as_abuser(user, "")
    ab_data = AbuserData.filter_by(user_id=user.id).first()

    assert ab_data is not None
    assert ab_data.encrypted_bundle is not None

    all_identifiers_to_check = {
        user_primary_email_normalized,
        alias1_email_normalized,
        mailbox1_email_normalized,
    }

    for identifier_str in all_identifiers_to_check:
        if not identifier_str:
            continue

        identifier_hmac = calculate_hmac(identifier_str)
        lookup_entry = AbuserLookup.filter_by(
            hashed_address=identifier_hmac, abuser_data_id=ab_data.id
        ).first()

        assert lookup_entry is not None, f"Lookup entry missing for {identifier_str}"
        assert lookup_entry.bundle_k is not None

        retrieved_bundles = get_abuser_bundles_for_address(identifier_str, -1)

        assert (
            len(retrieved_bundles) == 1
        ), f"Could not retrieve bundle for identifier: {identifier_str}"

        bundle = retrieved_bundles[0]

        assert bundle["account_id"] == str(user.id)
        assert bundle["email"] == user_primary_email_normalized
        assert any(
            a["address"] == alias1_email_normalized for a in bundle.get("aliases", [])
        )


def test_archive_user_with_no_aliases_or_mailboxes(flask_client, monkeypatch):
    user = create_new_user()
    user_primary_email_normalized = user.email.lower()
    Alias.filter_by(user_id=user.id).delete(synchronize_session=False)
    Session.commit()
    mark_user_as_abuser(user, "")
    ab_data = AbuserData.filter_by(user_id=user.id).first()

    assert ab_data is not None

    retrieved_bundles = get_abuser_bundles_for_address(
        user_primary_email_normalized, -1
    )

    assert len(retrieved_bundles) == 1

    bundle = retrieved_bundles[0]

    assert bundle["account_id"] == str(user.id)
    assert bundle["email"] == user_primary_email_normalized
    assert len(bundle.get("aliases", [])) == 0
    assert "mailboxes" in bundle


def test_duplicate_addresses_do_not_create_duplicate_lookups(flask_client, monkeypatch):
    user = create_new_user()
    duplicate_email_normalized = random_email().lower()

    if not user.default_mailbox_id:
        mb = Mailbox.create(
            user_id=user.id, email=random_email().lower(), verified=True, commit=True
        )
        user.default_mailbox_id = mb.id
        Session.add(user)
        Session.commit()

    Alias.create(
        email=duplicate_email_normalized,
        user_id=user.id,
        mailbox_id=user.default_mailbox_id,
        commit=True,
    )
    default_mb = Mailbox.get(user.default_mailbox_id)

    assert default_mb is not None

    default_mb.email = duplicate_email_normalized
    Session.add(default_mb)
    Session.commit()
    mark_user_as_abuser(user, "")
    identifier_hmac_duplicate = calculate_hmac(duplicate_email_normalized)
    ab_data = AbuserData.filter_by(user_id=user.id).first()

    assert ab_data is not None

    matches_count_duplicate = AbuserLookup.filter_by(
        hashed_address=identifier_hmac_duplicate, abuser_data_id=ab_data.id
    ).count()

    assert matches_count_duplicate == 1


def test_invalid_user_or_identifier_fails_gracefully(flask_client, monkeypatch):
    with pytest.raises(
        ValueError, match="Identifier address must be a non-empty string"
    ):
        _derive_key_for_identifier(MOCK_MASTER_ENC_KEY, None)

    with pytest.raises(
        ValueError, match="Identifier address must be a non-empty string"
    ):
        _derive_key_for_identifier(MOCK_MASTER_ENC_KEY, "")

    user_obj_no_email = User(id=99999, email=None)

    with pytest.raises(
        ValueError, match=f"User ID {user_obj_no_email.id} must have a primary email"
    ):
        mark_user_as_abuser(user_obj_no_email, "")


def test_can_decrypt_bundle_for_all_valid_identifiers(flask_client, monkeypatch):
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

    alias1_email_normalized = random_email().lower()
    Alias.create(
        email=alias1_email_normalized,
        user_id=user.id,
        mailbox_id=user.default_mailbox_id,
        commit=True,
    )
    mailbox1 = Mailbox.get(user.default_mailbox_id)

    assert mailbox1 is not None

    mailbox1_email_normalized = mailbox1.email.lower()
    Session.commit()
    mark_user_as_abuser(user, "")
    ab_data = AbuserData.filter_by(user_id=user.id).first()

    assert ab_data is not None

    all_identifiers_to_check = {
        user.email.lower(),
        alias1_email_normalized,
        mailbox1_email_normalized,
    }

    for identifier_str in all_identifiers_to_check:
        if not identifier_str:
            continue

        retrieved_bundles = get_abuser_bundles_for_address(identifier_str, -1)

        assert len(retrieved_bundles) == 1, f"Failed for identifier: {identifier_str}"

        bundle = retrieved_bundles[0]

        assert bundle["account_id"] == str(user.id)
        assert bundle["email"] == user.email.lower()


def test_db_rollback_on_error(monkeypatch, flask_client):
    user = create_new_user()
    original_commit = Session.commit

    def mock_commit_failure():
        raise RuntimeError("Simulated DB failure during commit")

    monkeypatch.setattr(Session, "commit", mock_commit_failure)

    with pytest.raises(RuntimeError, match="Simulated DB failure during commit"):
        mark_user_as_abuser(user, "")

    monkeypatch.setattr(Session, "commit", original_commit)  # Restore
    Session.rollback()

    assert AbuserData.filter_by(user_id=user.id).first() is None

    identifier_hmac = calculate_hmac(user.email)

    assert AbuserLookup.filter_by(hashed_address=identifier_hmac).count() == 0


def test_unarchive_abusive_user_removes_data(flask_client, monkeypatch):
    user = create_new_user()
    email_normalized = user.email.lower()
    mark_user_as_abuser(user, "")

    assert AbuserData.filter_by(user_id=user.id).first() is not None
    assert get_lookup_count_for_address(email_normalized) > 0

    unmark_as_abusive_user(user.id, "")

    assert AbuserData.filter_by(user_id=user.id).first() is None

    assert get_lookup_count_for_address(email_normalized) == 0


def test_unarchive_idempotent_on_missing_data(flask_client, monkeypatch):
    user = create_new_user()

    assert AbuserData.filter_by(user_id=user.id).first() is None

    unmark_as_abusive_user(user.id, "")

    assert AbuserData.filter_by(user_id=user.id).first() is None


def test_abuser_data_deletion_cascades_to_lookup(flask_client, monkeypatch):
    user = create_new_user()
    mark_user_as_abuser(user, "")
    ab_data = AbuserData.filter_by(user_id=user.id).first()

    assert ab_data is not None

    abuser_data_pk_id = ab_data.id

    assert AbuserLookup.filter_by(abuser_data_id=abuser_data_pk_id).count() > 0

    Session.delete(ab_data)
    Session.commit()

    assert AbuserLookup.filter_by(abuser_data_id=abuser_data_pk_id).count() == 0


def test_archive_then_unarchive_then_rearchive_is_consistent(flask_client, monkeypatch):
    user = create_new_user()
    mark_user_as_abuser(user, "")
    ab_data1 = AbuserData.filter_by(user_id=user.id).first()

    assert ab_data1 is not None

    unmark_as_abusive_user(user.id, "")

    assert AbuserData.filter_by(user_id=user.id).first() is None

    mark_user_as_abuser(user, "")
    ab_data2 = AbuserData.filter_by(user_id=user.id).first()

    assert ab_data2 is not None
    assert ab_data2.id != ab_data1.id


def test_get_abuser_bundles_returns_bundle_for_primary_email(flask_client, monkeypatch):
    user = create_new_user()
    email_normalized = user.email.lower()
    mark_user_as_abuser(user, "")
    bundles = get_abuser_bundles_for_address(email_normalized, -1)

    assert len(bundles) == 1

    bundle = bundles[0]

    assert bundle["email"] == email_normalized
    assert bundle["account_id"] == str(user.id)
    assert "aliases" in bundle
    assert "mailboxes" in bundle


def test_get_abuser_bundles_no_match_returns_empty(flask_client, monkeypatch):
    bundles = get_abuser_bundles_for_address("bohdan@shtepan.com", -1)
    assert bundles == []


def test_get_abuser_bundles_from_alias_address(flask_client, monkeypatch):
    user = create_new_user()

    if not user.default_mailbox_id:
        mb = Mailbox.create(
            user_id=user.id, email=random_email().lower(), verified=True, commit=True
        )
        user.default_mailbox_id = mb.id
        Session.add(user)
        Session.commit()

    alias_email_normalized = random_email().lower()
    Alias.create(
        email=alias_email_normalized,
        user_id=user.id,
        mailbox_id=user.default_mailbox_id,
        commit=True,
    )
    mark_user_as_abuser(user, "")
    results = get_abuser_bundles_for_address(alias_email_normalized, -1)

    assert len(results) == 1

    bundle = results[0]

    assert bundle["email"] == user.email.lower()
    assert any(
        a["address"] == alias_email_normalized for a in bundle.get("aliases", [])
    )


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

    current_mailbox_email_normalized = mailbox.email.lower()
    mark_user_as_abuser(user, "")

    results = get_abuser_bundles_for_address(current_mailbox_email_normalized, -1)

    assert len(results) == 1

    bundle = results[0]

    assert bundle["email"] == user.email.lower()
    assert any(
        m["address"] == current_mailbox_email_normalized
        for m in bundle.get("mailboxes", [])
    )


def test_get_abuser_bundles_with_corrupt_encrypted_k_bundle_is_skipped(
    flask_client, monkeypatch
):
    user = create_new_user()
    mark_user_as_abuser(user, "")
    identifier_hmac = calculate_hmac(user.email)
    lookup_entry = AbuserLookup.filter_by(hashed_address=identifier_hmac).first()

    assert lookup_entry is not None

    original_key_data = lookup_entry.bundle_k
    corrupted_key_data = secrets.token_bytes(len(original_key_data))
    lookup_entry.bundle_k = corrupted_key_data
    Session.add(lookup_entry)
    Session.commit()
    bundles = get_abuser_bundles_for_address(user.email, -1)

    assert bundles == []

    lookup_entry.bundle_k = original_key_data
    Session.add(lookup_entry)
    Session.commit()


def test_get_abuser_bundles_with_corrupt_main_bundle_is_skipped(
    flask_client, monkeypatch
):
    user = create_new_user()
    mark_user_as_abuser(user, "")
    ab_data = AbuserData.filter_by(user_id=user.id).first()

    assert ab_data is not None

    original_main_bundle = ab_data.encrypted_bundle
    corrupted_main_bundle = secrets.token_bytes(len(original_main_bundle))
    ab_data.encrypted_bundle = corrupted_main_bundle

    Session.add(ab_data)
    Session.commit()

    bundles = get_abuser_bundles_for_address(user.email, -1)

    assert bundles == []

    ab_data.encrypted_bundle = original_main_bundle
    Session.add(ab_data)
    Session.commit()


def test_archive_and_fetch_flow_end_to_end(flask_client, monkeypatch):
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

    current_mailbox_email_normalized = mailbox.email.lower()
    mark_user_as_abuser(user, "")
    bundles = get_abuser_bundles_for_address(user.email, -1)

    assert len(bundles) == 1

    data = bundles[0]

    assert data is not None
    assert data["email"] == user.email.lower()
    assert data["account_id"] == str(user.id)
    assert any(
        mb["address"] == current_mailbox_email_normalized
        for mb in data.get("mailboxes", [])
    )
