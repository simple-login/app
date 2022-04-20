from app.api.serializer import get_alias_infos_with_pagination_v3
from app.config import PAGE_LIMIT
from app.db import Session
from app.models import Alias, Mailbox, Contact
from tests.utils import create_new_user


def test_get_alias_infos_with_pagination_v3(flask_client):
    user = create_new_user()

    # user has 1 alias that's automatically created when the account is created
    alias_infos = get_alias_infos_with_pagination_v3(user)
    assert len(alias_infos) == 1
    alias_info = alias_infos[0]

    alias = Alias.filter_by(user_id=user.id).first()
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
    user = create_new_user()

    alias = Alias.filter_by(user_id=user.id).first()

    alias_infos = get_alias_infos_with_pagination_v3(user, query=alias.email)
    assert len(alias_infos) == 1

    alias_infos = get_alias_infos_with_pagination_v3(user, query="no match")
    assert len(alias_infos) == 0


def test_get_alias_infos_with_pagination_v3_query_alias_mailbox(flask_client):
    """test the query on the alias mailbox email"""
    user = create_new_user()
    alias = Alias.filter_by(user_id=user.id).first()
    alias_infos = get_alias_infos_with_pagination_v3(user, mailbox_id=alias.mailbox_id)
    assert len(alias_infos) == 1


def test_get_alias_infos_with_pagination_v3_query_alias_mailboxes(flask_client):
    """test the query on the alias additional mailboxes"""
    user = create_new_user()
    alias = Alias.filter_by(user_id=user.id).first()
    mb = Mailbox.create(user_id=user.id, email="mb@gmail.com")
    alias._mailboxes.append(mb)
    Session.commit()

    alias_infos = get_alias_infos_with_pagination_v3(user, mailbox_id=mb.id)
    assert len(alias_infos) == 1

    alias_infos = get_alias_infos_with_pagination_v3(user, query=alias.email)
    assert len(alias_infos) == 1


def test_get_alias_infos_with_pagination_v3_query_alias_note(flask_client):
    """test the query on the alias note"""
    user = create_new_user()

    alias = Alias.filter_by(user_id=user.id).first()
    alias.note = "test note"
    Session.commit()

    alias_infos = get_alias_infos_with_pagination_v3(user, query="test note")
    assert len(alias_infos) == 1


def test_get_alias_infos_with_pagination_v3_query_alias_name(flask_client):
    """test the query on the alias name"""
    user = create_new_user()

    alias = Alias.filter_by(user_id=user.id).first()
    alias.name = "Test Name"
    Session.commit()

    alias_infos = get_alias_infos_with_pagination_v3(user, query="test name")
    assert len(alias_infos) == 1


def test_get_alias_infos_with_pagination_v3_no_duplicate(flask_client):
    """When an alias belongs to multiple mailboxes, make sure get_alias_infos_with_pagination_v3
    returns no duplicates
    """
    user = create_new_user()

    alias = Alias.first()
    mb = Mailbox.create(user_id=user.id, email="mb@gmail.com")
    alias._mailboxes.append(mb)
    Session.commit()

    alias_infos = get_alias_infos_with_pagination_v3(user)
    assert len(alias_infos) == 1


def test_get_alias_infos_with_pagination_v3_no_duplicate_when_empty_contact(
    flask_client,
):
    """
    Make sure an alias is returned once when it has 2 contacts that have no email log activity
    """
    user = create_new_user()
    alias = Alias.first()

    Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email="contact@example.com",
        reply_email="rep@sl.local",
    )

    Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email="contact2@example.com",
        reply_email="rep2@sl.local",
    )

    alias_infos = get_alias_infos_with_pagination_v3(user)
    assert len(alias_infos) == 1


def test_get_alias_infos_pinned_alias(flask_client):
    """Different scenarios with pinned alias"""
    user = create_new_user()

    # to have 3 pages: 2*PAGE_LIMIT + the alias automatically created for a new account
    for _ in range(2 * PAGE_LIMIT):
        Alias.create_new_random(user)

    first_alias = Alias.filter_by(user_id=user.id).order_by(Alias.id).first()

    # should return PAGE_LIMIT alias
    alias_infos = get_alias_infos_with_pagination_v3(user)
    assert len(alias_infos) == PAGE_LIMIT
    # make sure first_alias is not returned as the default order is alias creation date
    assert first_alias not in [ai.alias for ai in alias_infos]

    # pin the first alias
    first_alias.pinned = True
    Session.commit()

    alias_infos = get_alias_infos_with_pagination_v3(user)
    # now first_alias is the first result
    assert first_alias == alias_infos[0].alias
    # and the page size is still the same
    assert len(alias_infos) == PAGE_LIMIT

    # pinned alias isn't included in the search
    alias_infos = get_alias_infos_with_pagination_v3(user, query="no match")
    assert len(alias_infos) == 0
