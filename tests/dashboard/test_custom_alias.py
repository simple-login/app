from flask import url_for

from app.config import EMAIL_DOMAIN
from app.dashboard.views.custom_alias import (
    signer,
    verify_prefix_suffix,
    available_suffixes,
)
from app.extensions import db
from app.models import Mailbox, CustomDomain
from app.utils import random_word
from tests.utils import login


def test_add_alias_success(flask_client):
    user = login(flask_client)
    db.session.commit()

    word = random_word()
    suffix = f".{word}@{EMAIL_DOMAIN}"
    suffix = signer.sign(suffix).decode()

    r = flask_client.post(
        url_for("dashboard.custom_alias"),
        data={"prefix": "prefix", "suffix": suffix, "mailbox": user.email,},
        follow_redirects=True,
    )

    assert r.status_code == 200
    assert f"Alias prefix.{word}@{EMAIL_DOMAIN} has been created" in str(r.data)


def test_not_show_unverified_mailbox(flask_client):
    """make sure user unverified mailbox is not shown to user"""
    user = login(flask_client)
    db.session.commit()

    Mailbox.create(user_id=user.id, email="m1@example.com", verified=True)
    Mailbox.create(user_id=user.id, email="m2@example.com", verified=False)
    db.session.commit()

    r = flask_client.get(url_for("dashboard.custom_alias"))

    assert "m1@example.com" in str(r.data)
    assert "m2@example.com" not in str(r.data)


def test_verify_prefix_suffix(flask_client):
    user = login(flask_client)
    db.session.commit()

    CustomDomain.create(user_id=user.id, domain="test.com", verified=True)

    assert verify_prefix_suffix(user, "prefix", "@test.com")
    assert not verify_prefix_suffix(user, "prefix", "@abcd.com")

    word = random_word()
    suffix = f".{word}@{EMAIL_DOMAIN}"
    assert verify_prefix_suffix(user, "prefix", suffix)


def test_available_suffixes(flask_client):
    user = login(flask_client)
    db.session.commit()

    CustomDomain.create(user_id=user.id, domain="test.com", verified=True)

    assert len(available_suffixes(user)) > 0

    # first suffix is custom domain
    first_suffix = available_suffixes(user)[0]
    assert first_suffix[0]
    assert first_suffix[1] == "@test.com"
    assert first_suffix[2].startswith("@test.com")
