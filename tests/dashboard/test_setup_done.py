from flask import url_for

from tests.utils import login


def test_setup_done(flask_client):
    login(flask_client)

    r = flask_client.get(
        url_for("dashboard.setup_done"),
    )

    assert r.status_code == 302
    # user is redirected to the dashboard page
    assert r.headers["Location"].endswith("/dashboard/")
    assert "setup_done=true" in r.headers["Set-Cookie"]
