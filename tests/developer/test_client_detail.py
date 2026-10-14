from io import BytesIO
from unittest import mock

from flask import url_for

from app.db import Session
from app.models import Client
from tests.utils import create_new_user, login, random_token

HOME_URL = "https://example.com"


def _create_client(user, approved: bool) -> Client:
    client = Client.create_new("original name", user.id)
    client.home_url = HOME_URL
    client.approved = approved
    Session.commit()
    return client


def _edit(flask_client, client, name="original name", url=HOME_URL, icon=None):
    data = {"name": name, "url": url}
    if icon is not None:
        data["icon"] = (BytesIO(icon), "icon.png")
    return flask_client.post(
        url_for("developer.client_detail", client_id=client.id, action="edit"),
        data=data,
        content_type="multipart/form-data",
        follow_redirects=True,
    )


@mock.patch("app.developer.views.client_detail.send_email")
def test_submit_for_approval_escapes_html(send_email_mock, flask_client):
    user = login(flask_client, create_new_user())
    client = _create_client(user, approved=False)
    client.name = "<a href='https://evil.test'>x</a>"
    Session.commit()
    description = f"<script>alert('{random_token()}')</script>"

    r = flask_client.post(
        url_for("developer.client_detail", client_id=client.id, action="submit"),
        data={"description": description},
        follow_redirects=True,
    )

    assert r.status_code == 200
    send_email_mock.assert_called_once()
    kwargs = send_email_mock.call_args.kwargs
    html = kwargs["html"]
    assert "<script>" not in html
    assert "<a href='https://evil.test'>" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;a href=" in html
    assert user.email in html
    assert kwargs["plaintext"].strip() != ""
    assert "\n" not in kwargs["subject"]
