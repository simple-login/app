import pytest

from app.db import Session
from app.errors import AliasDomainForbidden
from app.models import Alias, Mailbox, AliasMailbox, User, CustomDomain
from tests.utils import create_new_user, random_domain, random_email


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


def test_alias_create_cannot_use_another_users_custom_domain():
    """Alias.create() must reject alias creation on a domain owned by a different user."""
    user_1 = create_new_user()
    user_1_domain = random_domain()
    user_1_custom_domain = CustomDomain.create(
        user_id=user_1.id,
        domain=user_1_domain,
        verified=True,
        flush=True,
    )
    Session.flush()

    user_2 = create_new_user()
    attempted_email = f"attempted@{user_1_domain}"

    with pytest.raises(AliasDomainForbidden):
        Alias.create(
            user_id=user_2.id,
            email=attempted_email,
            mailbox_id=user_2.default_mailbox_id,
            flush=True,
        )

    # User_1 can still create an alias on their own domain
    user_1_alias = Alias.create(
        user_id=user_1.id,
        email=attempted_email,
        mailbox_id=user_1.default_mailbox_id,
        flush=True,
    )
    assert user_1_alias.custom_domain_id == user_1_custom_domain.id
