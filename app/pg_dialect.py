"""PostgreSQL + psycopg 3 dialect behaving like psycopg2 did.

Connections use psycopg's ClientCursor: parameters are bound client side and
queries are sent with the simple query protocol, as psycopg2 did. With the
default server-side binding, queries use the extended protocol, which changes
how connection poolers (e.g. in transaction mode) see the traffic. Statements
are never prepared server side either (prepare_threshold=None).

SQLAlchemy's psycopg dialect renders an explicit cast on string and integer bound
parameters (e.g. ``id = %(id)s::VARCHAR``), which psycopg2 never did. With
those casts, values that used to work now fail at the database:

- comparing an integer column with a string (e.g. an id coming from
  ``request.form``): ``operator does not exist: integer = character varying``
- comparing an integer column with an out-of-range number (e.g. an id parsed
  from a VERP address): ``integer out of range`` instead of no match

This dialect drops the casts on integer parameters (psycopg 3 sizes ints by
value), and sends a string compared with an integer column as an integer
parameter, so Postgres resolves them as it did with psycopg2.

Registered as ``postgresql+slpsycopg``; see ``config.DB_URI``.
"""

from typing import Optional

from psycopg import ClientCursor
from sqlalchemy import BigInteger, Integer, SmallInteger, String
from sqlalchemy.dialects import registry
from sqlalchemy.dialects.postgresql.psycopg import (
    PGCompiler_psycopg,
    PGDialect_psycopg,
)
from sqlalchemy.sql.elements import BindParameter

DIALECT_NAME = "slpsycopg"


def _as_compared_type(element, other):
    """A str bind compared with an integer expression gets the integer's type,
    so it is not sent as VARCHAR (psycopg2 sent it as an untyped literal)."""
    if (
        isinstance(element, BindParameter)
        and element.type._type_affinity is String
        and other.type._type_affinity is Integer
    ):
        return element._with_binary_element_type(other.type)
    return element


class SLPGCompiler_psycopg(PGCompiler_psycopg):
    def visit_binary(self, binary, **kw):
        left = _as_compared_type(binary.left, binary.right)
        right = _as_compared_type(binary.right, binary.left)
        if left is not binary.left or right is not binary.right:
            binary = binary._clone()
            binary.left = left
            binary.right = right
        return super().visit_binary(binary, **kw)


class SLPGDialect_psycopg(PGDialect_psycopg):
    # Compilation is deterministic for a given statement structure (the retyping
    # in SLPGCompiler_psycopg only depends on types), so caching stays valid.
    supports_statement_cache = True
    statement_compiler = SLPGCompiler_psycopg
    # The psycopg dialect maps integer types to subclasses whose only difference
    # is render_bind_cast = True: map them back to the plain types. Integers are
    # typed by psycopg from their value anyway. String casts are kept: SQLAlchemy
    # relies on them (e.g. arguments of json_build_object in reflection queries).
    colspecs = {
        **PGDialect_psycopg.colspecs,
        Integer: Integer,
        SmallInteger: SmallInteger,
        BigInteger: BigInteger,
    }

    def create_connect_args(self, url):
        args, kwargs = super().create_connect_args(url)
        # psycopg2 behaviour: client-side binding with the simple query protocol
        kwargs.setdefault("cursor_factory", ClientCursor)
        # psycopg2 never prepared statements server side; they also break
        # poolers in transaction mode
        kwargs.setdefault("prepare_threshold", None)
        return args, kwargs


def register():
    registry.register(
        f"postgresql.{DIALECT_NAME}", "app.pg_dialect", "SLPGDialect_psycopg"
    )


_POSTGRES_SCHEMES = ("postgresql", "postgres")


def _split_postgres_uri(uri: str) -> Optional[str]:
    """Return what follows "scheme://" for a PostgreSQL URI, with or without a
    driver (postgresql://, postgres://, postgresql+psycopg2://, ...), else None.
    """
    scheme, sep, rest = uri.partition("://")
    if not sep:
        return None
    if scheme.split("+", 1)[0].lower() not in _POSTGRES_SCHEMES:
        return None
    return rest


def sqlalchemy_uri(uri: str) -> str:
    """SQLAlchemy URL using this dialect, whatever driver the URI names (the
    historical postgresql:// or postgresql+psycopg2:// keep working)."""
    rest = _split_postgres_uri(uri)
    if rest is None:
        return uri
    register()
    return f"postgresql+{DIALECT_NAME}://{rest}"


def libpq_uri(uri: str) -> str:
    """Plain libpq URI (no "+driver"), as accepted by psycopg.connect()."""
    rest = _split_postgres_uri(uri)
    if rest is None:
        return uri
    return f"postgresql://{rest}"
