import json

from app.models import CustomDomain
from tests.utils import login


def test_get_custom_domains(flask_client):
    user = login(flask_client)

    CustomDomain.create(user_id=user.id, domain="test1.org", verified=True, commit=True)
    CustomDomain.create(
        user_id=user.id, domain="test2.org", verified=False, commit=True
    )

    r = flask_client.get(
        "/api/custom_domains",
    )

    assert r.status_code == 200
    assert r.json == {
        "custom_domains": [
            {"domain": "test1.org", "id": 1, "nb_alias": 0, "verified": True},
            {"domain": "test2.org", "id": 2, "nb_alias": 0, "verified": False},
        ]
    }
