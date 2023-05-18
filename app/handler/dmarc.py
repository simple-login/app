import uuid
from io import BytesIO
from typing import Optional, Tuple

from aiosmtpd.handlers import Message
from aiosmtpd.smtp import Envelope

from app import s3, config
from app.config import (
    DMARC_CHECK_ENABLED,
    ALERT_QUARANTINE_DMARC,
    ALERT_DMARC_FAILED_REPLY_PHASE,
)
from app.email import headers, status
from app.email_utils import (
    get_header_unicode,
    send_email_with_rate_control,
    render,
    add_or_replace_header,
    add_header,
)
from app.handler.spamd_result import SpamdResult, Phase, DmarcCheckResult
from app.log import LOG
from app.message_utils import message_to_bytes
from app.models import Alias, Contact, Notification, EmailLog, RefusedEmail


def apply_dmarc_policy_for_forward_phase(
    alias: Alias, contact: Contact, envelope: Envelope, msg: Message
) -> Tuple[Message, Optional[str]]:
    spam_result = SpamdResult.extract_from_headers(msg, Phase.forward)
    if not DMARC_CHECK_ENABLED or not spam_result:
        return msg, None

    from_header = get_header_unicode(msg[headers.FROM])

    warning_plain_text = f"""This email failed anti-phishing checks when it was received by SimpleLogin, be careful with its content.
More info on https://simplelogin.io/docs/getting-started/anti-phishing/
            """
    warning_html = f"""
        <p style="color:red">
            This email failed anti-phishing checks when it was received by SimpleLogin, be careful with its content.
            More info on <a href="https://simplelogin.io/docs/getting-started/anti-phishing/">anti-phishing measure</a>
        </p>
        """

    # do not quarantine an email if fails DMARC but has a small rspamd score
    if (
        config.MIN_RSPAMD_SCORE_FOR_FAILED_DMARC is not None
        and spam_result.rspamd_score < config.MIN_RSPAMD_SCORE_FOR_FAILED_DMARC
        and spam_result.dmarc
        in (
            DmarcCheckResult.quarantine,
            DmarcCheckResult.reject,
        )
    ):
        LOG.w(
            f"email fails DMARC but has a small rspamd score, from contact {contact.email} to alias {alias.email}."
            f"mail_from:{envelope.mail_from}, from_header: {from_header}"
        )
        changed_msg = add_header(
            msg,
            warning_plain_text,
            warning_html,
        )
        return changed_msg, None

    if spam_result.dmarc == DmarcCheckResult.soft_fail:
        LOG.w(
            f"dmarc forward: soft_fail from contact {contact.email} to alias {alias.email}."
            f"mail_from:{envelope.mail_from}, from_header: {from_header}"
        )
        changed_msg = add_header(
            msg,
            warning_plain_text,
            warning_html,
        )
        return changed_msg, None

    if spam_result.dmarc in (
        DmarcCheckResult.quarantine,
        DmarcCheckResult.reject,
    ):
        LOG.w(
            f"dmarc forward: put email from {contact} to {alias} to quarantine. {spam_result.event_data()}, "
            f"mail_from:{envelope.mail_from}, from_header: {msg[headers.FROM]}"
        )
        email_log = quarantine_dmarc_failed_forward_email(alias, contact, envelope, msg)
        Notification.create(
            user_id=alias.user_id,
            title=f"{alias.email} has a new mail in quarantine",
            message=Notification.render(
                "notification/message-quarantine.html", alias=alias
            ),
            commit=True,
        )
        user = alias.user
        send_email_with_rate_control(
            user,
            ALERT_QUARANTINE_DMARC,
            user.email,
            f"An email sent to {alias.email} has been quarantined",
            render(
                "transactional/message-quarantine-dmarc.txt.jinja2",
                from_header=from_header,
                alias=alias,
                refused_email_url=email_log.get_dashboard_url(),
            ),
            render(
                "transactional/message-quarantine-dmarc.html",
                from_header=from_header,
                alias=alias,
                refused_email_url=email_log.get_dashboard_url(),
            ),
            max_nb_alert=10,
            ignore_smtp_error=True,
        )
        return msg, status.E215

    return msg, None


def quarantine_dmarc_failed_forward_email(alias, contact, envelope, msg) -> EmailLog:
    add_or_replace_header(msg, headers.SL_DIRECTION, "Forward")
    msg[headers.SL_ENVELOPE_FROM] = envelope.mail_from
    random_name = str(uuid.uuid4())
    s3_report_path = f"refused-emails/full-{random_name}.eml"
    s3.upload_email_from_bytesio(
        s3_report_path, BytesIO(message_to_bytes(msg)), f"full-{random_name}"
    )
    refused_email = RefusedEmail.create(
        full_report_path=s3_report_path, user_id=alias.user_id, flush=True
    )
    return EmailLog.create(
        user_id=alias.user_id,
        mailbox_id=alias.mailbox_id,
        contact_id=contact.id,
        alias_id=alias.id,
        message_id=str(msg[headers.MESSAGE_ID]),
        refused_email_id=refused_email.id,
        is_spam=True,
        blocked=True,
        commit=True,
    )


def apply_dmarc_policy_for_reply_phase(
    alias_from: Alias, contact_recipient: Contact, envelope: Envelope, msg: Message
) -> Optional[str]:
    spam_result = SpamdResult.extract_from_headers(msg, Phase.reply)
    if not DMARC_CHECK_ENABLED or not spam_result:
        return None

    if spam_result.dmarc not in (
        DmarcCheckResult.quarantine,
        DmarcCheckResult.reject,
        DmarcCheckResult.soft_fail,
    ):
        return None

    LOG.w(
        f"dmarc reply: Put email from {alias_from.email} to {contact_recipient} into quarantine. {spam_result.event_data()}, "
        f"mail_from:{envelope.mail_from}, from_header: {msg[headers.FROM]}"
    )
    send_email_with_rate_control(
        alias_from.user,
        ALERT_DMARC_FAILED_REPLY_PHASE,
        alias_from.user.email,
        f"Attempt to send an email to your contact {contact_recipient.email} from {envelope.mail_from}",
        render(
            "transactional/spoof-reply.txt.jinja2",
            contact=contact_recipient,
            alias=alias_from,
            sender=envelope.mail_from,
        ),
        render(
            "transactional/spoof-reply.html",
            contact=contact_recipient,
            alias=alias_from,
            sender=envelope.mail_from,
        ),
    )
    return status.E215
