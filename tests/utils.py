import csv
import email
import json
import os
import random
import string
from email.message import EmailMessage
from io import StringIO
from typing import Optional, Dict

import jinja2
from flask import url_for

from app import alias_utils
from app.db import Session
from app.models import User, Alias, CustomDomain, Mailbox, AliasMailbox
from app.utils import random_string


def create_new_user() -> User:
    # new user has a different email address
    user = User.create(
        email=f"user{random.random()}@mailbox.test",
        password="password",
        name="Test User",
        activated=True,
        flush=True,
    )

    return user


def login(flask_client) -> User:
    user = create_new_user()

    r = flask_client.post(
        url_for("auth.login"),
        data={"email": user.email, "password": "password"},
        follow_redirects=True,
    )

    assert r.status_code == 200
    assert b"/auth/logout" in r.data

    return user


def alias_export(flask_client, target_url):
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


def random_domain() -> str:
    return random_token() + ".test"


def random_token(length: int = 10) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def pretty(d):
    """pretty print as json"""
    print(json.dumps(d, indent=2))


def load_eml_file(
    filename: str, template_values: Optional[Dict[str, str]] = None
) -> EmailMessage:
    emails_dir = os.path.join(
        os.path.dirname(os.path.realpath(__file__)), "example_emls"
    )
    fullpath = os.path.join(emails_dir, filename)
    with open(fullpath) as fd:
        template = jinja2.Template(fd.read())
        if not template_values:
            template_values = {}
        rendered = template.render(**template_values)
        return email.message_from_string(rendered)


def random_email() -> str:
    return "{rand}@{rand}.com".format(rand=random_string(20))
