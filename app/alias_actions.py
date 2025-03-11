import arrow

from app.alias_audit_log_utils import emit_alias_audit_log, AliasAuditLogAction
from app.config import ALIAS_TRASH_DAYS
from app.db import Session
from app.events.event_dispatcher import EventDispatcher
from app.events.generated.event_pb2 import EventContent, AliasDeleted
from app.log import LOG
from app.models import Alias, User, AliasDeleteReason, DomainDeletedAlias, DeletedAlias


def perform_alias_deletion(
    alias: Alias,
    user: User,
    reason: AliasDeleteReason = AliasDeleteReason.Unspecified,
    commit: bool = False,
):
    if alias.custom_domain_id:
        if not DomainDeletedAlias.get_by(
            email=alias.email, domain_id=alias.custom_domain_id
        ):
            domain_deleted_alias = DomainDeletedAlias(
                user_id=user.id,
                email=alias.email,
                domain_id=alias.custom_domain_id,
                reason=reason,
            )
            Session.add(domain_deleted_alias)
            Session.commit()
            LOG.i(
                f"Moving {alias} to domain {alias.custom_domain_id} trash {domain_deleted_alias}"
            )
    else:
        if not DeletedAlias.get_by(email=alias.email):
            deleted_alias = DeletedAlias(
                email=alias.email, reason=alias.delete_reason or reason
            )
            Session.add(deleted_alias)
            Session.commit()
            LOG.i(f"Moving {alias} to global trash {deleted_alias}")

    alias_id = alias.id
    alias_email = alias.email

    emit_alias_audit_log(
        alias, AliasAuditLogAction.DeleteAlias, "Alias deleted by user action"
    )
    Alias.filter(Alias.id == alias.id).delete()
    Session.commit()

    EventDispatcher.send_event(
        user,
        EventContent(alias_deleted=AliasDeleted(id=alias_id, email=alias_email)),
    )
    if commit:
        Session.commit()


def move_alias_to_trash(
    alias: Alias,
    user: User,
    reason: AliasDeleteReason = AliasDeleteReason.Unspecified,
    commit: bool = False,
):
    alias.delete_on = arrow.now().shift(days=+ALIAS_TRASH_DAYS)
    alias.delete_reason = reason

    alias_id = alias.id
    alias_email = alias.email
    emit_alias_audit_log(
        alias, AliasAuditLogAction.TrashAlias, "Alias moved to trash by user action"
    )

    EventDispatcher.send_event(
        user,
        EventContent(alias_deleted=AliasDeleted(id=alias_id, email=alias_email)),
    )
    if commit:
        Session.commit()
