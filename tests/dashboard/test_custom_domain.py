from flask import url_for

from app.extensions import db
from tests.utils import login


def test_add_domain_success(flask_client):
    user = login(flask_client)
    user.lifetime = True
    db.session.commit()

    r = flask_client.post(
        url_for("dashboard.custom_domain"),
        data={"form-name": "create", "domain": "ab.cd"},
        follow_redirects=True,
    )

    assert r.status_code == 200
    assert b"New domain ab.cd is created" in r.data
