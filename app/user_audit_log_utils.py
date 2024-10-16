from enum import Enum

from app.models import UserAuditLog


class UserAuditLogAction(Enum):
    Upgrade = "upgrade"
    SubscriptionExtended = "subscription_extended"
    SubscriptionCancelled = "subscription_cancelled"
    LinkAccount = "link_account"
    UnlinkAccount = "unlink_account"

    CreateMailbox = "create_mailbox"
    VerifyMailbox = "verify_mailbox"
    UpdateMailbox = "update_mailbox"
    DeleteMailbox = "delete_mailbox"

    CreateSubdomain = "create_subdomain"
    UpdateSubdomain = "update_subdomain"
    DeleteSubdomain = "delete_subdomain"

    CreateCustomDomain = "create_custom_domain"
    VerifyCustomDomain = "verify_custom_domain"
    UpdateCustomDomain = "update_custom_domain"
    DeleteCustomDomain = "delete_custom_domain"

    CreateContact = "create_contact"
    UpdateContact = "update_contact"
    DeleteContact = "delete_contact"

    CreateDirectory = "create_directory"
    UpdateDirectory = "update_directory"
    DeleteDirectory = "delete_directory"

    DeleteUser = "delete_user"


def emit_user_audit_log(
    user_id: int, action: UserAuditLogAction, message: str, commit: bool = False
):
    UserAuditLog.create(
        user_id=user_id,
        action=action.value,
        message=message,
        commit=commit,
    )
