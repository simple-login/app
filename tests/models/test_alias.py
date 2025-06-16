from app.db import Session
from app.models import Alias, Mailbox, AliasMailbox, User, CustomDomain
from tests.utils import create_new_user, random_email


def test_duplicated_mailbox_is_returned_only_once():
    user = create_new_user()
    other_mailbox = Mailbox.create(user_id=user.id, email=random_email(), verified=True)
    alias = Alias.create_new_random(user)
    AliasMailbox.create(mailbox_id=other_mailbox.id, alias_id=alias.id)
    AliasMailbox.create(mailbox_id=user.default_mailbox_id, alias_id=alias.id)
    Session.flush()
    alias_mailboxes = alias.mailboxes
    assert len(alias_mailboxes) == 2
    alias_mailbox_id = [mailbox.id for mailbox in alias_mailboxes]
    assert user.default_mailbox_id in alias_mailbox_id
    assert other_mailbox.id in alias_mailbox_id


def test_alias_create_from_partner_flags_also_the_user():
    user = create_new_user()
    Session.flush()
    email = random_email()
    alias = Alias.create(
        user_id=user.id,
        email=email,
        mailbox_id=user.default_mailbox_id,
        flags=Alias.FLAG_PARTNER_CREATED,
        flush=True,
    )
    assert alias.user.flags & User.FLAG_CREATED_ALIAS_FROM_PARTNER > 0


def test_alias_create_from_partner_domain_flags_the_alias():
    user = create_new_user()
    domain = CustomDomain.create(
        domain=random_email(),
        verified=True,
        user_id=user.id,
        partner_id=1,
    )
    Session.flush()
    email = random_email()
    alias = Alias.create(
        user_id=user.id,
        email=email,
        mailbox_id=user.default_mailbox_id,
        custom_domain_id=domain.id,
        flush=True,
    )
    assert alias.flags & Alias.FLAG_PARTNER_CREATED > 0
    assert alias.is_created_from_partner()
