from app.models import CustomDomain
from tests.utils import login


def test_get_setting(flask_client):
    user = login(flask_client)

    r = flask_client.get("/api/setting")
    assert r.status_code == 200
    assert r.json == {
        "alias_generator": "uuid",
        "notification": True,
        "random_alias_default_domain": "sl.local",
    }


def test_get_setting(flask_client):
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
