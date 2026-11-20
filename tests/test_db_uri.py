"""DB_URI keeps accepting the historical formats (see app/pg_dialect.py)."""

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict
from sqlalchemy import create_engine, make_url, text

from app import config
from app.pg_dialect import SLPGDialect_psycopg, libpq_uri, sqlalchemy_uri

# (DB_URI, expected libpq URI)
URIS = [
    # documented format
    (
        "postgresql://user:password@host:5432/dbname",
        "postgresql://user:password@host:5432/dbname",
    ),
    (
        "postgres://user:password@host:5432/dbname",
        "postgresql://user:password@host:5432/dbname",
    ),
    # explicit drivers, including the previous one
    (
        "postgresql+psycopg2://user:password@host:5432/dbname",
        "postgresql://user:password@host:5432/dbname",
    ),
    (
        "postgresql+psycopg://user:password@host:5432/dbname",
        "postgresql://user:password@host:5432/dbname",
    ),
    (
        "PostgreSQL://user:password@host:5432/dbname",
        "postgresql://user:password@host:5432/dbname",
    ),
    # no port, no password
    ("postgresql://user@host/dbname", "postgresql://user@host/dbname"),
    # url-encoded password, query parameters
    (
        "postgresql://user:p%40ss%3Aw%2Frd@host:5432/dbname?sslmode=require&connect_timeout=5",
        "postgresql://user:p%40ss%3Aw%2Frd@host:5432/dbname?sslmode=require&connect_timeout=5",
    ),
    # unix socket
    (
        "postgresql://user:password@/dbname?host=/var/run/postgresql",
        "postgresql://user:password@/dbname?host=/var/run/postgresql",
    ),
    # IPv6 host
    (
        "postgresql://user:password@[::1]:5432/dbname",
        "postgresql://user:password@[::1]:5432/dbname",
    ),
]


@pytest.mark.parametrize("db_uri,expected_libpq", URIS)
def test_libpq_uri(db_uri, expected_libpq):
    assert libpq_uri(db_uri) == expected_libpq
    # and libpq parses it
    conninfo_to_dict(libpq_uri(db_uri))


@pytest.mark.parametrize("db_uri,expected_libpq", URIS)
def test_sqlalchemy_uri_keeps_every_component(db_uri, expected_libpq):
    url = make_url(sqlalchemy_uri(db_uri))
    expected = make_url(expected_libpq)
    assert url.drivername == "postgresql+slpsycopg"
    assert url.username == expected.username
    assert url.password == expected.password
    assert url.host == expected.host
    assert url.port == expected.port
    assert url.database == expected.database
    assert url.query == expected.query
    # resolves to our dialect (no connection made)
    assert isinstance(create_engine(url).dialect, SLPGDialect_psycopg)


def test_non_postgres_uri_is_left_alone():
    assert sqlalchemy_uri("sqlite:///tmp/db.sqlite") == "sqlite:///tmp/db.sqlite"
    assert libpq_uri("sqlite:///tmp/db.sqlite") == "sqlite:///tmp/db.sqlite"


@pytest.mark.parametrize(
    "scheme", ["postgresql", "postgres", "postgresql+psycopg2", "postgresql+psycopg"]
)
def test_connect_with_each_scheme(scheme):
    # the test DB_URI is in the historical postgresql://user:password@host:port/db format
    rest = config.RAW_DB_URI.split("://", 1)[1]
    db_uri = f"{scheme}://{rest}"

    engine = create_engine(sqlalchemy_uri(db_uri))
    try:
        with engine.connect() as conn:
            assert conn.execute(text("SELECT 1")).scalar() == 1
    finally:
        engine.dispose()

    with psycopg.connect(libpq_uri(db_uri)) as conn:
        assert conn.execute("SELECT 1").fetchone()[0] == 1
