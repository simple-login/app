import arrow
import newrelic.agent

from app import config, rate_limiter
from app.alias_audit_log_utils import emit_alias_audit_log, AliasAuditLogAction
from app.config import ALIAS_TRASH_DAYS
from app.db import Session
from app.errors import CannotCreateAliasQuotaExceeded
from app.events.event_dispatcher import EventDispatcher
from app.events.generated.event_pb2 import EventContent, AliasDeleted, AliasCreated
from app.log import LOG
from app.models import (
    Alias,
    User,
    AliasDeleteReason,
    DomainDeletedAlias,
    DeletedAlias,
    UserAliasDeleteAction,
)


def __delete_alias(alias: Alias, user: User, commit: bool):
    alias_id = alias.id
    alias_email = alias.email

    LOG.info(f"Performing alias deletion for {alias} of user {user}")
    emit_alias_audit_log(
        alias, AliasAuditLogAction.DeleteAlias, "Alias deleted by user action"
    )
    Alias.filter(Alias.id == alias.id).delete()

    EventDispatcher.send_event(
        user,
        EventContent(alias_deleted=AliasDeleted(id=alias_id, email=alias_email)),
    )
    if commit:
        Session.commit()


def __delete_if_custom_domain(
    alias: Alias, user: User, reason: AliasDeleteReason, commit: bool
) -> bool:
    if not alias.custom_domain_id:
        return False

    if not DomainDeletedAlias.get_by(
        email=alias.email, domain_id=alias.custom_domain_id
    ):
        domain_deleted_alias = DomainDeletedAlias(
            user_id=user.id,
            email=alias.email,
            domain_id=alias.custom_domain_id,
            reason=reason,
            alias_id=alias.id,
        )
        Session.add(domain_deleted_alias)
        LOG.i(
            f"Moving {alias} to domain {alias.custom_domain_id} trash {domain_deleted_alias}"
        )

    __delete_alias(alias, user, commit)
    return True


def delete_alias(
    alias: Alias,
    user: User,
    reason: AliasDeleteReason = AliasDeleteReason.Unspecified,
    commit: bool = False,
):
    """
    Determine if the alias is meant to be sent to the user trash or to the global trash, depending on:
    - alias.delete_on
    - user.alias_delete_action
    Should be used instead of Alias.delete, DomainDeletedAlias.create, DeletedAlias.create
    """
    # Determine if the alias should be deleted or moved to trash
    if (
        alias.delete_on is not None
        or user.alias_delete_action == UserAliasDeleteAction.DeleteImmediately
    ):
        # Perform alias deletion
        perform_alias_deletion(alias, user, reason, commit)
    else:
        # Move alias to trash
        move_alias_to_trash(alias, user, reason, commit)


def perform_alias_deletion(
    alias: Alias,
    user: User,
    reason: AliasDeleteReason = AliasDeleteReason.Unspecified,
    commit: bool = False,
):
    if __delete_if_custom_domain(alias, user, reason, commit):
        LOG.info(
            f"Moved alias {alias.id} ({alias.email}) of custom domain {alias.custom_domain_id} to custom domain trash"
        )
        return

    if not DeletedAlias.get_by(email=alias.email):
        deleted_alias = DeletedAlias(
            email=alias.email, reason=alias.delete_reason or reason, alias_id=alias.id
        )
        Session.add(deleted_alias)
        LOG.i(f"Moving {alias} to global trash {deleted_alias}")

    __delete_alias(alias, user, commit)


def move_alias_to_trash(
    alias: Alias,
    user: User,
    reason: AliasDeleteReason = AliasDeleteReason.Unspecified,
    commit: bool = False,
):
    if __delete_if_custom_domain(alias, user, reason, commit):
        LOG.info(
            f"Moved alias {alias.id} ({alias.email}) of custom domain {alias.custom_domain_id} to custom domain trash"
        )
        return

    alias.delete_on = arrow.now().shift(days=+ALIAS_TRASH_DAYS)
    alias.delete_reason = reason
    alias.enabled = False

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


def __perform_alias_restore(user: User, alias: Alias) -> None:
    LOG.i(f"User {user} is restoring {alias}")
    if alias.delete_on is None:
        LOG.i(f"Alias {alias} is not trashed")
        return
    alias.delete_on = None
    alias.delete_reason = None
    alias.enabled = True
    emit_alias_audit_log(
        alias=alias,
        action=AliasAuditLogAction.RestoreAlias,
        message=f"Restored alias {alias.id} from trash",
        user_id=alias.user_id,
    )
    EventDispatcher.send_event(
        user,
        EventContent(
            alias_created=AliasCreated(
                id=alias.id,
                email=alias.email,
                note=alias.note,
                enabled=alias.enabled,
                created_at=int(alias.created_at.timestamp),
            )
        ),
    )
    Session.commit()


def check_user_can_restore_num_aliases(user: User, num_aliases_to_restore: int):
    if not user.can_create_num_aliases(num_aliases_to_restore):
        raise CannotCreateAliasQuotaExceeded()


def restore_alias(user: User, alias_id: int) -> None | Alias:
    LOG.i(f"Try to restore alias {alias_id} by {user.id}")
    limits = config.ALIAS_RESTORE_ONE_RATE_LIMIT
    for limit in limits:
        key = f"alias_restore_all_{limit[1]}:{user.id}"
        rate_limiter.check_bucket_limit(key, limit[0], limit[1])
    alias = Alias.get_by(id=alias_id, user_id=user.id)
    if alias is None:
        return None

    check_user_can_restore_num_aliases(user, 1)
    __perform_alias_restore(user, alias)
    newrelic.agent.record_custom_event("RestoreAlias", {"mode": "single"})
    newrelic.agent.record_custom_metric("AliasRestored", 1)
    return alias


def restore_all_alias(user: User) -> int:
    LOG.i(f"Try to restore all alias by {user.id}")
    limits = config.ALIAS_RESTORE_ALL_RATE_LIMIT
    for limit in limits:
        key = f"alias_restore_all_{limit[1]}:{user.id}"
        rate_limiter.check_bucket_limit(key, limit[0], limit[1])

    filters = [Alias.user_id == user.id, Alias.delete_on != None]  # noqa: E711

    trashed_aliases_count = Session.query(Alias).filter(*filters).count()
    check_user_can_restore_num_aliases(user, trashed_aliases_count)

    query = Session.query(Alias).filter(*filters).enable_eagerloads(False).yield_per(50)
    count = 0
    for alias in query.all():
        __perform_alias_restore(user, alias)
        count += 1
    newrelic.agent.record_custom_event("RestoreAlias", {"mode": "bulk"})
    newrelic.agent.record_custom_metric("AliasRestored", count)
    LOG.i(f"Untrashed {count} alias by user {user}")
    return count


def clear_trash(user: User) -> int:
    LOG.i(f"Clear alias trash by {user}")
    alias_query = (
        Session.query(Alias)
        .filter(Alias.user_id == user.id, Alias.delete_on != None)  # noqa: E711
        .enable_eagerloads(False)
        .yield_per(50)
    )
    count = 0
    for alias in alias_query.all():
        count = count + 1
        delete_alias(alias, user, reason=alias.delete_reason, commit=False)
    newrelic.agent.record_custom_event("ClearAliasTrash", {})
    Session.commit()
    return count
