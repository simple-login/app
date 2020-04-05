from flask import url_for

from flask import url_for

from app.config import PAGE_LIMIT
from app.extensions import db
from app.models import User, ApiKey, Alias, Contact, EmailLog


def test_get_aliases_error_without_pagination(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

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
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

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


def test_get_aliases_with_pagination(flask_client):
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
    assert r.json == {"note": "test note"}


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
