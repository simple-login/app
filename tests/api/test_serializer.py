from flask import url_for

from app.api.serializer import get_alias_infos_with_pagination_v3
from app.config import PAGE_LIMIT
from app.extensions import db
from app.models import User, ApiKey, Alias, Contact, EmailLog, Mailbox


def test_get_alias_infos_with_pagination_v3(flask_client):
    user = User.create(
        email="a@b.c",
        password="password",
        name="Test User",
        activated=True,
        commit=True,
    )

    # user has 1 alias that's automatically created when the account is created
    alias_infos = get_alias_infos_with_pagination_v3(user)
    assert len(alias_infos) == 1
    alias_info = alias_infos[0]

    alias = Alias.query.first()
    assert alias_info.alias == alias
    assert alias_info.mailbox == user.default_mailbox
    assert alias_info.mailboxes == [user.default_mailbox]
    assert alias_info.nb_forward == 0
    assert alias_info.nb_blocked == 0
    assert alias_info.nb_reply == 0
    assert alias_info.latest_email_log is None
    assert alias_info.latest_contact is None


def test_get_alias_infos_with_pagination_v3_query_alias_email(flask_client):
    """test the query on the alias email"""
    user = User.create(
        email="a@b.c",
        password="password",
        name="Test User",
        activated=True,
        commit=True,
    )

    alias = Alias.query.first()

    alias_infos = get_alias_infos_with_pagination_v3(user, query=alias.email)
    assert len(alias_infos) == 1

    alias_infos = get_alias_infos_with_pagination_v3(user, query="no match")
    assert len(alias_infos) == 0


def test_get_alias_infos_with_pagination_v3_query_alias_mailbox(flask_client):
    """test the query on the alias mailbox email"""
    user = User.create(
        email="a@b.c",
        password="password",
        name="Test User",
        activated=True,
        commit=True,
    )
    alias = Alias.query.first()
    alias_infos = get_alias_infos_with_pagination_v3(user, query=alias.mailbox.email)
    assert len(alias_infos) == 1


def test_get_alias_infos_with_pagination_v3_query_alias_mailboxes(flask_client):
    """test the query on the alias additional mailboxes"""
    user = User.create(
        email="a@b.c",
        password="password",
        name="Test User",
        activated=True,
        commit=True,
    )
    alias = Alias.query.first()
    mb = Mailbox.create(user_id=user.id, email="mb@gmail.com")
    alias._mailboxes.append(mb)
    db.session.commit()

    alias_infos = get_alias_infos_with_pagination_v3(user, query=mb.email)
    assert len(alias_infos) == 1

    alias_infos = get_alias_infos_with_pagination_v3(user, query=alias.email)
    assert len(alias_infos) == 1


def test_get_alias_infos_with_pagination_v3_query_alias_note(flask_client):
    """test the query on the alias note"""
    user = User.create(
        email="a@b.c",
        password="password",
        name="Test User",
        activated=True,
        commit=True,
    )

    alias = Alias.query.first()
    alias.note = "test note"
    db.session.commit()

    alias_infos = get_alias_infos_with_pagination_v3(user, query="test note")
    assert len(alias_infos) == 1


def test_get_alias_infos_with_pagination_v3_query_alias_name(flask_client):
    """test the query on the alias name"""
    user = User.create(
        email="a@b.c",
        password="password",
        name="Test User",
        activated=True,
        commit=True,
    )

    alias = Alias.query.first()
    alias.name = "Test Name"
    db.session.commit()

    alias_infos = get_alias_infos_with_pagination_v3(user, query="test name")
    assert len(alias_infos) == 1


def test_get_alias_infos_with_pagination_v3_no_duplicate(flask_client):
    """When an alias belongs to multiple mailboxes, make sure get_alias_infos_with_pagination_v3
    returns no duplicates
    """
    user = User.create(
        email="a@b.c",
        password="password",
        name="Test User",
        activated=True,
        commit=True,
    )

    alias = Alias.query.first()
    mb = Mailbox.create(user_id=user.id, email="mb@gmail.com")
    alias._mailboxes.append(mb)
    db.session.commit()

    alias_infos = get_alias_infos_with_pagination_v3(user)
    assert len(alias_infos) == 1
