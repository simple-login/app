import email
import json
import os
import random
import string
from email.message import EmailMessage
from typing import Optional, Dict

import jinja2
from flask import url_for

from app.models import User
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
