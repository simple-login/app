from typing import Optional

import pytest

from app import config
from app.alias_audit_log_utils import AliasAuditLogAction
from app.contact_utils import create_contact, ContactCreateError, contact_toggle_block
from app.db import Session
from app.models import (
    Alias,
    Contact,
    User,
    AliasAuditLog,
)
from tests.utils import create_new_user, random_email, random_token


def setup_module(module):
    config.DISABLE_CREATE_CONTACTS_FOR_FREE_USERS = True


def teardown_module(module):
    config.DISABLE_CREATE_CONTACTS_FOR_FREE_USERS = False


def create_provider():
    # name auto_created from_partner
    yield ["name", "a@b.c", True, True]
    yield [None, None, True, True]
    yield [None, None, False, True]
    yield [None, None, True, False]
    yield [None, None, False, False]


@pytest.mark.parametrize(
    "name, mail_from, automatic_created, from_partner", create_provider()
)
def test_create_contact(
    name: Optional[str],
    mail_from: Optional[str],
    automatic_created: bool,
    from_partner: bool,
):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    Session.commit()
    email = random_email()
    contact_result = create_contact(
        email,
        alias,
        name=name,
        mail_from=mail_from,
        automatic_created=automatic_created,
        from_partner=from_partner,
    )
    assert contact_result.error is None
    contact = contact_result.contact
    assert contact.user_id == user.id
    assert contact.alias_id == alias.id
    assert contact.website_email == email
    assert contact.name == name
    assert contact.mail_from == mail_from
    assert contact.automatic_created == automatic_created
    assert not contact.invalid_email
    expected_flags = Contact.FLAG_PARTNER_CREATED if from_partner else 0
    assert contact.flags == expected_flags


def test_create_contact_email_email_not_allowed():
    user = create_new_user()
    alias = Alias.create_new_random(user)
    Session.commit()
    contact_result = create_contact("", alias)
    assert contact_result.contact is None
    assert contact_result.error == ContactCreateError.InvalidEmail


def test_create_contact_email_email_allowed():
    user = create_new_user()
    alias = Alias.create_new_random(user)
    Session.commit()
    contact_result = create_contact("", alias, allow_empty_email=True)
    assert contact_result.error is None
    assert contact_result.contact is not None
    assert contact_result.contact.website_email == ""
    assert contact_result.contact.invalid_email


def test_create_contact_name_overrides_email_name():
    user = create_new_user()
    alias = Alias.create_new_random(user)
    Session.commit()
    email = random_email()
    name = random_token()
    contact_result = create_contact(f"superseeded <{email}>", alias, name=name)
    assert contact_result.error is None
    assert contact_result.contact is not None
    assert contact_result.contact.website_email == email
    assert contact_result.contact.name == name


def test_create_contact_name_taken_from_email():
    user = create_new_user()
    alias = Alias.create_new_random(user)
    Session.commit()
    email = random_email()
    name = random_token()
    contact_result = create_contact(f"{name} <{email}>", alias)
    assert contact_result.error is None
    assert contact_result.contact is not None
    assert contact_result.contact.website_email == email
    assert contact_result.contact.name == name


def test_create_contact_empty_name_is_none():
    user = create_new_user()
    alias = Alias.create_new_random(user)
    Session.commit()
    email = random_email()
    contact_result = create_contact(email, alias, name="")
    assert contact_result.error is None
    assert contact_result.contact is not None
    assert contact_result.contact.website_email == email
    assert contact_result.contact.name is None


def test_create_contact_free_user():
    user = create_new_user()
    user.trial_end = None
    user.flags = 0
    alias = Alias.create_new_random(user)
    Session.flush()
    # Free users without the FREE_DISABLE_CREATE_CONTACTS
    result = create_contact(random_email(), alias)
    assert result.error is None
    assert result.created
    assert result.contact is not None
    assert not result.contact.automatic_created
    # Free users with the flag should be able to still create automatic emails
    user.flags = User.FLAG_FREE_DISABLE_CREATE_CONTACTS
    Session.flush()
    result = create_contact(random_email(), alias, automatic_created=True)
    assert result.error is None
    assert result.created
    assert result.contact is not None
    assert result.contact.automatic_created
    # Free users with the flag cannot create non-automatic emails
    result = create_contact(random_email(), alias)
    assert result.error == ContactCreateError.NotAllowed


def test_do_not_allow_invalid_email():
    user = create_new_user()
    alias = Alias.create_new_random(user)
    Session.commit()
    contact_result = create_contact("potato", alias)
    assert contact_result.contact is None
    assert contact_result.error == ContactCreateError.InvalidEmail
    contact_result = create_contact("asdf\x00@gmail.com", alias)
    assert contact_result.contact is None
    assert contact_result.error == ContactCreateError.InvalidEmail


def test_update_name_for_existing():
    user = create_new_user()
    alias = Alias.create_new_random(user)
    Session.commit()
    email = random_email()
    contact_result = create_contact(email, alias)
    assert contact_result.error is None
    assert contact_result.created
    assert contact_result.contact is not None
    assert contact_result.contact.name is None
    name = random_token()
    contact_result = create_contact(email, alias, name=name)
    assert contact_result.error is None
    assert not contact_result.created
    assert contact_result.contact is not None
    assert contact_result.contact.name == name


def test_update_mail_from_for_existing():
    user = create_new_user()
    alias = Alias.create_new_random(user)
    Session.commit()
    email = random_email()
    contact_result = create_contact(email, alias)
    assert contact_result.error is None
    assert contact_result.created
    assert contact_result.contact is not None
    assert contact_result.contact is not None
    assert contact_result.contact.mail_from is None
    mail_from = random_email()
    contact_result = create_contact(email, alias, mail_from=mail_from)
    assert contact_result.error is None
    assert not contact_result.created
    assert contact_result.contact is not None
    assert contact_result.contact.mail_from == mail_from


def test_toggle_contact_block():
    user = create_new_user()
    alias = Alias.create_new_random(user)
    Session.commit()
    email = random_email()
    contact = create_contact(email, alias).contact
    last_log_id = (
        AliasAuditLog.filter_by(alias_id=alias.id)
        .order_by(AliasAuditLog.id.desc())
        .first()
        .id
    )
    assert contact is not None
    assert not contact.block_forward
    # First toggle
    contact_toggle_block(contact)
    audit_log = (
        AliasAuditLog.filter_by(alias_id=alias.id)
        .order_by(AliasAuditLog.id.desc())
        .first()
    )
    assert audit_log.action == AliasAuditLogAction.UpdateContact.value
    assert audit_log.id > last_log_id
    assert contact.block_forward
    last_log_id = audit_log.id
    # Second toggle
    contact_toggle_block(contact)
    audit_log = (
        AliasAuditLog.filter_by(alias_id=alias.id)
        .order_by(AliasAuditLog.id.desc())
        .first()
    )
    assert audit_log.action == AliasAuditLogAction.UpdateContact.value
    assert audit_log.id > last_log_id
    assert not contact.block_forward
