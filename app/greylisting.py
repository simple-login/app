import arrow

from app.alias_utils import try_auto_create
from app.config import (
    MIN_TIME_BETWEEN_ACTIVITY_PER_ALIAS,
    MIN_TIME_BETWEEN_ACTIVITY_PER_MAILBOX,
)
from app.extensions import db
from app.log import LOG
from app.models import Alias, EmailLog, Contact


def greylisting_needed_for_alias(alias: Alias) -> bool:
    # get the latest email activity on this alias
    r = (
        db.session.query(EmailLog, Contact)
        .filter(EmailLog.contact_id == Contact.id, Contact.alias_id == alias.id)
        .order_by(EmailLog.id.desc())
        .first()
    )

    if r:
        email_log, _ = r
        now = arrow.now()
        if (now - email_log.created_at).seconds < MIN_TIME_BETWEEN_ACTIVITY_PER_ALIAS:
            LOG.d(
                "Too much forward on alias %s. Latest email log %s", alias, email_log,
            )
            return True

    return False


def greylisting_needed_for_mailbox(alias: Alias) -> bool:
    # get the latest email activity on this mailbox
    r = (
        db.session.query(EmailLog, Contact, Alias)
        .filter(
            EmailLog.contact_id == Contact.id,
            Contact.alias_id == Alias.id,
            Alias.mailbox_id == alias.mailbox_id,
        )
        .order_by(EmailLog.id.desc())
        .first()
    )

    if r:
        email_log, _, _ = r
        now = arrow.now()
        if (now - email_log.created_at).seconds < MIN_TIME_BETWEEN_ACTIVITY_PER_MAILBOX:
            LOG.d(
                "Too much forward on mailbox %s. Latest email log %s. Alias %s",
                alias.mailbox,
                email_log,
                alias,
            )
            return True

    return False


def greylisting_needed_forward_phase(alias_address: str) -> bool:
    alias = Alias.get_by(email=alias_address)

    if alias:
        return greylisting_needed_for_alias(alias) or greylisting_needed_for_mailbox(
            alias
        )

    else:
        LOG.d(
            "alias %s not exist. Try to see if it can be created on the fly",
            alias_address,
        )
        alias = try_auto_create(alias_address)
        if alias:
            return greylisting_needed_for_mailbox(alias)

    return False


def greylisting_needed_reply_phase(reply_email: str) -> bool:
    contact = Contact.get_by(reply_email=reply_email)
    if not contact:
        return False

    alias = contact.alias
    return greylisting_needed_for_alias(alias) or greylisting_needed_for_mailbox(alias)


def greylisting_needed(mail_from: str, rcpt_tos: [str]) -> bool:
    for rcpt_to in rcpt_tos:
        if rcpt_to.startswith("reply+") or rcpt_to.startswith("ra+"):
            reply_email = rcpt_to.lower()
            if greylisting_needed_reply_phase(reply_email):
                return True
        else:
            # Forward phase
            address = rcpt_to.lower()  # alias@SL
            if greylisting_needed_forward_phase(address):
                return True

    return False
