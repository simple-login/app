import email
import json
import os
import random
import string
from email.message import EmailMessage
from typing import Optional, Dict

import jinja2
from flask import url_for

from app.db import Session
from app.models import User, PartnerUser, UserAliasDeleteAction
from app.proton.proton_partner import get_proton_partner
from app.utils import random_string


def create_new_user(
    email: Optional[str] = None,
    name: Optional[str] = None,
    alias_delete_action: UserAliasDeleteAction = UserAliasDeleteAction.DeleteImmediately,
) -> User:
    if not email:
        email = f"user_{random_token(10)}@mailbox.lan"
    if not name:
        name = "Test User"
    # new user has a different email address
    user = User.create(
        email=email,
        password="password",
        name=name,
        activated=True,
        flush=True,
    )
    user.alias_delete_action = alias_delete_action
    Session.flush()

    return user


def create_partner_linked_user() -> tuple[User, PartnerUser]:
    user = create_new_user()
    partner_user = PartnerUser.create(
        partner_id=get_proton_partner().id,
        user_id=user.id,
        external_user_id=random_token(10),
        flush=True,
    )

    return user, partner_user


def login(flask_client, user: Optional[User] = None) -> User:
    if not user:
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
    return random_token() + ".lan"


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
        return email.message_from_bytes(rendered.encode("utf-8"))


def random_email() -> str:
    return "{rand}@{rand}.com".format(rand=random_string(20))


def fix_rate_limit_after_request():
    from flask import g
    from app.extensions import limiter

    g._rate_limiting_complete = False
    setattr(g, "%s_rate_limiting_complete" % limiter._key_prefix, False)
