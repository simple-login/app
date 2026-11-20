"""The DB dialect must keep psycopg2's parameter typing (see app/pg_dialect.py)."""

from sqlalchemy import text

from app.db import Session, engine
from app.models import EmailLog, User
from app.pg_dialect import SLPGDialect_psycopg
from tests.utils import create_new_user


def test_engine_uses_psycopg3_dialect():
    assert isinstance(engine.dialect, SLPGDialect_psycopg)
    assert engine.dialect.driver == "psycopg"


def test_no_cast_rendered_on_integer_binds():
    assert "::" not in str((User.id == 1).compile(dialect=engine.dialect))
    assert "::" not in str((User.id == "1").compile(dialect=engine.dialect))
    # strings compared with strings keep the cast
    assert "::VARCHAR" in str((User.email == "a").compile(dialect=engine.dialect))


def test_integer_column_compared_with_string(flask_client):
    user = create_new_user()
    assert User.filter(User.id == str(user.id)).first().id == user.id
    assert [u.id for u in User.filter(User.id.in_([str(user.id)])).all()] == [user.id]


def test_integer_column_compared_with_out_of_range_number(flask_client):
    assert EmailLog.get(99999999999999) is None
    assert EmailLog.filter(EmailLog.id == 99999999999999).first() is None


def test_cached_statement_uses_each_call_values(flask_client):
    # the compiled statement is cached: make sure values are not mixed up
    u1, u2 = create_new_user(), create_new_user()
    for _ in range(3):
        for u in (u1, u2):
            assert User.filter(User.id == str(u.id)).first().id == u.id
            assert User.filter(User.id.in_([str(u.id)])).one().id == u.id
            assert User.filter(User.id == u.id).first().id == u.id


def test_untyped_text_parameters(flask_client):
    assert Session.execute(text("SELECT '%' || :p"), {"p": "x"}).scalar() == "%x"
    assert Session.execute(text("SELECT :p"), {"p": "x"}).scalar() == "x"
