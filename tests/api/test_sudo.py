from random import random

from flask import url_for

from app.api.base import check_sudo_mode_is_active
from app.db import Session
from app.models import ApiKey
from tests.api.utils import get_new_user_and_api_key


def test_enter_sudo_mode(flask_client):
    user, api_key = get_new_user_and_api_key()
    password = f"passwd-{random()}"
    user.set_password(password)
    Session.commit()

    r = flask_client.patch(
        url_for("api.enter_sudo"),
        headers={"Authentication": api_key.code},
        json={"password": "invalid"},
    )

    assert r.status_code == 403
    assert not check_sudo_mode_is_active(ApiKey.get(id=api_key.id))

    r = flask_client.patch(
        url_for("api.enter_sudo"),
        headers={"Authentication": api_key.code},
        json={"password": password},
    )

    assert r.status_code == 200
    assert r.json == {"ok": True}
    assert check_sudo_mode_is_active(ApiKey.get(id=api_key.id))
