import csv
from io import StringIO

from flask import url_for

from app import alias_utils
from app.db import Session
from app.import_utils import import_from_csv
from app.models import (
    CustomDomain,
    Mailbox,
    Alias,
    AliasMailbox,
    BatchImport,
    File,
)
from tests.utils import login, create_new_user, random_domain, random_token


def test_export(flask_client):
    # Create users
    user1 = login(flask_client)
    user2 = create_new_user()
    Session.commit()

    # Remove onboarding aliases
    for alias in Alias.filter_by(user_id=user1.id).all():
        alias_utils.delete_alias(alias, user1)
    for alias in Alias.filter_by(user_id=user2.id).all():
        alias_utils.delete_alias(alias, user2)
    Session.commit()

    # Create domains
    ok_domain = CustomDomain.create(
        user_id=user1.id, domain=random_domain(), verified=True
    )
    bad_domain = CustomDomain.create(
        user_id=user2.id, domain=random_domain(), verified=True
    )
    Session.commit()

    # Create mailboxes
    mailbox1 = Mailbox.create(
        user_id=user1.id, email=f"{random_token()}@{ok_domain.domain}", verified=True
    )
    mailbox2 = Mailbox.create(
        user_id=user1.id, email=f"{random_token()}@{ok_domain.domain}", verified=True
    )
    badmailbox1 = Mailbox.create(
        user_id=user2.id,
        email=f"{random_token()}@{bad_domain.domain}",
        verified=True,
    )
    Session.commit()

    # Create aliases
    alias1 = Alias.create(
        user_id=user1.id,
        email=f"{random_token()}@my-domain.com",
        note="Used on eBay",
        mailbox_id=mailbox1.id,
    )
    alias2 = Alias.create(
        user_id=user1.id,
        email=f"{random_token()}@my-domain.com",
        note="Used on Facebook, Instagram.",
        mailbox_id=mailbox1.id,
    )
    Alias.create(
        user_id=user2.id,
        email=f"{random_token()}@my-domain.com",
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
    csv_data = csv.DictReader(StringIO(r.data.decode("utf-8")))
    found_aliases = set()
    for row in csv_data:
        found_aliases.add(row["alias"])
        if row["alias"] == alias1.email:
            assert alias1.note == row["note"]
            assert "True" == row["enabled"]
            assert mailbox1.email == row["mailboxes"]
        elif row["alias"] == alias2.email:
            assert alias2.note == row["note"]
            assert "True" == row["enabled"]
            assert f"{mailbox1.email} {mailbox2.email}" == row["mailboxes"]
        else:
            raise AssertionError("Unknown alias")
    assert set((alias1.email, alias2.email)) == found_aliases


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
    file = File.create(path=f"/{random_token()}", commit=True)
    batch_import = BatchImport.create(user_id=user.id, file_id=file.id, commit=True)

    import_from_csv(batch_import, user, alias_data)

    # Should have failed to import anything new because my-domain.com isn't registered
    assert len(Alias.filter_by(user_id=user.id).all()) == 1  # +0


def test_import_no_mailboxes(flask_client):
    # Create user
    user = login(flask_client)

    # Check start state
    assert len(Alias.filter_by(user_id=user.id).all()) == 1  # Onboarding alias

    domain = random_domain()
    # Create domain
    CustomDomain.create(user_id=user.id, domain=domain, ownership_verified=True)
    Session.commit()

    alias_data = [
        "alias,note",
        f"ebay@{domain},Used on eBay",
        f'facebook@{domain},"Used on Facebook, Instagram."',
    ]

    file = File.create(path=f"/{random_token()}", commit=True)
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

    file = File.create(path=f"/{random_token()}", commit=True)
    batch_import = BatchImport.create(user_id=user.id, file_id=file.id)

    import_from_csv(batch_import, user, alias_data)

    # Should have failed to import anything new because my-domain.com isn't registered
    assert len(Alias.filter_by(user_id=user.id).all()) == 1  # +0


def test_import(flask_client):
    # Create user
    user = login(flask_client)

    # Check start state
    assert len(Alias.filter_by(user_id=user.id).all()) == 1  # Onboarding alias

    domain1 = random_domain()
    domain2 = random_domain()
    # Create domains
    CustomDomain.create(user_id=user.id, domain=domain1, ownership_verified=True)
    CustomDomain.create(user_id=user.id, domain=domain2, ownership_verified=True)
    Session.commit()

    # Create mailboxes
    mailbox1 = Mailbox.create(
        user_id=user.id, email=f"destination@{domain2}", verified=True
    )
    mailbox2 = Mailbox.create(
        user_id=user.id, email=f"destination2@{domain2}", verified=True
    )
    Session.commit()

    alias_data = [
        "alias,note,mailboxes",
        f"ebay@{domain1},Used on eBay,destination@{domain2}",
        f'facebook@{domain1},"Used on Facebook, Instagram.",destination@{domain2} destination2@{domain2}',
    ]

    file = File.create(path=f"/{random_token()}", commit=True)
    batch_import = BatchImport.create(user_id=user.id, file_id=file.id)

    import_from_csv(batch_import, user, alias_data)

    aliases = Alias.filter_by(user_id=user.id).order_by(Alias.id).all()
    assert len(aliases) == 3  # +2

    # aliases[0] is the onboarding alias, skip it

    # eBay alias
    assert aliases[1].email == f"ebay@{domain1}"
    assert len(aliases[1].mailboxes) == 1
    # First one should be primary
    assert aliases[1].mailbox_id == mailbox1.id
    # Others are sorted
    assert aliases[1].mailboxes[0] == mailbox1

    # Facebook alias
    assert aliases[2].email == f"facebook@{domain1}"
    assert len(aliases[2].mailboxes) == 2
    # First one should be primary
    assert aliases[2].mailbox_id == mailbox1.id
    # Others are sorted
    assert aliases[2].mailboxes[0] == mailbox2
    assert aliases[2].mailboxes[1] == mailbox1
