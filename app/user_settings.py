import uuid
from typing import Optional

from flask import session as flask_session

from app.db import Session
from app.log import LOG
from app.models import User, SLDomain, CustomDomain, Mailbox
from app.user_audit_log_utils import emit_user_audit_log, UserAuditLogAction


class CannotSetAlias(Exception):
    def __init__(self, msg: str):
        self.msg = msg


class CannotSetMailbox(Exception):
    def __init__(self, msg: str):
        self.msg = msg


def set_default_alias_domain(user: User, domain_name: Optional[str]):
    if not domain_name:
        LOG.i(f"User {user} has set no domain as default domain")
        user.default_alias_public_domain_id = None
        user.default_alias_custom_domain_id = None
        Session.flush()
        return

    sl_domain: SLDomain = SLDomain.get_by(domain=domain_name)
    if sl_domain:
        if sl_domain.hidden:
            LOG.i(f"User {user} has tried to set up a hidden domain as default domain")
            raise CannotSetAlias("Domain does not exist")
        if sl_domain.premium_only and not user.is_premium():
            LOG.i(f"User {user} has tried to set up a premium domain as default domain")
            raise CannotSetAlias("You cannot use this domain")
        LOG.i(f"User {user} has set public {sl_domain} as default domain")
        user.default_alias_public_domain_id = sl_domain.id
        user.default_alias_custom_domain_id = None
        Session.flush()
        return
    custom_domain = CustomDomain.get_by(domain=domain_name)
    if not custom_domain:
        LOG.i(
            f"User {user} has tried to set up an non existing domain as default domain"
        )
        raise CannotSetAlias("Domain does not exist or it hasn't been verified")
    if custom_domain.user_id != user.id or not custom_domain.verified:
        LOG.i(
            f"User {user} has tried to set domain {custom_domain} as default domain that does not belong to the user or that is not verified"
        )
        raise CannotSetAlias("Domain does not exist or it hasn't been verified")
    LOG.i(f"User {user} has set custom {custom_domain} as default domain")
    user.default_alias_public_domain_id = None
    user.default_alias_custom_domain_id = custom_domain.id
    Session.flush()


def set_default_mailbox(user: User, mailbox_id: int) -> Mailbox:
    mailbox: Optional[Mailbox] = Mailbox.get(mailbox_id)

    if not mailbox or mailbox.user_id != user.id:
        raise CannotSetMailbox("Invalid mailbox")

    if not mailbox.verified:
        raise CannotSetMailbox("This is mailbox is not verified")

    if mailbox.id == user.default_mailbox_id:
        return mailbox
    LOG.i(f"User {user} has set mailbox {mailbox} as his default one")

    user.default_mailbox_id = mailbox.id
    emit_user_audit_log(
        user=user,
        action=UserAuditLogAction.UpdateMailbox,
        message=f"Set mailbox {mailbox.id} ({mailbox.email}) as default",
    )

    Session.commit()
    return mailbox


def regenerate_user_alternative_id(user: User, update_session: bool = True):
    """
    Regenerate the user's alternative_id to log them out on other browsers/sessions.
    Optionally updates the current flask session with the new alternative_id.
    """
    user.alternative_id = str(uuid.uuid4())
    Session.flush()

    if update_session:
        flask_session["_user_id"] = user.alternative_id
