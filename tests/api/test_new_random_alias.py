from flask import url_for

from app.config import EMAIL_DOMAIN
from app.extensions import db
from app.models import User, ApiKey, GenEmail


def test_success(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    r = flask_client.post(
        url_for("api.new_random_alias", hostname="www.test.com"),
        headers={"Authentication": api_key.code},
    )

    assert r.status_code == 201
    assert r.json["alias"].endswith(EMAIL_DOMAIN)


def test_out_of_quota(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    # create 3 random alias to run out of quota
    GenEmail.create_new_gen_email(user.id)
    GenEmail.create_new_gen_email(user.id)
    GenEmail.create_new_gen_email(user.id)

    r = flask_client.post(
        url_for("api.new_random_alias", hostname="www.test.com"),
        headers={"Authentication": api_key.code},
    )

    assert r.status_code == 400
    assert r.json == {
        "error": "You have created 3 random aliases, please upgrade to create more"
    }
