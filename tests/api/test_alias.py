import arrow
from flask import url_for

# Need to import directly from config to allow modification from the tests
from app import config
from app.db import Session
from app.email_utils import is_reverse_alias
from app.models import User, Alias, Contact, EmailLog, Mailbox
from tests.api.utils import get_new_user_and_api_key
from tests.utils import login, random_domain


def test_get_aliases_error_without_pagination(flask_client):
    user, api_key = get_new_user_and_api_key()

    r = flask_client.get(
        url_for("api.get_aliases"), headers={"Authentication": api_key.code}
    )

    assert r.status_code == 400
    assert r.json["error"]


def test_get_aliases_with_pagination(flask_client):
    user, api_key = get_new_user_and_api_key()

    # create more aliases than config.PAGE_LIMIT
    for _ in range(config.PAGE_LIMIT + 1):
        Alias.create_new_random(user)
    Session.commit()

    # get aliases on the 1st page, should return config.PAGE_LIMIT aliases
    r = flask_client.get(
        url_for("api.get_aliases", page_id=0), headers={"Authentication": api_key.code}
    )
    assert r.status_code == 200
    assert len(r.json["aliases"]) == config.PAGE_LIMIT

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
    # as the total number of aliases is config.PAGE_LIMIT +2
    # 1 alias is created when user is created
    r = flask_client.get(
        url_for("api.get_aliases", page_id=1), headers={"Authentication": api_key.code}
    )
    assert r.status_code == 200
    assert len(r.json["aliases"]) == 2


def test_get_aliases_query(flask_client):
    user, api_key = get_new_user_and_api_key()

    # create more aliases than config.PAGE_LIMIT
    Alias.create_new(user, "prefix1")
    Alias.create_new(user, "prefix2")
    Session.commit()

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
    user = login(flask_client)

    a0 = Alias.create_new(user, "prefix0")
    a1 = Alias.create_new(user, "prefix1")
    Session.commit()

    # << Aliases have no activity >>
    r = flask_client.get("/api/v2/aliases?page_id=0")
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
        commit=True,
    )
    EmailLog.create(
        contact_id=c0.id, user_id=user.id, alias_id=c0.alias_id, commit=True
    )

    # a1 has more recent activity
    c1 = Contact.create(
        user_id=user.id,
        alias_id=a1.id,
        website_email="c1@example.com",
        reply_email="re1@SL",
        commit=True,
    )
    EmailLog.create(
        contact_id=c1.id, user_id=user.id, alias_id=c1.alias_id, commit=True
    )

    r = flask_client.get("/api/v2/aliases?page_id=0")
    assert r.status_code == 200

    r0 = r.json["aliases"][0]

    assert r0["latest_activity"]["action"] == "forward"
    assert "timestamp" in r0["latest_activity"]

    assert r0["latest_activity"]["contact"]["email"] == "c1@example.com"
    assert "name" in r0["latest_activity"]["contact"]
    assert "reverse_alias" in r0["latest_activity"]["contact"]
    assert "pinned" in r0


def test_get_pinned_aliases_v2(flask_client):
    user = login(flask_client)

    a0 = Alias.create_new(user, "prefix0")
    a0.pinned = True
    Session.commit()

    r = flask_client.get("/api/v2/aliases?page_id=0")
    assert r.status_code == 200
    # the default alias (created when user is created) and a0 are returned
    assert len(r.json["aliases"]) == 2

    r = flask_client.get("/api/v2/aliases?page_id=0&pinned=true")
    assert r.status_code == 200
    # only a0 is returned
    assert len(r.json["aliases"]) == 1
    assert r.json["aliases"][0]["id"] == a0.id


def test_get_disabled_aliases_v2(flask_client):
    user = login(flask_client)

    a0 = Alias.create_new(user, "prefix0")
    a0.enabled = False
    Session.commit()

    r = flask_client.get("/api/v2/aliases?page_id=0")
    assert r.status_code == 200
    # the default alias (created when user is created) and a0 are returned
    assert len(r.json["aliases"]) == 2

    r = flask_client.get("/api/v2/aliases?page_id=0&disabled=true")
    assert r.status_code == 200
    # only a0 is returned
    assert len(r.json["aliases"]) == 1
    assert r.json["aliases"][0]["id"] == a0.id


def test_get_enabled_aliases_v2(flask_client):
    user = login(flask_client)

    a0 = Alias.create_new(user, "prefix0")
    a0.enabled = False
    Session.commit()

    r = flask_client.get("/api/v2/aliases?page_id=0")
    assert r.status_code == 200
    # the default alias (created when user is created) and a0 are returned
    assert len(r.json["aliases"]) == 2

    r = flask_client.get("/api/v2/aliases?page_id=0&enabled=true")
    assert r.status_code == 200
    # only the first alias is returned
    assert len(r.json["aliases"]) == 1
    assert r.json["aliases"][0]["id"] != a0.id


def test_delete_alias(flask_client):
    user = login(flask_client)

    alias = Alias.create_new_random(user)
    Session.commit()

    r = flask_client.delete(
        url_for("api.delete_alias", alias_id=alias.id),
    )

    assert r.status_code == 200
    assert r.json == {"deleted": True}


def test_toggle_alias(flask_client):
    user, api_key = get_new_user_and_api_key()

    alias = Alias.create_new_random(user)
    Session.commit()

    r = flask_client.post(
        url_for("api.toggle_alias", alias_id=alias.id),
        headers={"Authentication": api_key.code},
    )

    assert r.status_code == 200
    assert r.json == {"enabled": False}


def test_alias_activities(flask_client):
    user, api_key = get_new_user_and_api_key()

    alias = Alias.create_new_random(user)
    Session.commit()

    # create some alias log
    contact = Contact.create(
        website_email="marketing@example.com",
        reply_email="reply@a.b",
        alias_id=alias.id,
        user_id=alias.user_id,
    )
    Session.commit()

    for _ in range(int(config.PAGE_LIMIT / 2)):
        EmailLog.create(
            contact_id=contact.id,
            is_reply=True,
            user_id=contact.user_id,
            alias_id=contact.alias_id,
        )

    for _ in range(int(config.PAGE_LIMIT / 2) + 2):
        EmailLog.create(
            contact_id=contact.id,
            blocked=True,
            user_id=contact.user_id,
            alias_id=contact.alias_id,
        )

    r = flask_client.get(
        url_for("api.get_alias_activities", alias_id=alias.id, page_id=0),
        headers={"Authentication": api_key.code},
    )

    assert r.status_code == 200
    assert len(r.json["activities"]) == config.PAGE_LIMIT
    for ac in r.json["activities"]:
        assert ac["from"]
        assert ac["to"]
        assert ac["timestamp"]
        assert ac["action"]
        assert ac["reverse_alias"]
        assert ac["reverse_alias_address"]

    # second page, should return 1 or 2 results only
    r = flask_client.get(
        url_for("api.get_alias_activities", alias_id=alias.id, page_id=1),
        headers={"Authentication": api_key.code},
    )
    assert len(r.json["activities"]) < 3


def test_update_alias(flask_client):
    user, api_key = get_new_user_and_api_key()

    alias = Alias.create_new_random(user)
    Session.commit()

    r = flask_client.put(
        url_for("api.update_alias", alias_id=alias.id),
        headers={"Authentication": api_key.code},
        json={"note": "test note"},
    )

    assert r.status_code == 200


def test_update_alias_mailbox(flask_client):
    user, api_key = get_new_user_and_api_key()

    mb = Mailbox.create(user_id=user.id, email="ab@cd.com", verified=True)

    alias = Alias.create_new_random(user)
    Session.commit()

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
    user, api_key = get_new_user_and_api_key()

    alias = Alias.create_new_random(user)
    Session.commit()

    r = flask_client.put(
        url_for("api.update_alias", alias_id=alias.id),
        headers={"Authentication": api_key.code},
        json={"name": "Test Name"},
    )
    assert r.status_code == 200
    alias = Alias.get(alias.id)
    assert alias.name == "Test Name"

    # update name with linebreak
    r = flask_client.put(
        url_for("api.update_alias", alias_id=alias.id),
        headers={"Authentication": api_key.code},
        json={"name": "Test \nName"},
    )
    assert r.status_code == 200
    alias = Alias.get(alias.id)
    assert alias.name == "Test Name"


def test_update_alias_mailboxes(flask_client):
    user, api_key = get_new_user_and_api_key()

    mb1 = Mailbox.create(user_id=user.id, email="ab1@cd.com", verified=True)
    mb2 = Mailbox.create(user_id=user.id, email="ab2@cd.com", verified=True)

    alias = Alias.create_new_random(user)
    Session.commit()

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
    user, api_key = get_new_user_and_api_key()

    alias = Alias.create_new_random(user)
    Session.commit()
    assert not alias.disable_pgp

    r = flask_client.put(
        url_for("api.update_alias", alias_id=alias.id),
        headers={"Authentication": api_key.code},
        json={"disable_pgp": True},
    )

    assert r.status_code == 200
    alias = Alias.get(alias.id)
    assert alias.disable_pgp


def test_update_pinned(flask_client):
    user = login(flask_client)

    alias = Alias.filter_by(user_id=user.id).first()
    assert not alias.pinned

    r = flask_client.patch(
        url_for("api.update_alias", alias_id=alias.id),
        json={"pinned": True},
    )

    assert r.status_code == 200
    assert alias.pinned


def test_alias_contacts(flask_client):
    user = login(flask_client)

    alias = Alias.create_new_random(user)
    Session.commit()

    # create some alias log
    for i in range(config.PAGE_LIMIT + 1):
        contact = Contact.create(
            website_email=f"marketing-{i}@example.com",
            reply_email=f"reply-{i}@a.b",
            alias_id=alias.id,
            user_id=alias.user_id,
        )
        Session.commit()

        EmailLog.create(
            contact_id=contact.id,
            is_reply=True,
            user_id=contact.user_id,
            alias_id=contact.alias_id,
        )
        Session.commit()

    r = flask_client.get(f"/api/aliases/{alias.id}/contacts?page_id=0")

    assert r.status_code == 200
    assert len(r.json["contacts"]) == config.PAGE_LIMIT
    for ac in r.json["contacts"]:
        assert ac["creation_date"]
        assert ac["creation_timestamp"]
        assert ac["last_email_sent_date"]
        assert ac["last_email_sent_timestamp"]
        assert ac["contact"]
        assert ac["reverse_alias"]
        assert ac["reverse_alias_address"]
        assert "block_forward" in ac

    # second page, should return 1 result only
    r = flask_client.get(f"/api/aliases/{alias.id}/contacts?page_id=1")
    assert len(r.json["contacts"]) == 1


def test_create_contact_route(flask_client):
    user, api_key = get_new_user_and_api_key()

    alias = Alias.create_new_random(user)
    Session.commit()

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
    assert r.json["reverse_alias_address"]
    assert r.json["existed"] is False

    # re-add a contact, should return 200
    r = flask_client.post(
        url_for("api.create_contact_route", alias_id=alias.id),
        headers={"Authentication": api_key.code},
        json={"contact": "First2 Last2 <first@example.com>"},
    )
    assert r.status_code == 200
    assert r.json["existed"]


def test_create_contact_route_invalid_alias(flask_client):
    user, api_key = get_new_user_and_api_key()
    other_user, other_api_key = get_new_user_and_api_key()

    alias = Alias.create_new_random(other_user)
    Session.commit()

    r = flask_client.post(
        url_for("api.create_contact_route", alias_id=alias.id),
        headers={"Authentication": api_key.code},
        json={"contact": "First Last <first@example.com>"},
    )

    assert r.status_code == 403


def test_create_contact_route_free_users(flask_client):
    user, api_key = get_new_user_and_api_key()

    alias = Alias.create_new_random(user)
    Session.commit()
    # On trial, should be ok
    r = flask_client.post(
        url_for("api.create_contact_route", alias_id=alias.id),
        headers={"Authentication": api_key.code},
        json={"contact": f"First Last <first@{random_domain()}>"},
    )
    assert r.status_code == 201

    # End trial but allow via flags for older free users
    user.trial_end = arrow.now()
    user.flags = 0
    Session.commit()
    r = flask_client.post(
        url_for("api.create_contact_route", alias_id=alias.id),
        headers={"Authentication": api_key.code},
        json={"contact": f"First Last <first@{random_domain()}>"},
    )
    assert r.status_code == 201

    # End trial and disallow for new free users. Config should allow it
    user.flags = User.FLAG_FREE_DISABLE_CREATE_ALIAS
    Session.commit()
    r = flask_client.post(
        url_for("api.create_contact_route", alias_id=alias.id),
        headers={"Authentication": api_key.code},
        json={"contact": f"First Last <first@{random_domain()}>"},
    )
    assert r.status_code == 201

    # Set the global config to disable free users from create contacts
    config.DISABLE_CREATE_CONTACTS_FOR_FREE_USERS = True
    r = flask_client.post(
        url_for("api.create_contact_route", alias_id=alias.id),
        headers={"Authentication": api_key.code},
        json={"contact": f"First Last <first@{random_domain()}>"},
    )
    assert r.status_code == 403
    config.DISABLE_CREATE_CONTACTS_FOR_FREE_USERS = False


def test_create_contact_route_empty_contact_address(flask_client):
    user = login(flask_client)
    alias = Alias.filter_by(user_id=user.id).first()

    r = flask_client.post(
        url_for("api.create_contact_route", alias_id=alias.id),
        json={"contact": ""},
    )

    assert r.status_code == 400
    assert r.json["error"] == "Empty address is not a valid email address"


def test_create_contact_route_invalid_contact_email(flask_client):
    user = login(flask_client)
    alias = Alias.filter_by(user_id=user.id).first()

    r = flask_client.post(
        url_for("api.create_contact_route", alias_id=alias.id),
        json={"contact": "@gmail.com"},
    )

    assert r.status_code == 400
    assert r.json["error"] == "@gmail.com is not a valid email address"


def test_delete_contact(flask_client):
    user, api_key = get_new_user_and_api_key()

    alias = Alias.create_new_random(user)
    Session.commit()

    contact = Contact.create(
        alias_id=alias.id,
        website_email="contact@example.com",
        reply_email="reply+random@sl.io",
        user_id=alias.user_id,
    )
    Session.commit()

    r = flask_client.delete(
        url_for("api.delete_contact", contact_id=contact.id),
        headers={"Authentication": api_key.code},
    )

    assert r.status_code == 200
    assert r.json == {"deleted": True}


def test_get_alias(flask_client):
    user, api_key = get_new_user_and_api_key()

    # create more aliases than config.PAGE_LIMIT
    alias = Alias.create_new_random(user)
    Session.commit()

    # get aliases on the 1st page, should return config.PAGE_LIMIT aliases
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
    assert "pinned" in res


def test_is_reverse_alias(flask_client):
    assert is_reverse_alias("ra+abcd@sl.local")
    assert is_reverse_alias("reply+abcd@sl.local")

    assert not is_reverse_alias("ra+abcd@test.org")
    assert not is_reverse_alias("reply+abcd@test.org")
    assert not is_reverse_alias("abcd@test.org")


def test_toggle_contact(flask_client):
    user = login(flask_client)

    alias = Alias.create_new_random(user)
    Session.commit()

    contact = Contact.create(
        alias_id=alias.id,
        website_email="contact@example.com",
        reply_email="reply+random@sl.io",
        user_id=alias.user_id,
    )
    Session.commit()

    r = flask_client.post(f"/api/contacts/{contact.id}/toggle")

    assert r.status_code == 200
    assert r.json == {"block_forward": True}


def test_get_aliases_disabled_account(flask_client):
    user, api_key = get_new_user_and_api_key()

    r = flask_client.get(
        "/api/v2/aliases?page_id=0",
        headers={"Authentication": api_key.code},
    )
    assert r.status_code == 200

    user.disabled = True
    Session.commit()

    r = flask_client.get(
        "/api/v2/aliases?page_id=0",
        headers={"Authentication": api_key.code},
    )
    assert r.status_code == 403
