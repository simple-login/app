from enum import Enum

import arrow

from app.models import User, UserAuditLog


class UserAuditLogAction(Enum):
    CreateUser = "create_user"
    ActivateUser = "activate_user"
    ResetPassword = "reset_password"

    Upgrade = "upgrade"
    SubscriptionExtended = "subscription_extended"
    SubscriptionCancelled = "subscription_cancelled"
    LinkAccount = "link_account"
    UnlinkAccount = "unlink_account"

    CreateMailbox = "create_mailbox"
    VerifyMailbox = "verify_mailbox"
    UpdateMailbox = "update_mailbox"
    DeleteMailbox = "delete_mailbox"
    MailboxDisablePgp = "mailbox_disable_pgp"

    CreateCustomDomain = "create_custom_domain"
    VerifyCustomDomain = "verify_custom_domain"
    UpdateCustomDomain = "update_custom_domain"
    DeleteCustomDomain = "delete_custom_domain"

    CreateDirectory = "create_directory"
    UpdateDirectory = "update_directory"
    DeleteDirectory = "delete_directory"

    AddSenderBlacklist = "add_sender_blacklist"
    DeleteSenderBlacklist = "delete_sender_blacklist"
    
    CreateAlias = "create_alias"
    UpdateAlias = "update_alias"
    DeleteAlias = "delete_alias"

    UserMarkedForDeletion = "user_marked_for_deletion"
    DeleteUser = "delete_user"

    LoginBlocked = "login_blocked"


USER_REQUESTED_DELETION_REASON = "Account deletion requested by the user"


def emit_user_audit_log(
    user: User, action: UserAuditLogAction, message: str, commit: bool = False
):
    UserAuditLog.create(
        user_id=user.id,
        user_email=user.email,
        action=action.value,
        message=message,
        commit=commit,
    )


def emit_user_marked_for_deletion_audit_log(user: User, source: str, reason: str):
    emit_user_audit_log(
        user=user,
        action=UserAuditLogAction.UserMarkedForDeletion,
        message=f"User {user.id} ({user.email}) marked for deletion. Source: {source}. Reason: {reason}",
    )


def emit_user_deleted_audit_log(user: User, deleted_by: str, reason: str):
    emit_user_audit_log(
        user=user,
        action=UserAuditLogAction.DeleteUser,
        message=f"User {user.id} ({user.email}) deleted. Deleted by: {deleted_by}. Reason: {reason}",
    )


LOGIN_BLOCKED_THROTTLE_HOURS = 24


def emit_login_blocked_audit_log(user: User, reason: str, source: str):
    """Records a blocked login attempt, at most once per day for the same user, reason and source"""
    message = f"Login blocked: {reason}. Source: {source}"
    already_recorded = (
        UserAuditLog.filter(
            UserAuditLog.user_id == user.id,
            UserAuditLog.action == UserAuditLogAction.LoginBlocked.value,
            UserAuditLog.message == message,
            UserAuditLog.created_at
            > arrow.utcnow().shift(hours=-LOGIN_BLOCKED_THROTTLE_HOURS),
        ).first()
        is not None
    )
    if already_recorded:
        return
    emit_user_audit_log(
        user=user,
        action=UserAuditLogAction.LoginBlocked,
        message=message,
        commit=True,
    )
