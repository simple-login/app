"""PostgreSQL + psycopg 3 dialect keeping psycopg2's parameter typing.

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


def register():
    registry.register(
        f"postgresql.{DIALECT_NAME}", "app.pg_dialect", "SLPGDialect_psycopg"
    )
