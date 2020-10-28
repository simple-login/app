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
