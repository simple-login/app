"""Regression tests for the admin mailbox-ban bypasses (SECBTY-2507)."""

import arrow
import pytest
from flask import url_for

from app import config, mailbox_utils
from app.alias_suffix import signer
from app.config import EMAIL_DOMAIN
from app.constants import JobType
from app.db import Session
from app.email_utils import (
    EmailCannotBeUsedReason,
    email_can_be_used_as_mailbox_with_reason,
)
from app.import_utils import import_from_csv
from app.mailbox_utils import (
    MailboxError,
    admin_disable_mailbox,
    admin_reenable_mailbox,
    create_mailbox,
    is_email_admin_disabled,
    perform_mailbox_email_change,
    request_mailbox_email_change,
    verify_mailbox_code,
)
from app.models import (
    Alias,
    AliasMailbox,
    BatchImport,
    CustomDomain,
    Directory,
    File,
    Job,
    Mailbox,
    MailboxActivation,
    User,
)
from app.utils import canonicalize_email, random_string, random_word
from job_runner import delete_mailbox_job
from tests.api.utils import get_new_user_and_api_key
from tests.utils import (
    create_new_user,
    login,
    random_domain,
    random_email,
    random_token,
)


@pytest.fixture(autouse=True)
def skip_mx():
    config.SKIP_MX_LOOKUP_ON_CHECK = True
    yield
    config.SKIP_MX_LOOKUP_ON_CHECK = False


def _banned_mailbox(email: str | None = None) -> Mailbox:
    owner = create_new_user()
    mailbox = Mailbox.create(
        user_id=owner.id, email=email or random_email(), verified=True, commit=True
    )
    admin_disable_mailbox(mailbox)
    return Mailbox.get(mailbox.id)


def _premium_user():
    user = create_new_user()
    user.lifetime = True
    Session.commit()
    return user


# Finding 1


def test_banned_address_cannot_be_used_as_mailbox():
    banned = _banned_mailbox()
    assert is_email_admin_disabled(banned.email)
    assert (
        email_can_be_used_as_mailbox_with_reason(banned.email)
        == EmailCannotBeUsedReason.MailboxAdminDisabled
    )
    # generic message, does not reveal the ban
    assert "banned" not in EmailCannotBeUsedReason.MailboxAdminDisabled.value.lower()
    with pytest.raises(MailboxError):
        create_mailbox(_premium_user(), banned.email, verified=True)


@pytest.mark.parametrize(
    "banned_email,variant",
    [
        ("bannedperson@gmail.com", "banned.person+x@gmail.com"),
        ("bannedperson@gmail.com", "bannedperson@googlemail.com"),
        ("banned.person@googlemail.com", "BannedPerson+tag@gmail.com"),
        ("bannedperson@proton.me", "bannedperson+x@proton.me"),
        ("bannedperson@protonmail.com", "banned.person+x@protonmail.com"),
        ("bannedperson@pm.me", "BannedPerson+tag@pm.me"),
    ],
)
def test_banned_address_variants_are_rejected(banned_email, variant):
    _banned_mailbox(banned_email)
    assert is_email_admin_disabled(variant)
    with pytest.raises(MailboxError):
        create_mailbox(_premium_user(), variant, verified=True)


def test_ban_covers_variant_mailboxes_and_reenable_agrees():
    base = f"v{random_string(8).lower()}"
    owner1, owner2 = create_new_user(), create_new_user()
    m1 = Mailbox.create(
        user_id=owner1.id, email=f"{base}@gmail.com", verified=True, commit=True
    )
    m2 = Mailbox.create(
        user_id=owner2.id, email=f"{base}+a@gmail.com", verified=True, commit=True
    )
    assert admin_disable_mailbox(m1) == 2
    assert Mailbox.get(m2.id).is_admin_disabled()
    assert admin_reenable_mailbox(m1) == 2
    assert not Mailbox.get(m2.id).is_admin_disabled()
    assert not is_email_admin_disabled(f"{base}@gmail.com")


def test_registration_with_banned_address_rejected(flask_client):
    banned = _banned_mailbox()
    r = flask_client.post(
        url_for("auth.register"),
        data={"email": banned.email, "password": "password"},
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "banned" not in r.data.decode().lower()
    assert (
        "You cannot use this email address as your personal inbox." in r.data.decode()
    )
    from app.models import User

    assert User.get_by(email=banned.email) is None


def test_registration_with_banned_address_variant_rejected(flask_client):
    from app.models import User

    base = f"r{random_string(8).lower()}"
    _banned_mailbox(f"{base}@proton.me")
    variant = f"{base}+x@proton.me"
    r = flask_client.post(
        url_for("auth.register"),
        data={"email": variant, "password": "password"},
        follow_redirects=True,
    )
    assert (
        "You cannot use this email address as your personal inbox." in r.data.decode()
    )
    assert User.get_by(email=canonicalize_email(variant)) is None


def test_api_register_with_banned_address_rejected(flask_client):
    from app.models import User

    banned = _banned_mailbox()
    r = flask_client.post(
        url_for("api.auth_register"),
        json={"email": banned.email, "password": "password"},
    )
    assert r.status_code == 400
    assert User.get_by(email=banned.email) is None


def test_dashboard_mailbox_create_with_banned_address_rejected(flask_client):
    user = login(flask_client)
    user.lifetime = True
    Session.commit()
    banned = _banned_mailbox()
    flask_client.post(
        url_for("dashboard.mailbox_route"),
        data={"form-name": "create", "email": banned.email},
        follow_redirects=True,
    )
    assert Mailbox.filter_by(user_id=user.id, email=banned.email).first() is None


def test_account_email_change_to_banned_address_rejected(flask_client):
    user = login(flask_client)
    banned = _banned_mailbox()
    r = flask_client.post(
        url_for("dashboard.account_setting"),
        data={"form-name": "update-email", "email": banned.email},
        follow_redirects=True,
    )
    assert (
        "You cannot use this email address as your personal inbox." in r.data.decode()
    )
    assert User.get(user.id).email != banned.email


def test_request_mailbox_email_change_to_banned_address_rejected():
    user = _premium_user()
    mailbox = Mailbox.create(
        user_id=user.id, email=random_email(), verified=True, commit=True
    )
    banned = _banned_mailbox()
    with pytest.raises(MailboxError):
        request_mailbox_email_change(user, mailbox, banned.email, send_email=False)


def test_api_mailbox_create_with_banned_address_rejected(flask_client):
    banned = _banned_mailbox()
    user, api_key = get_new_user_and_api_key()
    user.lifetime = True
    Session.commit()
    r = flask_client.post(
        url_for("api.create_mailbox"),
        headers={"Authentication": api_key.code},
        json={"email": banned.email},
    )
    assert r.status_code == 400
    assert Mailbox.filter_by(user_id=user.id, email=banned.email).first() is None


# Finding 2


def test_pending_email_change_confirmed_after_ban_is_rejected():
    user = _premium_user()
    mailbox = Mailbox.create(
        user_id=user.id, email=random_email(), verified=True, commit=True
    )
    new_email = random_email()
    request_mailbox_email_change(user, mailbox, new_email, send_email=False)
    activation = MailboxActivation.filter_by(mailbox_id=mailbox.id).first()
    assert activation is not None
    # simulate a ban racing with the pending change (e.g. new_email set again)
    old_email = mailbox.email
    mailbox.flags = mailbox.flags | Mailbox.FLAG_ADMIN_DISABLED
    mailbox.new_email = new_email
    Session.commit()

    with pytest.raises(MailboxError):
        verify_mailbox_code(user, mailbox.id, activation.code)
    result = perform_mailbox_email_change(mailbox.id)
    assert result.error is not None
    assert Mailbox.get(mailbox.id).email == old_email


def test_confirm_change_route_after_ban_is_rejected(flask_client):
    user = login(flask_client)
    user.lifetime = True
    Session.commit()
    mailbox = Mailbox.create(
        user_id=user.id, email=random_email(), verified=True, commit=True
    )
    request_mailbox_email_change(user, mailbox, random_email(), send_email=False)
    activation = MailboxActivation.filter_by(mailbox_id=mailbox.id).first()
    old_email = mailbox.email
    mailbox.flags = mailbox.flags | Mailbox.FLAG_ADMIN_DISABLED
    mailbox.new_email = random_email()
    Session.commit()

    r = flask_client.get(
        url_for(
            "dashboard.mailbox_confirm_email_change_route",
            mailbox_id=mailbox.id,
            code=activation.code,
        ),
        follow_redirects=True,
    )
    assert "Cannot verify mailbox" in r.data.decode()
    assert Mailbox.get(mailbox.id).email == old_email


def test_admin_disable_clears_pending_change_and_reassigns_default():
    user = _premium_user()
    mailbox = Mailbox.create(
        user_id=user.id, email=random_email(), verified=True, commit=True
    )
    other = Mailbox.get(user.default_mailbox_id)
    user.default_mailbox_id = mailbox.id
    Session.commit()
    request_mailbox_email_change(user, mailbox, random_email(), send_email=False)
    assert Mailbox.get(mailbox.id).new_email is not None

    admin_disable_mailbox(mailbox)

    mb = Mailbox.get(mailbox.id)
    assert mb.new_email is None
    assert MailboxActivation.filter_by(mailbox_id=mb.id).count() == 0
    assert user.default_mailbox_id == other.id


def test_admin_disable_default_without_alternative_keeps_default():
    user = create_new_user()
    default = Mailbox.get(user.default_mailbox_id)
    admin_disable_mailbox(default)
    assert user.default_mailbox_id == default.id


# Finding 3


def test_api_update_alias_singular_mailbox_id_rejects_disabled(flask_client):
    user, api_key = get_new_user_and_api_key()
    banned = _banned_mailbox()
    mb = Mailbox.create(user_id=user.id, email=banned.email, verified=True, commit=True)
    admin_disable_mailbox(mb)
    alias = Alias.create_new_random(user)
    Session.commit()
    original = alias.mailbox_id

    r = flask_client.put(
        url_for("api.update_alias", alias_id=alias.id),
        headers={"Authentication": api_key.code},
        json={"mailbox_id": mb.id},
    )
    assert r.status_code == 400
    assert Alias.get(alias.id).mailbox_id == original


def test_api_update_alias_singular_mailbox_id_keeps_extra_mailboxes(flask_client):
    user, api_key = get_new_user_and_api_key()
    user.lifetime = True
    m2 = Mailbox.create(user_id=user.id, email=random_email(), verified=True)
    m3 = Mailbox.create(user_id=user.id, email=random_email(), verified=True)
    alias = Alias.create_new_random(user)
    Session.commit()
    AliasMailbox.create(alias_id=alias.id, mailbox_id=m2.id, commit=True)

    r = flask_client.put(
        url_for("api.update_alias", alias_id=alias.id),
        headers={"Authentication": api_key.code},
        json={"mailbox_id": m3.id},
    )
    assert r.status_code == 200
    assert Alias.get(alias.id).mailbox_id == m3.id
    assert AliasMailbox.filter_by(alias_id=alias.id, mailbox_id=m2.id).count() == 1


def test_api_custom_alias_v3_rejects_disabled_mailbox(flask_client):
    user = login(flask_client)
    mb = Mailbox.create(user_id=user.id, email=random_email(), verified=True)
    Session.commit()
    admin_disable_mailbox(mb)
    suffix = f".{random_word()}@{EMAIL_DOMAIN}"
    r = flask_client.post(
        "/api/v3/alias/custom/new",
        json={
            "alias_prefix": "prefix",
            "signed_suffix": signer.sign(suffix).decode(),
            "mailbox_ids": [mb.id],
        },
    )
    assert r.status_code == 400
    assert Alias.get_by(email=f"prefix{suffix}") is None


def test_api_custom_alias_v2_reassigns_disabled_default_mailbox(flask_client):
    user = login(flask_client)
    original_default_id = user.default_mailbox_id
    mb = Mailbox.create(user_id=user.id, email=random_email(), verified=True)
    Session.commit()
    user.default_mailbox_id = mb.id
    Session.commit()
    admin_disable_mailbox(mb)
    # default falls back to the user's other enabled mailbox
    assert user.default_mailbox_id == original_default_id
    suffix = f".{random_word()}@{EMAIL_DOMAIN}"
    r = flask_client.post(
        "/api/v2/alias/custom/new",
        json={
            "alias_prefix": "prefix",
            "signed_suffix": signer.sign(suffix).decode(),
        },
    )
    assert r.status_code == 201
    alias = Alias.get_by(email=f"prefix{suffix}")
    assert alias.mailbox_id == original_default_id


def test_api_custom_alias_v2_rejects_disabled_default_mailbox(flask_client):
    user = login(flask_client)
    # no alternative mailbox: disable the user's only (default) mailbox
    admin_disable_mailbox(user.default_mailbox)
    suffix = f".{random_word()}@{EMAIL_DOMAIN}"
    r = flask_client.post(
        "/api/v2/alias/custom/new",
        json={
            "alias_prefix": "prefix",
            "signed_suffix": signer.sign(suffix).decode(),
        },
    )
    assert r.status_code == 400
    assert Alias.get_by(email=f"prefix{suffix}") is None


def test_dashboard_directory_update_rejects_disabled_mailbox(flask_client):
    user = login(flask_client)
    user.lifetime = True
    mb = Mailbox.create(user_id=user.id, email=random_email(), verified=True)
    directory = Directory.create(name=random_token(), user_id=user.id, commit=True)
    admin_disable_mailbox(mb)

    r = flask_client.post(
        url_for("dashboard.directory"),
        data={
            "form-name": "update",
            "directory_id": directory.id,
            "mailbox_ids": [mb.id],
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    # the form choices already exclude admin-disabled mailboxes, so validation
    # fails before the ensure_mailbox_assignable guard is reached
    assert "Invalid request" in r.data.decode()
    assert mb.id not in [m.id for m in Directory.get(directory.id).mailboxes]


def test_delete_mailbox_rejects_disabled_transfer_target():
    user = _premium_user()
    m1 = Mailbox.create(user_id=user.id, email=random_email(), verified=True)
    m2 = Mailbox.create(user_id=user.id, email=random_email(), verified=True)
    Session.commit()
    admin_disable_mailbox(m2)
    with pytest.raises(MailboxError):
        mailbox_utils.delete_mailbox(user, m1.id, m2.id)


def test_delete_mailbox_job_skips_disabled_transfer_target():
    user = _premium_user()
    m1 = Mailbox.create(user_id=user.id, email=random_email(), verified=True)
    m2 = Mailbox.create(user_id=user.id, email=random_email(), verified=True)
    Session.commit()
    alias = Alias.create_new(user, "prefix", mailbox_id=m1.id)
    Session.commit()
    admin_disable_mailbox(m2)
    job = Job.create(
        name=JobType.DELETE_MAILBOX.value,
        payload={"mailbox_id": m1.id, "transfer_mailbox_id": m2.id},
        run_at=arrow.now(),
        commit=True,
    )
    delete_mailbox_job(job)
    assert Mailbox.get(m1.id) is not None
    assert Alias.get(alias.id).mailbox_id == m1.id


def test_import_skips_disabled_mailbox(flask_client):
    user = login(flask_client)
    domain = random_domain()
    CustomDomain.create(user_id=user.id, domain=domain, ownership_verified=True)
    mb = Mailbox.create(user_id=user.id, email=random_email(), verified=True)
    Session.commit()
    admin_disable_mailbox(mb)
    file = File.create(path=f"/{random_token()}", commit=True)
    batch_import = BatchImport.create(user_id=user.id, file_id=file.id, commit=True)

    import_from_csv(
        batch_import,
        user,
        ["alias,note,mailboxes", f"ebay@{domain},note,{mb.email}"],
    )

    alias = Alias.get_by(email=f"ebay@{domain}")
    assert alias is not None
    assert alias.mailbox_id == user.default_mailbox_id
