from flask import url_for

from app.config import PAGE_LIMIT
from app.extensions import db
from app.models import User, ApiKey, Alias, Contact, EmailLog, Mailbox
from tests.utils import login


def test_get_aliases_error_without_pagination(flask_client):
    user = User.create(
        email="a@b.c",
        password="password",
        name="Test User",
        activated=True,
        commit=True,
    )

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    r = flask_client.get(
        url_for("api.get_aliases"), headers={"Authentication": api_key.code}
    )

    assert r.status_code == 400
    assert r.json["error"]


def test_get_aliases_with_pagination(flask_client):
    user = User.create(
        email="a@b.c",
        password="password",
        name="Test User",
        activated=True,
        commit=True,
    )

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    # create more aliases than PAGE_LIMIT
    for _ in range(PAGE_LIMIT + 1):
        Alias.create_new_random(user)
    db.session.commit()

    # get aliases on the 1st page, should return PAGE_LIMIT aliases
    r = flask_client.get(
        url_for("api.get_aliases", page_id=0), headers={"Authentication": api_key.code}
    )
    assert r.status_code == 200
    assert len(r.json["aliases"]) == PAGE_LIMIT

    # assert returned field
    for a in r.json["aliases"]:
        assert "id" in a
        assert "email" in a
        assert "creation_date" in a
        assert "creation_timestamp" in a
        assert "nb_forward" in a
        assert "nb_block" in a
        assert "nb_reply" in a
        assert "enabled" in a
        assert "note" in a

    # get aliases on the 2nd page, should return 2 aliases
    # as the total number of aliases is PAGE_LIMIT +2
    # 1 alias is created when user is created
    r = flask_client.get(
        url_for("api.get_aliases", page_id=1), headers={"Authentication": api_key.code}
    )
    assert r.status_code == 200
    assert len(r.json["aliases"]) == 2


def test_get_aliases_query(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    # create more aliases than PAGE_LIMIT
    Alias.create_new(user, "prefix1")
    Alias.create_new(user, "prefix2")
    db.session.commit()

    # get aliases without query, should return 3 aliases as one alias is created when user is created
    r = flask_client.get(
        url_for("api.get_aliases", page_id=0), headers={"Authentication": api_key.code}
    )
    assert r.status_code == 200
    assert len(r.json["aliases"]) == 3

    # get aliases with "prefix1" query, should return 1 alias
    r = flask_client.get(
        url_for("api.get_aliases", page_id=0),
        headers={"Authentication": api_key.code},
        json={"query": "prefix1"},
    )
    assert r.status_code == 200
    assert len(r.json["aliases"]) == 1


def test_get_aliases_v2(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    a0 = Alias.create_new(user, "prefix0")
    a1 = Alias.create_new(user, "prefix1")
    db.session.commit()

    # << Aliases have no activity >>
    r = flask_client.get(
        url_for("api.get_aliases_v2", page_id=0),
        headers={"Authentication": api_key.code},
    )
    assert r.status_code == 200

    r0 = r.json["aliases"][0]
    assert "name" in r0

    # make sure a1 is returned before a0
    assert r0["email"].startswith("prefix1")
    assert "id" in r0["mailbox"]
    assert "email" in r0["mailbox"]

    assert r0["mailboxes"]
    for mailbox in r0["mailboxes"]:
        assert "id" in mailbox
        assert "email" in mailbox

    assert "support_pgp" in r0
    assert not r0["support_pgp"]

    assert "disable_pgp" in r0
    assert not r0["disable_pgp"]

    # << Alias has some activities >>
    c0 = Contact.create(
        user_id=user.id,
        alias_id=a0.id,
        website_email="c0@example.com",
        reply_email="re0@SL",
    )
    db.session.commit()
    EmailLog.create(contact_id=c0.id, user_id=user.id)
    db.session.commit()

    # a1 has more recent activity
    c1 = Contact.create(
        user_id=user.id,
        alias_id=a1.id,
        website_email="c1@example.com",
        reply_email="re1@SL",
    )
    db.session.commit()
    EmailLog.create(contact_id=c1.id, user_id=user.id)
    db.session.commit()

    # get aliases v2
    r = flask_client.get(
        url_for("api.get_aliases_v2", page_id=0),
        headers={"Authentication": api_key.code},
    )
    assert r.status_code == 200

    r0 = r.json["aliases"][0]

    assert r0["latest_activity"]["action"] == "forward"
    assert "timestamp" in r0["latest_activity"]

    assert r0["latest_activity"]["contact"]["email"] == "c1@example.com"
    assert "name" in r0["latest_activity"]["contact"]
    assert "reverse_alias" in r0["latest_activity"]["contact"]


def test_delete_alias(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    alias = Alias.create_new_random(user)
    db.session.commit()

    r = flask_client.delete(
        url_for("api.delete_alias", alias_id=alias.id),
        headers={"Authentication": api_key.code},
    )

    assert r.status_code == 200
    assert r.json == {"deleted": True}


def test_toggle_alias(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    alias = Alias.create_new_random(user)
    db.session.commit()

    r = flask_client.post(
        url_for("api.toggle_alias", alias_id=alias.id),
        headers={"Authentication": api_key.code},
    )

    assert r.status_code == 200
    assert r.json == {"enabled": False}


def test_alias_activities(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    alias = Alias.create_new_random(user)
    db.session.commit()

    # create some alias log
    contact = Contact.create(
        website_email="marketing@example.com",
        reply_email="reply@a.b",
        alias_id=alias.id,
        user_id=alias.user_id,
    )
    db.session.commit()

    for _ in range(int(PAGE_LIMIT / 2)):
        EmailLog.create(contact_id=contact.id, is_reply=True, user_id=contact.user_id)

    for _ in range(int(PAGE_LIMIT / 2) + 2):
        EmailLog.create(contact_id=contact.id, blocked=True, user_id=contact.user_id)

    r = flask_client.get(
        url_for("api.get_alias_activities", alias_id=alias.id, page_id=0),
        headers={"Authentication": api_key.code},
    )

    assert r.status_code == 200
    assert len(r.json["activities"]) == PAGE_LIMIT
    for ac in r.json["activities"]:
        assert ac["from"]
        assert ac["to"]
        assert ac["timestamp"]
        assert ac["action"]
        assert ac["reverse_alias"]

    # second page, should return 1 or 2 results only
    r = flask_client.get(
        url_for("api.get_alias_activities", alias_id=alias.id, page_id=1),
        headers={"Authentication": api_key.code},
    )
    assert len(r.json["activities"]) < 3


def test_update_alias(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    alias = Alias.create_new_random(user)
    db.session.commit()

    r = flask_client.put(
        url_for("api.update_alias", alias_id=alias.id),
        headers={"Authentication": api_key.code},
        json={"note": "test note"},
    )

    assert r.status_code == 200


def test_update_alias_mailbox(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    mb = Mailbox.create(user_id=user.id, email="ab@cd.com", verified=True)

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    alias = Alias.create_new_random(user)
    db.session.commit()

    r = flask_client.put(
        url_for("api.update_alias", alias_id=alias.id),
        headers={"Authentication": api_key.code},
        json={"mailbox_id": mb.id},
    )

    assert r.status_code == 200

    # fail when update with non-existing mailbox
    r = flask_client.put(
        url_for("api.update_alias", alias_id=alias.id),
        headers={"Authentication": api_key.code},
        json={"mailbox_id": -1},
    )
    assert r.status_code == 400


def test_update_alias_name(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    alias = Alias.create_new_random(user)
    db.session.commit()

    r = flask_client.put(
        url_for("api.update_alias", alias_id=alias.id),
        headers={"Authentication": api_key.code},
        json={"name": "Test Name"},
    )

    assert r.status_code == 200
    alias = Alias.get(alias.id)
    assert alias.name == "Test Name"


def test_update_alias_mailboxes(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    mb1 = Mailbox.create(user_id=user.id, email="ab1@cd.com", verified=True)
    mb2 = Mailbox.create(user_id=user.id, email="ab2@cd.com", verified=True)

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    alias = Alias.create_new_random(user)
    db.session.commit()

    r = flask_client.put(
        url_for("api.update_alias", alias_id=alias.id),
        headers={"Authentication": api_key.code},
        json={"mailbox_ids": [mb1.id, mb2.id]},
    )

    assert r.status_code == 200
    alias = Alias.get(alias.id)

    assert alias.mailbox
    assert len(alias._mailboxes) == 1

    # fail when update with empty mailboxes
    r = flask_client.put(
        url_for("api.update_alias", alias_id=alias.id),
        headers={"Authentication": api_key.code},
        json={"mailbox_ids": []},
    )
    assert r.status_code == 400


def test_update_disable_pgp(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    alias = Alias.create_new_random(user)
    db.session.commit()
    assert not alias.disable_pgp

    r = flask_client.put(
        url_for("api.update_alias", alias_id=alias.id),
        headers={"Authentication": api_key.code},
        json={"disable_pgp": True},
    )

    assert r.status_code == 200
    alias = Alias.get(alias.id)
    assert alias.disable_pgp


def test_alias_contacts(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    alias = Alias.create_new_random(user)
    db.session.commit()

    # create some alias log
    for i in range(PAGE_LIMIT + 1):
        contact = Contact.create(
            website_email=f"marketing-{i}@example.com",
            reply_email=f"reply-{i}@a.b",
            alias_id=alias.id,
            user_id=alias.user_id,
        )
        db.session.commit()

        EmailLog.create(contact_id=contact.id, is_reply=True, user_id=contact.user_id)
        db.session.commit()

    r = flask_client.get(
        url_for("api.get_alias_contacts_route", alias_id=alias.id, page_id=0),
        headers={"Authentication": api_key.code},
    )

    assert r.status_code == 200
    assert len(r.json["contacts"]) == PAGE_LIMIT
    for ac in r.json["contacts"]:
        assert ac["creation_date"]
        assert ac["creation_timestamp"]
        assert ac["last_email_sent_date"]
        assert ac["last_email_sent_timestamp"]
        assert ac["contact"]
        assert ac["reverse_alias"]

    # second page, should return 1 result only
    r = flask_client.get(
        url_for("api.get_alias_contacts_route", alias_id=alias.id, page_id=1),
        headers={"Authentication": api_key.code},
    )
    assert len(r.json["contacts"]) == 1


def test_create_contact_route(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    alias = Alias.create_new_random(user)
    db.session.commit()

    r = flask_client.post(
        url_for("api.create_contact_route", alias_id=alias.id),
        headers={"Authentication": api_key.code},
        json={"contact": "First Last <first@example.com>"},
    )

    assert r.status_code == 201
    assert r.json["contact"] == "first@example.com"
    assert "creation_date" in r.json
    assert "creation_timestamp" in r.json
    assert r.json["last_email_sent_date"] is None
    assert r.json["last_email_sent_timestamp"] is None
    assert r.json["reverse_alias"]

    # re-add a contact, should return 409
    r = flask_client.post(
        url_for("api.create_contact_route", alias_id=alias.id),
        headers={"Authentication": api_key.code},
        json={"contact": "First2 Last2 <first@example.com>"},
    )
    assert r.status_code == 409


def test_create_contact_route_empty_contact_address(flask_client):
    login(flask_client)
    alias = Alias.query.first()

    r = flask_client.post(
        url_for("api.create_contact_route", alias_id=alias.id),
        json={"contact": ""},
    )

    assert r.status_code == 400
    assert r.json["error"] == "Contact cannot be empty"


def test_create_contact_route_invalid_contact_email(flask_client):
    login(flask_client)
    alias = Alias.query.first()

    r = flask_client.post(
        url_for("api.create_contact_route", alias_id=alias.id),
        json={"contact": "with space@gmail.com"},
    )

    assert r.status_code == 400
    assert r.json["error"] == "invalid contact email with space@gmail.com"


def test_delete_contact(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    alias = Alias.create_new_random(user)
    db.session.commit()

    contact = Contact.create(
        alias_id=alias.id,
        website_email="contact@example.com",
        reply_email="reply+random@sl.io",
        user_id=alias.user_id,
    )
    db.session.commit()

    r = flask_client.delete(
        url_for("api.delete_contact", contact_id=contact.id),
        headers={"Authentication": api_key.code},
    )

    assert r.status_code == 200
    assert r.json == {"deleted": True}


def test_get_alias(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    # create more aliases than PAGE_LIMIT
    alias = Alias.create_new_random(user)
    db.session.commit()

    # get aliases on the 1st page, should return PAGE_LIMIT aliases
    r = flask_client.get(
        url_for("api.get_alias", alias_id=alias.id),
        headers={"Authentication": api_key.code},
    )
    assert r.status_code == 200

    # assert returned field
    res = r.json
    assert "id" in res
    assert "email" in res
    assert "creation_date" in res
    assert "creation_timestamp" in res
    assert "nb_forward" in res
    assert "nb_block" in res
    assert "nb_reply" in res
    assert "enabled" in res
    assert "note" in res
