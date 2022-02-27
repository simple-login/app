from app.dashboard.views import alias_transfer
from app.db import Session
from app.models import (
    Alias,
    Mailbox,
    User,
    AliasMailbox,
)
from tests.utils import login


def test_alias_transfer(flask_client):
    user = login(flask_client)
    mb = Mailbox.create(user_id=user.id, email="mb@gmail.com", commit=True)

    alias = Alias.create_new_random(user)
    Session.commit()

    AliasMailbox.create(alias_id=alias.id, mailbox_id=mb.id, commit=True)

    new_user = User.create(
        email="hey@example.com",
        password="password",
        activated=True,
        commit=True,
    )

    Mailbox.create(
        user_id=new_user.id, email="hey2@example.com", verified=True, commit=True
    )

    alias_transfer.transfer(alias, new_user, new_user.mailboxes())

    # refresh from db
    alias = Alias.get(alias.id)
    assert alias.user == new_user
    assert set(alias.mailboxes) == set(new_user.mailboxes())
    assert len(alias.mailboxes) == 2
