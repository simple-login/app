"""The DB dialect must keep psycopg2's parameter typing (see app/pg_dialect.py)."""

from psycopg import ClientCursor
from sqlalchemy import select, text
from sqlalchemy.engine.default import CACHE_HIT

from app.db import Session, engine
from app.models import EmailLog, User
from app.pg_dialect import SLPGDialect_psycopg
from tests.utils import create_new_user


def test_engine_uses_psycopg3_dialect():
    assert isinstance(engine.dialect, SLPGDialect_psycopg)
    assert engine.dialect.driver == "psycopg"
    assert engine.dialect.supports_statement_cache


def test_connection_is_psycopg2_compatible(flask_client):
    dbapi_conn = Session.connection().connection.dbapi_connection
    # client-side binding, simple query protocol
    assert dbapi_conn.cursor_factory is ClientCursor
    assert dbapi_conn.prepare_threshold is None


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
    # The compiled statement is cached: the cache must be hit, and each
    # execution must still use its own values
    u1, u2 = create_new_user(), create_new_user()
    for stmt in (
        lambda u: select(User.id).where(User.id == str(u.id)),
        lambda u: select(User.id).where(User.id.in_([str(u.id)])),
        lambda u: select(User.id).where(User.id == u.id),
    ):
        hits = []
        for _ in range(3):
            for u in (u1, u2):
                result = Session.connection().execute(stmt(u))
                hits.append(result.context.cache_hit == CACHE_HIT)
                assert result.scalars().all() == [u.id]
        assert hits[1:] == [True] * (len(hits) - 1)


def test_untyped_text_parameters(flask_client):
    assert Session.execute(text("SELECT '%' || :p"), {"p": "x"}).scalar() == "%x"
    assert Session.execute(text("SELECT :p"), {"p": "x"}).scalar() == "x"
