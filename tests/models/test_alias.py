from app.db import Session
from app.models import Alias, Mailbox, AliasMailbox
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
