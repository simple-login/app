import arrow

from app.alias_utils import try_auto_create
from app.config import (
    MAX_ACTIVITY_DURING_MINUTE_PER_ALIAS,
    MAX_ACTIVITY_DURING_MINUTE_PER_MAILBOX,
)
from app.email_utils import is_reply_email
from app.extensions import db
from app.log import LOG
from app.models import Alias, EmailLog, Contact


def greylisting_needed_for_alias(alias: Alias) -> bool:
    min_time = arrow.now().shift(minutes=-1)

    # get the nb of activity on this alias
    nb_activity = (
        db.session.query(EmailLog)
        .join(Contact, EmailLog.contact_id == Contact.id)
        .filter(
            Contact.alias_id == alias.id,
            EmailLog.created_at > min_time,
        )
        .group_by(EmailLog.id)
        .count()
    )

    if nb_activity > MAX_ACTIVITY_DURING_MINUTE_PER_ALIAS:
        LOG.d(
            "Too much forward on alias %s. Nb Activity %s",
            alias,
            nb_activity,
        )
        return True

    return False


def greylisting_needed_for_mailbox(alias: Alias) -> bool:
    min_time = arrow.now().shift(minutes=-1)

    # get nb of activity on this mailbox
    nb_activity = (
        db.session.query(EmailLog)
        .join(Contact, EmailLog.contact_id == Contact.id)
        .join(Alias, Contact.alias_id == Alias.id)
        .filter(
            Alias.mailbox_id == alias.mailbox_id,
            EmailLog.created_at > min_time,
        )
        .group_by(EmailLog.id)
        .count()
    )

    if nb_activity > MAX_ACTIVITY_DURING_MINUTE_PER_MAILBOX:
        LOG.d(
            "Too much forward on mailbox %s, alias %s. Nb Activity %s",
            alias.mailbox,
            alias,
            nb_activity,
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
        if is_reply_email(rcpt_to):
            if greylisting_needed_reply_phase(rcpt_to):
                return True
        else:
            # Forward phase
            address = rcpt_to  # alias@SL
            if greylisting_needed_forward_phase(address):
                return True

    return False
