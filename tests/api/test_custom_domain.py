from app.alias_utils import delete_alias
from app.models import CustomDomain, Alias, Mailbox
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
    assert len(r.json["custom_domains"]) == 2
    for domain in r.json["custom_domains"]:
        assert domain["domain_name"]
        assert domain["id"]
        assert domain["nb_alias"] == 0
        assert "is_verified" in domain
        assert "catch_all" in domain
        assert "name" in domain
        assert "random_prefix_generation" in domain
        assert domain["creation_date"]
        assert domain["creation_timestamp"]

        assert domain["mailboxes"]
        for mailbox in domain["mailboxes"]:
            assert "id" in mailbox
            assert "email" in mailbox


def test_update_custom_domains(flask_client):
    user = login(flask_client)

    d1 = CustomDomain.create(
        user_id=user.id, domain="test1.org", verified=True, commit=True
    )

    # test update catch all
    assert d1.catch_all is False
    r = flask_client.patch(f"/api/custom_domains/{d1.id}", json={"catch_all": True})
    assert r.status_code == 200
    assert d1.catch_all is True

    # make sure the full domain json is returned
    cd_json = r.json["custom_domain"]
    assert cd_json["domain_name"]
    assert cd_json["id"] == d1.id
    assert cd_json["nb_alias"] == 0
    assert "is_verified" in cd_json
    assert "catch_all" in cd_json
    assert "name" in cd_json
    assert "random_prefix_generation" in cd_json
    assert cd_json["creation_date"]
    assert cd_json["creation_timestamp"]

    assert cd_json["mailboxes"]
    for mailbox in cd_json["mailboxes"]:
        assert "id" in mailbox
        assert "email" in mailbox

    # test update random_prefix_generation
    assert d1.random_prefix_generation is False
    r = flask_client.patch(
        f"/api/custom_domains/{d1.id}", json={"random_prefix_generation": True}
    )
    assert r.status_code == 200
    assert d1.random_prefix_generation is True

    # test update name
    assert d1.name is None
    r = flask_client.patch(f"/api/custom_domains/{d1.id}", json={"name": "test name"})
    assert r.status_code == 200
    assert d1.name == "test name"

    # test update mailboxes
    assert d1.mailboxes == [user.default_mailbox]
    mb = Mailbox.create(
        user_id=user.id, email="test@example.org", verified=True, commit=True
    )
    r = flask_client.patch(
        f"/api/custom_domains/{d1.id}", json={"mailbox_ids": [mb.id]}
    )
    assert r.status_code == 200
    assert d1.mailboxes == [mb]


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
        assert deleted_alias["deletion_timestamp"] > 0
