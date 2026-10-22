from flask import url_for

from app.models import Client
from tests.utils import create_new_user, login


def test_new_client_page_redirects_with_notice(flask_client):
    user = login(flask_client, create_new_user())

    r = flask_client.get(url_for("developer.new_client"), follow_redirects=True)

    assert r.status_code == 200
    assert b"no longer possible to create new" in r.data
    assert Client.filter_by(user_id=user.id).count() == 0


def test_new_client_post_does_not_create_client(flask_client):
    user = login(flask_client, create_new_user())

    r = flask_client.post(
        url_for("developer.new_client"),
        data={"name": "my site", "url": "https://example.com"},
        follow_redirects=True,
    )

    assert r.status_code == 200
    assert b"no longer possible to create new" in r.data
    assert Client.filter_by(user_id=user.id).count() == 0


def test_index_has_no_new_website_button(flask_client):
    login(flask_client, create_new_user())

    r = flask_client.get(url_for("developer.index"))

    assert r.status_code == 200
    assert b"Sign in with SimpleLogin" in r.data
    assert b"developer/new_client" not in r.data
