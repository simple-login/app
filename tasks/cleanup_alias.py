import arrow
from sqlalchemy import and_

from app.db import Session
from app.log import LOG
from app.models import Alias
from app.alias_delete import perform_alias_deletion


def cleanup_alias(oldest_allowed: arrow.Arrow):
    LOG.i(f"Deleting alias with delete_on older than {oldest_allowed}")
    for alias in (
        Alias.filter(
            and_(Alias.delete_on.isnot(None), Alias.delete_on <= oldest_allowed)
        )
        .yield_per(500)
        .all()
    ):
        alias: Alias = alias
        perform_alias_deletion(alias, alias.user, alias.delete_reason)
        Session.commit()
