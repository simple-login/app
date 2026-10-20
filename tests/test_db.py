from sqlalchemy import text
from sqlalchemy.orm import scoped_session, sessionmaker

from app.db import engine


def test_session_recovers_after_interrupted_invalidation():
    # Reproduce the state left when a disconnect's invalidation is interrupted:
    # the pool has dropped the DBAPI connection but the Connection still holds it.
    # A Session bound to one shared Connection then fails every later query with
    # "'NoneType' object has no attribute 'cursor'"; an engine-bound one recovers.
    session = scoped_session(sessionmaker(bind=engine))
    try:
        fairy = session.connection().connection
        engine.pool._invalidate(fairy)
        session.close()

        assert session.execute(text("SELECT 1")).scalar() == 1
    finally:
        session.remove()
