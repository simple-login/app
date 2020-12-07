from app.alias_utils import delete_alias
from app.models import CustomDomain, Alias
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


def test_get_custom_domain_trash(flask_client):
    user = login(flask_client)

    cd = CustomDomain.create(
        user_id=user.id, domain="test1.org", verified=True, commit=True
    )

    alias = Alias.create(
        user_id=user.id,
        email="first@test1.org",
        custom_domain_id=cd.id,
        mailbox_id=user.default_mailbox_id,
        commit=True,
    )

    delete_alias(alias, user)

    r = flask_client.get(
        f"/api/custom_domains/{cd.id}/trash",
    )

    for deleted_alias in r.json["aliases"]:
        assert deleted_alias["alias"]
        assert deleted_alias["creation_timestamp"] > 0
