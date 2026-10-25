from flask import url_for

from app.db import Session
from app.models import Notification
from tests.api.utils import get_new_user_and_api_key
from tests.utils import login, random_token

# A notification title can contain data lifted verbatim from an inbound email's
# From header (e.g. contact address in email_handler.py bounce notifications),
# which is NOT constrained by email-validator the way an alias local part is.
# It must never reach an HTML/JS sink unescaped, in any of the three places a
# title is rendered.


def test_notifications_list_page_escapes_title(flask_client):
    user = login(flask_client)

    marker = random_token()
    payload = f"<img src=x onerror=alert`{marker}`>"
    Notification.create(user_id=user.id, title=payload, message="body", commit=True)

    r = flask_client.get(url_for("dashboard.notifications_route"))
    assert r.status_code == 200
    body = r.data.decode()

    # the raw tag must not appear; only its escaped form may
    assert payload not in body
    assert "&lt;img" in body


def test_single_notification_page_escapes_title(flask_client):
    user = login(flask_client)

    marker = random_token()
    payload = f"<img src=x onerror=alert`{marker}`>"
    notification_id = Notification.create(
        user_id=user.id, title=payload, message="body", commit=True
    ).id

    r = flask_client.get(
        url_for("dashboard.notification_route", notification_id=notification_id)
    )
    assert r.status_code == 200
    body = r.data.decode()

    assert payload not in body
    assert "&lt;img" in body


def test_notification_bell_renders_title_as_text_not_html(flask_client):
    """
    The bell dropdown (header.html, present on every dashboard page) is a Vue
    component that fetches titles as JSON and binds them. Binding the title with
    v-html would execute markup client-side; assert it uses v-text instead.
    """
    login(flask_client)

    r = flask_client.get(url_for("dashboard.index"))
    assert r.status_code == 200
    body = r.data.decode()

    assert 'v-text="notification.title"' in body
    assert 'v-html="notification.title' not in body


def test_notification_api_returns_title_as_json_value(flask_client):
    """
    The API is the data source for the bell. It must hand back the title as a
    JSON string value (data), never as pre-rendered HTML.
    """
    user, api_key = get_new_user_and_api_key()
    marker = random_token()
    payload = f"<img src=x onerror=alert`{marker}`>"
    Notification.create(user_id=user.id, title=payload, message="body", commit=True)
    Session.commit()

    r = flask_client.get(
        url_for("api.get_notifications", page=0),
        headers={"Authentication": api_key.code},
    )
    assert r.status_code == 200
    # JSON transport carries the title verbatim as a value; the escaping
    # boundary is the client-side v-text binding, verified above.
    assert r.json["notifications"][0]["title"] == payload
