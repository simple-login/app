from flask import url_for

from app.config import MAX_NB_DIRECTORY
from app.models import Directory
from tests.utils import login, random_token


def test_create_directory(flask_client):
    login(flask_client)

    directory_name = random_token()
    r = flask_client.post(
        url_for("dashboard.directory"),
        data={"form-name": "create", "name": directory_name},
        follow_redirects=True,
    )

    assert r.status_code == 200
    assert f"Directory {directory_name} is created" in r.data.decode()
    assert Directory.get_by(name=directory_name) is not None


def test_delete_directory(flask_client):
    """cannot add domain if user personal email uses this domain"""
    user = login(flask_client)
    directory_name = random_token()
    directory = Directory.create(name=directory_name, user_id=user.id, commit=True)

    r = flask_client.post(
        url_for("dashboard.directory"),
        data={"form-name": "delete", "directory_id": directory.id},
        follow_redirects=True,
    )

    assert r.status_code == 200
    assert f"Directory {directory_name} has been deleted" in r.data.decode()
    assert Directory.get_by(name=directory_name) is None


def test_create_directory_in_trash(flask_client):
    user = login(flask_client)
    directory_name = random_token()

    directory = Directory.create(name=directory_name, user_id=user.id, commit=True)

    # delete the directory
    r = flask_client.post(
        url_for("dashboard.directory"),
        data={"form-name": "delete", "directory_id": directory.id},
        follow_redirects=True,
    )
    assert Directory.get_by(name=directory_name) is None

    # try to recreate the directory
    r = flask_client.post(
        url_for("dashboard.directory"),
        data={"form-name": "create", "name": directory_name},
        follow_redirects=True,
    )

    assert r.status_code == 200
    assert (
        f"{directory_name} has been used before and cannot be reused" in r.data.decode()
    )


def test_create_directory_out_of_quota(flask_client):
    user = login(flask_client)

    for i in range(
        MAX_NB_DIRECTORY - Directory.filter(Directory.user_id == user.id).count()
    ):
        Directory.create(name=f"test{i}", user_id=user.id, commit=True)

    assert Directory.filter(Directory.user_id == user.id).count() == MAX_NB_DIRECTORY

    flask_client.post(
        url_for("dashboard.directory"),
        data={"form-name": "create", "name": "test"},
        follow_redirects=True,
    )

    # no new directory is created
    assert Directory.filter(Directory.user_id == user.id).count() == MAX_NB_DIRECTORY
