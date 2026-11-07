from unittest.mock import patch

import pytest
from flask import url_for

from app import config
from app.db import Session
from app.email_utils import (
    EmailCannotBeUsedReason,
    email_can_be_used_as_mailbox_with_reason,
    personal_email_already_used,
)
from app.mailbox_email_match import equivalence_reasons, get_equivalent_domains
from app.mailbox_utils import MailboxError, create_mailbox
from app.models import Mailbox, User
from app.utils import random_string
from tests.utils import create_new_user


@pytest.fixture(autouse=True)
def skip_mx():
    config.SKIP_MX_LOOKUP_ON_CHECK = True
    yield
    config.SKIP_MX_LOOKUP_ON_CHECK = False


def _local() -> str:
    return f"eq{random_string(8).lower()}"


@pytest.mark.parametrize(
    "email,expected",
    [
        ("John.Doe+tag@gmail.com", ["johndoe@gmail.com", "johndoe@googlemail.com"]),
        ("john.doe@googlemail.com", ["johndoe@googlemail.com", "johndoe@gmail.com"]),
        ("  JohnDoe@GMAIL.com ", ["johndoe@gmail.com", "johndoe@googlemail.com"]),
        ("john.doe+tag@proton.me", ["johndoe@proton.me"]),
        ("john.doe+tag@protonmail.com", ["johndoe@protonmail.com"]),
        ("John.Doe+tag@pm.me", ["johndoe@pm.me"]),
        ("John.Doe+tag@example.com", ["john.doe+tag@example.com"]),
        ("not-an-email", ["not-an-email"]),
    ],
)
def test_get_equivalent_domains(email, expected):
    assert get_equivalent_domains(email) == expected


def test_registration_rejects_equivalent_of_existing_user(flask_client):
    local = _local()
    create_new_user(email=f"{local}@gmail.com")
    Session.commit()

    r = flask_client.post(
        url_for("auth.register"),
        data={
            "email": f"{local[:3]}.{local[3:]}+x@googlemail.com",
            "password": "password",
        },
        follow_redirects=True,
    )

    assert "already used" in r.data.decode()
    assert User.get_by(email=f"{local}@googlemail.com") is None


def test_api_registration_rejects_equivalent_of_existing_user(flask_client):
    local = _local()
    create_new_user(email=f"{local}@googlemail.com")
    Session.commit()

    r = flask_client.post(
        url_for("api.auth_register"),
        json={"email": f"{local}+x@gmail.com", "password": "password"},
    )

    assert r.status_code == 400
    assert User.get_by(email=f"{local}@gmail.com") is None


def test_personal_email_already_used_keeps_unrelated_addresses_free():
    local = _local()
    create_new_user(email=f"{local}@gmail.com")

    assert personal_email_already_used(f"{local}@googlemail.com")
    assert not personal_email_already_used(f"{local}@proton.me")
    assert not personal_email_already_used(f"{local}x@gmail.com")


def test_equivalent_of_disabled_user_email_cannot_be_used_as_mailbox():
    local = _local()
    disabled_user = create_new_user(email=f"{local}@gmail.com")
    disabled_user.disabled = True
    Session.flush()

    assert (
        email_can_be_used_as_mailbox_with_reason(f"{local}+x@googlemail.com")
        == EmailCannotBeUsedReason.EmailOfDisabledUser
    )
    with pytest.raises(MailboxError):
        create_mailbox(create_new_user(), f"{local}@googlemail.com", verified=True)


def test_equivalent_of_disabled_user_mailbox_cannot_be_used_as_mailbox():
    local = _local()
    disabled_user = create_new_user()
    disabled_user.disabled = True
    Mailbox.create(
        user_id=disabled_user.id, email=f"{local}@googlemail.com", verified=True
    )
    Session.flush()

    assert (
        email_can_be_used_as_mailbox_with_reason(f"{local[:2]}.{local[2:]}@gmail.com")
        == EmailCannotBeUsedReason.MailboxOfDisabledUser
    )


def test_registration_rejects_equivalent_of_disabled_user_mailbox(flask_client):
    local = _local()
    disabled_user = create_new_user()
    disabled_user.disabled = True
    Mailbox.create(user_id=disabled_user.id, email=f"{local}@gmail.com", verified=True)
    Session.commit()

    r = flask_client.post(
        url_for("auth.register"),
        data={"email": f"{local}+new@googlemail.com", "password": "password"},
        follow_redirects=True,
    )

    assert (
        "You cannot use this email address as your personal inbox." in r.data.decode()
    )
    assert User.get_by(email=f"{local}@googlemail.com") is None


@pytest.mark.parametrize(
    "registration_email",
    ["{first}.{last}@gmail.com", "{first}{last}+x@googlemail.com"],
)
def test_registration_rejects_disabled_user_mailbox_stored_non_canonical(
    flask_client, registration_email
):
    first, last = _local(), _local()
    disabled_user = create_new_user()
    disabled_user.disabled = True
    Mailbox.create(
        user_id=disabled_user.id, email=f"{first}.{last}@gmail.com", verified=True
    )
    Session.commit()

    r = flask_client.post(
        url_for("auth.register"),
        data={
            "email": registration_email.format(first=first, last=last),
            "password": "password",
        },
        follow_redirects=True,
    )

    assert (
        "You cannot use this email address as your personal inbox." in r.data.decode()
    )
    assert User.get_by(email=f"{first}{last}@gmail.com") is None


def _create_user_with_non_canonical_email(first: str, last: str) -> User:
    user = create_new_user(email=f"{first}.{last}+signup@gmail.com")
    user.default_mailbox.email = f"{_local()}@mailbox.lan"
    Session.flush()
    return user


def test_personal_email_already_used_matches_user_stored_non_canonical():
    first, last = _local(), _local()
    _create_user_with_non_canonical_email(first, last)

    assert personal_email_already_used(f"{first}{last}@gmail.com")
    assert personal_email_already_used(f"{first}{last}+x@googlemail.com")
    assert not personal_email_already_used(f"{first}{last}x@gmail.com")


def test_disabled_user_email_stored_non_canonical_cannot_be_used_as_mailbox():
    first, last = _local(), _local()
    disabled_user = _create_user_with_non_canonical_email(first, last)
    disabled_user.disabled = True
    Session.flush()

    assert (
        email_can_be_used_as_mailbox_with_reason(f"{first}{last}@googlemail.com")
        == EmailCannotBeUsedReason.EmailOfDisabledUser
    )
    with pytest.raises(MailboxError):
        create_mailbox(create_new_user(), f"{first}{last}@gmail.com", verified=True)


@pytest.mark.parametrize(
    "registration_email",
    ["{first}{last}@gmail.com", "{first}.{last}+x@googlemail.com"],
)
def test_registration_rejects_disabled_user_email_stored_non_canonical(
    flask_client, registration_email
):
    first, last = _local(), _local()
    disabled_user = _create_user_with_non_canonical_email(first, last)
    disabled_user.disabled = True
    Session.commit()

    r = flask_client.post(
        url_for("auth.register"),
        data={
            "email": registration_email.format(first=first, last=last),
            "password": "password",
        },
        follow_redirects=True,
    )

    assert (
        "You cannot use this email address as your personal inbox." in r.data.decode()
    )
    assert User.get_by(email=f"{first}{last}@gmail.com") is None


@pytest.mark.parametrize(
    "email,other,expected",
    [
        ("a@gmail.com", "a@gmail.com", []),
        ("A@Gmail.com", "a@gmail.com", []),
        (
            "a@gmail.com",
            "a@googlemail.com",
            ["gmail.com and googlemail.com are equivalent domains"],
        ),
        (
            "a@googlemail.com",
            "a@gmail.com",
            ["googlemail.com and gmail.com are equivalent domains"],
        ),
        ("a+bc@gmail.com", "a@gmail.com", ["+tag is ignored"]),
        ("a.b@gmail.com", "ab@gmail.com", ["dots are ignored"]),
        (
            "a+x@gmail.com",
            "a+x@googlemail.com",
            ["gmail.com and googlemail.com are equivalent domains"],
        ),
        (
            "a+bc@gmail.com",
            "a.@googlemail.com",
            [
                "gmail.com and googlemail.com are equivalent domains",
                "+tag is ignored",
                "dots are ignored",
            ],
        ),
    ],
)
def test_equivalence_reasons(email, other, expected):
    assert equivalence_reasons(email, other) == expected


@pytest.mark.parametrize(
    "stored_template,attempted_template,reasons",
    [
        (
            "{first}{last}@googlemail.com",
            "{first}{last}+bc@gmail.com",
            "gmail.com and googlemail.com are equivalent domains, +tag is ignored",
        ),
        (
            "{first}.{last}+signup@gmail.com",
            "{first}{last}@googlemail.com",
            "googlemail.com and gmail.com are equivalent domains, +tag is ignored, dots are ignored",
        ),
        ("{first}{last}@gmail.com", "{first}{last}@gmail.com", "same address"),
    ],
)
def test_personal_email_already_used_logs_the_matched_user_email(
    stored_template, attempted_template, reasons
):
    first, last = _local(), _local()
    stored = stored_template.format(first=first, last=last)
    attempted = attempted_template.format(first=first, last=last)
    user = create_new_user(email=stored)
    Session.flush()

    with patch("app.email_utils.LOG") as log:
        assert personal_email_already_used(attempted)

    log.i.assert_called_once_with(
        "Email %s is already used by user %s: it is equivalent to %s (%s)",
        attempted,
        user.id,
        stored,
        reasons,
    )


def test_personal_email_already_used_does_not_log_free_addresses():
    with patch("app.email_utils.LOG") as log:
        assert not personal_email_already_used(f"{_local()}@gmail.com")
    log.i.assert_not_called()
