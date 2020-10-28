import json

from app.models import CustomDomain, AliasGeneratorEnum
from tests.utils import login


def test_get_setting(flask_client):
    user = login(flask_client)

    r = flask_client.get("/api/setting")
    assert r.status_code == 200
    assert r.json == {
        "alias_generator": "word",
        "notification": True,
        "random_alias_default_domain": "sl.local",
    }


def test_update_settings_notification(flask_client):
    user = login(flask_client)
    assert user.notification

    r = flask_client.patch("/api/setting", json={"notification": False})
    assert r.status_code == 200
    assert not user.notification


def test_update_settings_alias_generator(flask_client):
    user = login(flask_client)
    assert user.alias_generator == AliasGeneratorEnum.word.value

    r = flask_client.patch("/api/setting", json={"alias_generator": "invalid"})
    assert r.status_code == 400

    r = flask_client.patch("/api/setting", json={"alias_generator": "uuid"})
    assert r.status_code == 200
    assert user.alias_generator == AliasGeneratorEnum.uuid.value


def test_update_settings_random_alias_default_domain(flask_client):
    user = login(flask_client)
    assert user.default_random_alias_domain() == "sl.local"

    r = flask_client.patch(
        "/api/setting", json={"random_alias_default_domain": "invalid"}
    )
    assert r.status_code == 400

    r = flask_client.patch(
        "/api/setting", json={"random_alias_default_domain": "d1.test"}
    )
    assert r.status_code == 200
    assert user.default_random_alias_domain() == "d1.test"


def test_get_setting_domains(flask_client):
    user = login(flask_client)
    CustomDomain.create(user_id=user.id, domain="ab.cd", verified=True, commit=True)

    r = flask_client.get("/api/setting/domains")
    assert r.status_code == 200
    assert r.json == [
        [True, "d1.test"],
        [True, "d2.test"],
        [True, "sl.local"],
        [False, "ab.cd"],
    ]
