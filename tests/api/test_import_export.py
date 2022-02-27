from flask import url_for

from app import alias_utils
from app.db import Session
from app.import_utils import import_from_csv
from app.models import (
    User,
    CustomDomain,
    Mailbox,
    Alias,
    AliasMailbox,
    BatchImport,
    File,
)
from tests.utils import login


def test_export(flask_client):
    # Create users
    user1 = login(flask_client)
    user2 = User.create(
        email="x@y.z", password="password", name="Wrong user", activated=True
    )
    Session.commit()

    # Remove onboarding aliases
    for alias in Alias.filter_by(user_id=user1.id).all():
        alias_utils.delete_alias(alias, user1)
    for alias in Alias.filter_by(user_id=user2.id).all():
        alias_utils.delete_alias(alias, user2)
    Session.commit()

    # Create domains
    CustomDomain.create(
        user_id=user1.id, domain="my-destination-domain.com", verified=True
    )
    CustomDomain.create(
        user_id=user2.id, domain="bad-destionation-domain.com", verified=True
    )
    Session.commit()

    # Create mailboxes
    mailbox1 = Mailbox.create(
        user_id=user1.id, email="destination@my-destination-domain.com", verified=True
    )
    mailbox2 = Mailbox.create(
        user_id=user1.id, email="destination2@my-destination-domain.com", verified=True
    )
    badmailbox1 = Mailbox.create(
        user_id=user2.id,
        email="baddestination@bad-destination-domain.com",
        verified=True,
    )
    Session.commit()

    # Create aliases
    Alias.create(
        user_id=user1.id,
        email="ebay@my-domain.com",
        note="Used on eBay",
        mailbox_id=mailbox1.id,
    )
    alias2 = Alias.create(
        user_id=user1.id,
        email="facebook@my-domain.com",
        note="Used on Facebook, Instagram.",
        mailbox_id=mailbox1.id,
    )
    Alias.create(
        user_id=user2.id,
        email="notmine@my-domain.com",
        note="Should not appear",
        mailbox_id=badmailbox1.id,
    )
    Session.commit()

    # Add second mailbox to an alias
    AliasMailbox.create(
        alias_id=alias2.id,
        mailbox_id=mailbox2.id,
    )
    Session.commit()

    # Export
    r = flask_client.get(url_for("api.export_aliases"))
    assert r.status_code == 200
    assert r.mimetype == "text/csv"
    assert (
        r.data
        == """alias,note,enabled,mailboxes
ebay@my-domain.com,Used on eBay,True,destination@my-destination-domain.com
facebook@my-domain.com,"Used on Facebook, Instagram.",True,destination@my-destination-domain.com destination2@my-destination-domain.com
""".replace(
            "\n", "\r\n"
        ).encode()
    )


def test_import_no_mailboxes_no_domains(flask_client):
    # Create user
    user = login(flask_client)

    # Check start state
    assert len(Alias.filter_by(user_id=user.id).all()) == 1  # Onboarding alias

    alias_data = [
        "alias,note",
        "ebay@my-domain.com,Used on eBay",
        'facebook@my-domain.com,"Used on Facebook, Instagram."',
    ]
    file = File.create(path="/test", commit=True)
    batch_import = BatchImport.create(user_id=user.id, file_id=file.id, commit=True)

    import_from_csv(batch_import, user, alias_data)

    # Should have failed to import anything new because my-domain.com isn't registered
    assert len(Alias.filter_by(user_id=user.id).all()) == 1  # +0


def test_import_no_mailboxes(flask_client):
    # Create user
    user = login(flask_client)

    # Check start state
    assert len(Alias.filter_by(user_id=user.id).all()) == 1  # Onboarding alias

    # Create domain
    CustomDomain.create(
        user_id=user.id, domain="my-domain.com", ownership_verified=True
    )
    Session.commit()

    alias_data = [
        "alias,note",
        "ebay@my-domain.com,Used on eBay",
        'facebook@my-domain.com,"Used on Facebook, Instagram."',
    ]

    file = File.create(path="/test", commit=True)
    batch_import = BatchImport.create(user_id=user.id, file_id=file.id)

    import_from_csv(batch_import, user, alias_data)

    assert len(Alias.filter_by(user_id=user.id).all()) == 3  # +2


def test_import_no_domains(flask_client):
    # Create user
    user = login(flask_client)

    # Check start state
    assert len(Alias.filter_by(user_id=user.id).all()) == 1  # Onboarding alias

    alias_data = [
        "alias,note,mailboxes",
        "ebay@my-domain.com,Used on eBay,destination@my-destination-domain.com",
        'facebook@my-domain.com,"Used on Facebook, Instagram.",destination1@my-destination-domain.com destination2@my-destination-domain.com',
    ]

    file = File.create(path="/test", commit=True)
    batch_import = BatchImport.create(user_id=user.id, file_id=file.id)

    import_from_csv(batch_import, user, alias_data)

    # Should have failed to import anything new because my-domain.com isn't registered
    assert len(Alias.filter_by(user_id=user.id).all()) == 1  # +0


def test_import(flask_client):
    # Create user
    user = login(flask_client)

    # Check start state
    assert len(Alias.filter_by(user_id=user.id).all()) == 1  # Onboarding alias

    # Create domains
    CustomDomain.create(
        user_id=user.id, domain="my-domain.com", ownership_verified=True
    )
    CustomDomain.create(
        user_id=user.id, domain="my-destination-domain.com", ownership_verified=True
    )
    Session.commit()

    # Create mailboxes
    mailbox1 = Mailbox.create(
        user_id=user.id, email="destination@my-destination-domain.com", verified=True
    )
    mailbox2 = Mailbox.create(
        user_id=user.id, email="destination2@my-destination-domain.com", verified=True
    )
    Session.commit()

    alias_data = [
        "alias,note,mailboxes",
        "ebay@my-domain.com,Used on eBay,destination@my-destination-domain.com",
        'facebook@my-domain.com,"Used on Facebook, Instagram.",destination@my-destination-domain.com destination2@my-destination-domain.com',
    ]

    file = File.create(path="/test", commit=True)
    batch_import = BatchImport.create(user_id=user.id, file_id=file.id)

    import_from_csv(batch_import, user, alias_data)

    aliases = Alias.filter_by(user_id=user.id).order_by(Alias.id).all()
    assert len(aliases) == 3  # +2

    # aliases[0] is the onboarding alias, skip it

    # eBay alias
    assert aliases[1].email == "ebay@my-domain.com"
    assert len(aliases[1].mailboxes) == 1
    # First one should be primary
    assert aliases[1].mailbox_id == mailbox1.id
    # Others are sorted
    assert aliases[1].mailboxes[0] == mailbox1

    # Facebook alias
    assert aliases[2].email == "facebook@my-domain.com"
    assert len(aliases[2].mailboxes) == 2
    # First one should be primary
    assert aliases[2].mailbox_id == mailbox1.id
    # Others are sorted
    assert aliases[2].mailboxes[0] == mailbox2
    assert aliases[2].mailboxes[1] == mailbox1
