import email
import json
import os
import random
import string
from email.message import EmailMessage
from typing import Optional, Dict

import jinja2
from flask import url_for

from app.models import User, Alias


def login(flask_client) -> User:
    # create user, user is activated
    user = User.create(
        email="a@b.c",
        password="password",
        name="Test User",
        activated=True,
        commit=True,
    )

    r = flask_client.post(
        url_for("auth.login"),
        data={"email": "a@b.c", "password": "password"},
        follow_redirects=True,
    )

    assert r.status_code == 200
    assert b"/auth/logout" in r.data

    return user


def random_token(length: int = 10) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def create_random_user() -> User:
    email = "{}@{}.com".format(random_token(), random_token())
    return User.create(
        email=email,
        password="password",
        name="Test User",
        activated=True,
        commit=True,
    )


def create_random_alias(user: User) -> Alias:
    alias_email = "{}@{}.com".format(random_token(), random_token())
    alias = Alias.create(
        user_id=user.id,
        email=alias_email,
        mailbox_id=user.default_mailbox_id,
        commit=True,
    )
    return alias


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
    template = jinja2.Template(open(fullpath).read())
    if not template_values:
        template_values = {}
    rendered = template.render(**template_values)
    return email.message_from_string(rendered)
