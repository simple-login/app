import arrow
from sqlalchemy.sql import text

from app.db import Session
from app.log import LOG


def cleanup_expired_oauth_tokens(oldest_allowed: arrow.Arrow):
    LOG.i(f"Deleting oauth_token entries with expired older than {oldest_allowed}")
    sql = text(
        "DELETE FROM oauth_token WHERE expired IS NOT NULL AND expired < :expire_time"
    )
    res = Session.execute(sql, {"expire_time": oldest_allowed.datetime}).rowcount
    LOG.i(f"Deleted {res} expired oauth_token entries")
    Session.commit()
