from flask import url_for

from app import alias_utils
from app.extensions import db
from app.models import User, CustomDomain, Mailbox, Alias, AliasMailbox, ApiKey

def test_export(flask_client):
    # Create users
    user1 = User.create(
        email="a@b.c",
        password="password",
        name="Test User",
        activated=True
    )
    user2 = User.create(
        email="x@y.z",
        password="password",
        name="Wrong user",
        activated=True
    )
    db.session.commit()

    # Remove onboarding aliases
    for alias in Alias.filter_by(user_id=user1.id).all():
        alias_utils.delete_alias(alias, user1)
    for alias in Alias.filter_by(user_id=user2.id).all():
        alias_utils.delete_alias(alias, user2)
    db.session.commit()

    # Create domains
    CustomDomain.create(
        user_id=user1.id,
        domain="my-destination-domain.com",
        verified=True
    )
    CustomDomain.create(
        user_id=user2.id,
        domain="bad-destionation-domain.com",
        verified=True
    )
    db.session.commit()

    # Create mailboxes
    mailbox1 = Mailbox.create(
        user_id=user1.id,
        email="destination@my-destination-domain.com",
        verified=True
    )
    mailbox2 = Mailbox.create(
        user_id=user1.id,
        email="destination2@my-destination-domain.com",
        verified=True
    )
    badmailbox1 = Mailbox.create(
        user_id=user2.id,
        email="baddestination@bad-destination-domain.com",
        verified=True
    )
    db.session.commit()

    # Create aliases
    alias1 = Alias.create(
        user_id=user1.id,
        email="ebay@my-domain.com",
        note="Used on eBay",
        mailbox_id=mailbox1.id
    )
    alias2 = Alias.create(
        user_id=user1.id,
        email="facebook@my-domain.com",
        note="Used on Facebook, Instagram.",
        mailbox_id=mailbox1.id
    )
    alias3 = Alias.create(
        user_id=user2.id,
        email="notmine@my-domain.com",
        note="Should not appear",
        mailbox_id=badmailbox1.id
    )
    db.session.commit()

    # Add second mailbox to an alias
    alias_mailbox = AliasMailbox.create(
        alias_id=alias2.id,
        mailbox_id=mailbox2.id,
    )
    db.session.commit()

    # Export
    # Create api_key
    api_key = ApiKey.create(user1.id, "for test")
    db.session.commit()

    # <<< without hostname >>>
    r = flask_client.get(
        url_for("api.export_aliases"), headers={"Authentication": api_key.code}
    )
    assert r.status_code == 200
    assert r.mimetype == "text/csv"
    assert r.data == """alias,note,enabled,mailboxes
ebay@my-domain.com,Used on eBay,True,destination@my-destination-domain.com
facebook@my-domain.com,"Used on Facebook, Instagram.",True,destination@my-destination-domain.com destination2@my-destination-domain.com
""".replace("\n", "\r\n").encode()