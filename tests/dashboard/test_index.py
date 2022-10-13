from flask import url_for, g

from app import config
from app.models import (
    Alias,
)
from tests.utils import login


def test_create_random_alias_success(flask_client):
    user = login(flask_client)
    assert Alias.filter(Alias.user_id == user.id).count() == 1

    r = flask_client.post(
        url_for("dashboard.index"),
        data={"form-name": "create-random-email"},
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert Alias.filter(Alias.user_id == user.id).count() == 2


def test_too_many_requests(flask_client):
    config.DISABLE_RATE_LIMIT = False
    login(flask_client)

    # can't create more than 5 aliases in 1 minute
    for _ in range(7):
        r = flask_client.post(
            url_for("dashboard.index"),
            data={"form-name": "create-random-email"},
            follow_redirects=True,
        )

        # to make flask-limiter work with unit test
        # https://github.com/alisaifee/flask-limiter/issues/147#issuecomment-642683820
        g._rate_limiting_complete = False
    else:
        # last request
        assert r.status_code == 429
        assert "Whoa, slow down there, pardner!" in str(r.data)
