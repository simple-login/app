from random import random

from flask import url_for

from app import config
from app.db import Session
from app.models import Job, ApiToCookieToken
from tests.api.utils import get_new_user_and_api_key


def test_delete_without_sudo(flask_client):
    user, api_key = get_new_user_and_api_key()
    for job in Job.all():
        job.delete(job.id)
    Session.commit()

    r = flask_client.delete(
        url_for("api.delete_user"),
        headers={"Authentication": api_key.code},
    )

    assert r.status_code == 440
    assert Job.count() == 0


def test_delete_with_sudo(flask_client):
    user, api_key = get_new_user_and_api_key()
    password = f"passwd-{random()}"
    user.set_password(password)
    for job in Job.all():
        job.delete(job.id)
    Session.commit()

    r = flask_client.patch(
        url_for("api.enter_sudo"),
        headers={"Authentication": api_key.code},
        json={"password": password},
    )

    assert r.status_code == 200

    r = flask_client.delete(
        url_for("api.delete_user"),
        headers={"Authentication": api_key.code},
    )

    assert r.status_code == 200
    jobs = Job.all()
    assert len(jobs) == 1
    job = jobs[0]
    assert job.name == config.JOB_DELETE_ACCOUNT
    assert job.payload == {"user_id": user.id}


def test_get_cookie_token(flask_client):
    user, api_key = get_new_user_and_api_key()

    r = flask_client.get(
        url_for("api.get_api_session_token"),
        headers={"Authentication": api_key.code},
    )

    assert r.status_code == 200

    code = r.json["token"]
    token = ApiToCookieToken.get_by(code=code)
    assert token is not None
    assert token.user_id == user.id
