from flask import session as flask_session

from app import user_settings
from app.db import Session
from tests.utils import create_new_user


def test_regenerate_alternative_id_changes_id(flask_client):
    user = create_new_user()
    original_alternative_id = user.alternative_id
    Session.flush()

    user_settings.regenerate_user_alternative_id(user, update_session=False)
    Session.flush()

    assert user.alternative_id != original_alternative_id
    assert user.alternative_id is not None


def test_regenerate_alternative_id_updates_session(flask_client, flask_app):
    user = create_new_user()
    Session.flush()

    # Need to be within a request context to use flask session
    with flask_app.test_request_context():
        flask_session["_user_id"] = "old_session_id"

        user_settings.regenerate_user_alternative_id(user, update_session=True)
        Session.flush()

        assert flask_session["_user_id"] == user.alternative_id


def test_regenerate_alternative_id_does_not_update_session_when_disabled(
    flask_client, flask_app
):
    user = create_new_user()
    Session.flush()

    with flask_app.test_request_context():
        flask_session["_user_id"] = "old_session_id"

        user_settings.regenerate_user_alternative_id(user, update_session=False)
        Session.flush()

        assert flask_session["_user_id"] == "old_session_id"
        assert flask_session["_user_id"] != user.alternative_id


def test_regenerate_alternative_id_generates_valid_uuid(flask_client):
    import uuid

    user = create_new_user()
    Session.flush()

    user_settings.regenerate_user_alternative_id(user, update_session=False)
    Session.flush()

    # Verify it's a valid UUID format
    uuid.UUID(user.alternative_id)
