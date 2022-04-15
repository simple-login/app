from flask import url_for

from app.db import Session
from app.models import Notification
from tests.api.utils import get_new_user_and_api_key


def test_get_notifications(flask_client):
    user, api_key = get_new_user_and_api_key()

    # create some notifications
    Notification.create(user_id=user.id, message="Test message 1")
    Notification.create(user_id=user.id, message="Test message 2")
    Session.commit()

    r = flask_client.get(
        "/api/notifications?page=0",
        headers={"Authentication": api_key.code},
    )

    assert r.status_code == 200
    assert r.json["more"] is False
    assert len(r.json["notifications"]) == 2
    for n in r.json["notifications"]:
        assert n["id"] > 0
        assert n["message"]
        assert "title" in n
        assert n["read"] is False
        assert n["created_at"]

    # no more post at the next page
    r = flask_client.get(
        url_for("api.get_notifications", page=1),
        headers={"Authentication": api_key.code},
    )
    assert r.json["more"] is False
    assert len(r.json["notifications"]) == 0


def test_mark_notification_as_read(flask_client):
    user, api_key = get_new_user_and_api_key()

    Notification.create(id=1, user_id=user.id, message="Test message 1")
    Session.commit()

    r = flask_client.post(
        url_for("api.mark_as_read", notification_id=1),
        headers={"Authentication": api_key.code},
    )

    assert r.status_code == 200
    notification = Notification.first()
    assert notification.read
