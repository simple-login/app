from app.db import Session
from app.models import (
    Alias,
    Contact,
)
from tests.utils import login


def test_disable_alias(flask_client):
    user = login(flask_client)
    alias = Alias.create_new_random(user)
    Session.commit()

    assert alias.enabled
    flask_client.post(f"/dashboard/unsubscribe/{alias.id}")
    assert not alias.enabled


def test_block_contact(flask_client):
    user = login(flask_client)
    alias = Alias.first()
    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email="contact@example.com",
        reply_email="re1@SL",
        commit=True,
    )

    assert not contact.block_forward
    flask_client.post(f"/dashboard/block_contact/{contact.id}")
    assert contact.block_forward

    # make sure the page loads
    flask_client.get(f"/dashboard/block_contact/{contact.id}")
