from flask import url_for

from app.db import Session
from app.models import DailyMetric


def test_register_success(flask_client):
    r = flask_client.post(
        url_for("auth.register"),
        data={"email": "abcd@gmail.com", "password": "password"},
        follow_redirects=True,
    )

    assert r.status_code == 200
    # User arrives at the waiting activation page.
    assert b"An email to validate your email is on its way" in r.data


def test_register_increment_nb_new_web_non_proton_user(flask_client):
    daily_metric = DailyMetric.get_or_create_today_metric()
    Session.commit()
    nb_new_web_non_proton_user = daily_metric.nb_new_web_non_proton_user

    r = flask_client.post(
        url_for("auth.register"),
        data={"email": "abcd@gmail.com", "password": "password"},
        follow_redirects=True,
    )

    assert r.status_code == 200
    new_daily_metric = DailyMetric.get_or_create_today_metric()
    assert new_daily_metric.nb_new_web_non_proton_user == nb_new_web_non_proton_user + 1


def test_register_disabled(flask_client):
    """User cannot create new account when DISABLE_REGISTRATION."""
    from app import config

    config.DISABLE_REGISTRATION = True

    r = flask_client.post(
        url_for("auth.register"),
        data={"email": "abcd@gmail.com", "password": "password"},
        follow_redirects=True,
    )

    assert b"Registration is closed" in r.data
