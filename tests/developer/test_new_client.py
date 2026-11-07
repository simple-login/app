import pytest
from flask import url_for

from app import config
from app.models import Client
from tests.utils import create_new_user, login

NOTICE = b"no longer possible to create new"


@pytest.fixture
def allow_new_clients(monkeypatch):
    monkeypatch.setattr(config, "ALLOW_NEW_OAUTH_CLIENTS", True)


def test_creation_is_disabled_by_default():
    assert config.ALLOW_NEW_OAUTH_CLIENTS is False


def test_new_client_page_redirects_with_notice(flask_client):
    user = login(flask_client, create_new_user())

    r = flask_client.get(url_for("developer.new_client"), follow_redirects=True)

    assert r.status_code == 200
    assert NOTICE in r.data
    assert Client.filter_by(user_id=user.id).count() == 0


def test_new_client_post_does_not_create_client(flask_client):
    user = login(flask_client, create_new_user())

    r = flask_client.post(
        url_for("developer.new_client"),
        data={"name": "my site", "url": "https://example.com"},
        follow_redirects=True,
    )

    assert r.status_code == 200
    assert NOTICE in r.data
    assert Client.filter_by(user_id=user.id).count() == 0


def test_index_has_no_new_website_button(flask_client):
    login(flask_client, create_new_user())

    r = flask_client.get(url_for("developer.index"))

    assert r.status_code == 200
    assert b"Sign in with SimpleLogin" in r.data
    assert b"developer/new_client" not in r.data


def test_new_client_page_works_when_enabled(flask_client, allow_new_clients):
    login(flask_client, create_new_user())

    r = flask_client.get(url_for("developer.new_client"))

    assert r.status_code == 200
    assert NOTICE not in r.data


def test_new_client_post_creates_client_when_enabled(flask_client, allow_new_clients):
    user = login(flask_client, create_new_user())

    r = flask_client.post(
        url_for("developer.new_client"),
        data={"name": "my site", "url": "https://example.com"},
    )

    assert r.status_code == 302
    assert Client.filter_by(user_id=user.id).count() == 1


def test_index_has_new_website_button_when_enabled(flask_client, allow_new_clients):
    login(flask_client, create_new_user())

    r = flask_client.get(url_for("developer.index"))

    assert b"developer/new_client" in r.data
