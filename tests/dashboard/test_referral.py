from flask import url_for

from app.db import Session
from app.models import Client, Referral, User
from tests.utils import login, random_token


def create_referral(user: User) -> Referral:
    referral = Referral.create(
        user_id=user.id, code=random_token(10), name=random_token(8)
    )
    Session.commit()
    return referral


def create_client(user: User) -> Client:
    client = Client.create_new(name=random_token(8), user_id=user.id)
    Session.commit()
    return client


def test_referral_page_is_closed_to_non_participant(flask_client):
    login(flask_client)

    r = flask_client.get(url_for("dashboard.referral_route"))

    assert r.status_code == 302
    assert r.headers["Location"].endswith(url_for("dashboard.index"))


def test_non_participant_cannot_create_a_referral(flask_client):
    user = login(flask_client)

    r = flask_client.post(
        url_for("dashboard.referral_route"),
        data={"form-name": "create", "code": random_token(10), "name": "test"},
        follow_redirects=True,
    )

    assert r.status_code == 200
    assert 'name="code"' not in r.data.decode()
    assert Referral.filter_by(user_id=user.id).count() == 0


def test_referral_page_still_works_for_participant(flask_client):
    user = login(flask_client)
    referral = create_referral(user)

    r = flask_client.get(url_for("dashboard.referral_route"))

    assert r.status_code == 200
    assert referral.code in r.data.decode()


def test_deleting_the_last_referral_does_not_lock_the_user_out(flask_client):
    """Deleting every code must not revoke access, otherwise it is a one-way door
    out of a program that is closed to new participants."""
    user = login(flask_client)
    referral = create_referral(user)

    r = flask_client.post(
        url_for("dashboard.referral_route"),
        data={"form-name": "delete", "referral-id": referral.id},
        follow_redirects=True,
    )

    assert r.status_code == 200
    assert Referral.filter_by(user_id=user.id).count() == 0
    assert flask_client.get(url_for("dashboard.referral_route")).status_code == 200


def test_client_referral_page_is_closed_to_non_participant(flask_client):
    user = login(flask_client)
    client = create_client(user)

    r = flask_client.get(
        url_for("developer.client_detail_referral", client_id=client.id)
    )

    assert r.status_code == 302
    assert r.headers["Location"].endswith(
        url_for("developer.client_detail", client_id=client.id)
    )
