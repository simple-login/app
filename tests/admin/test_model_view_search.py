"""Tests for the numeric-aware search of the admin model views."""

from app.admin.alias import AliasAdmin
from app.admin.email_log import EmailLogAdmin
from app.admin.user import UserAdmin
from app.db import Session
from app.models import Alias, EmailLog, User
from tests.utils import create_new_user, random_token


def _search_sql(view_cls, model, term: str) -> str:
    view = view_cls(model, Session)
    query, count_query, _, _ = view._apply_search(
        Session.query(model), Session.query(model), {}, {}, term
    )
    return str(query)


def test_numeric_search_looks_up_the_id_directly():
    sql = _search_sql(UserAdmin, User, "12345")
    assert "users.id = " in sql
    # no full table scan on the text columns
    assert "ILIKE" not in sql.upper()


def test_non_numeric_search_only_hits_the_text_columns():
    sql = _search_sql(UserAdmin, User, "bob@example.com")
    assert "CAST(users.email AS VARCHAR) ILIKE" in sql
    assert "users.id = " not in sql


def test_numeric_search_on_joined_id_looks_up_the_id_directly():
    sql = _search_sql(AliasAdmin, Alias, "12345")
    assert "alias.id = " in sql
    assert "ILIKE" not in sql.upper()


def test_exact_match_prefix_still_looks_up_the_id_directly():
    sql = _search_sql(UserAdmin, User, "=12345")
    assert "users.id = " in sql
    assert "ILIKE" not in sql.upper()


def test_search_terms_that_are_not_plain_integers_keep_the_text_search():
    # flask-admin's `^` (starts with) prefix, negative numbers and separators
    # are not plain integers
    for term in ("^12345", "-12345", "1_2345"):
        sql = _search_sql(UserAdmin, User, term)
        assert "CAST(users.email AS VARCHAR) ILIKE" in sql, term
        assert "users.id = " not in sql, term


def test_non_numeric_term_on_an_id_only_view_matches_nothing():
    """A non-numeric term must not be silently dropped, which would list the
    whole table. EmailLogAdmin only has an integer searchable column."""
    sql = _search_sql(EmailLogAdmin, EmailLog, "foo@example.com")
    assert "WHERE" in sql
    view = EmailLogAdmin(EmailLog, Session)
    query, count_query, _, _ = view._apply_search(
        Session.query(EmailLog), Session.query(EmailLog), {}, {}, "foo@example.com"
    )
    assert query.all() == []
    assert count_query.count() == 0


def test_search_ignores_out_of_range_numbers():
    sql = _search_sql(UserAdmin, User, str(2**64))
    assert "users.id = " not in sql


def test_numeric_search_finds_the_user(flask_client):
    user = create_new_user(email=f"search_{random_token(8)}@example.com")
    Session.commit()

    view = UserAdmin(User, Session)
    query, count_query, _, _ = view._apply_search(
        Session.query(User), Session.query(User), {}, {}, str(user.id)
    )
    assert [found.id for found in query.all()] == [user.id]
    assert count_query.count() == 1


def test_numeric_search_does_not_match_ids_by_substring(flask_client):
    user = create_new_user(email=f"substring_{random_token(8)}@example.com")
    Session.commit()

    view = UserAdmin(User, Session)
    query, _, _, _ = view._apply_search(
        Session.query(User), Session.query(User), {}, {}, str(user.id * 10)
    )
    assert user.id not in [found.id for found in query.all()]
