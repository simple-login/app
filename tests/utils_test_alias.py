import csv
from io import StringIO

from flask import url_for

from app.alias_delete import delete_alias
from app.db import Session
from app.models import Alias, CustomDomain, Mailbox, AliasMailbox
from tests.utils import login, create_new_user, random_domain, random_token


def alias_export(flask_client, target_url):
    # Create users
    user1 = login(flask_client)
    user2 = create_new_user()
    Session.commit()

    # Remove onboarding aliases
    for alias in Alias.filter_by(user_id=user1.id).all():
        delete_alias(alias, user1)
    for alias in Alias.filter_by(user_id=user2.id).all():
        delete_alias(alias, user2)
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
    r = flask_client.get(url_for(target_url))
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
