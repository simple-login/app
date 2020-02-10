from flask import url_for

from app.config import EMAIL_DOMAIN
from app.extensions import db
from app.utils import random_word
from tests.utils import login


def test_add_alias_success(flask_client):
    user = login(flask_client)
    db.session.commit()

    word = random_word()

    r = flask_client.post(
        url_for("dashboard.custom_alias"),
        data={
            "prefix": "prefix",
            "suffix": f".{word}@{EMAIL_DOMAIN}",
            "mailbox": user.email,
        },
        follow_redirects=True,
    )

    assert r.status_code == 200
    assert f"Alias prefix.{word}@{EMAIL_DOMAIN} has been created" in str(r.data)
