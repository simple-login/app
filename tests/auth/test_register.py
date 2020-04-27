from flask import url_for


def test_register_success(flask_client):
    """User arrives at the waiting activation page."""
    r = flask_client.post(
        url_for("auth.register"),
        data={"email": "abcd@gmail.com", "password": "password"},
        follow_redirects=True,
    )

    assert r.status_code == 200
    assert b"An email to validate your email is on its way" in r.data


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
