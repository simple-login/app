from enum import Enum

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

    UserMarkedForDeletion = "user_marked_for_deletion"
    DeleteUser = "delete_user"


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
