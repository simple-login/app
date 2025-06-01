"""
Enable SMTP access for aliases.

This will allow a MUA to send directly from the alias without the need for the user to create a reverse-alias.

"""

import argparse
import time
import ssl
import uuid
import email

import newrelic.agent

from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult, LoginPassword, Envelope

from sqlalchemy.orm.exc import ObjectDeletedError
from sqlalchemy.exc import IntegrityError
from email.message import Message
from email.utils import formataddr, formatdate
from init_app import load_pgp_public_keys

from server import create_light_app
from app import config
from app.alias_utils import get_alias_recipient_name
from app.errors import NonReverseAliasInReplyPhase
from app.db import Session
from app.log import LOG, set_message_id
from app.email import status, headers
from app.utils import sanitize_email
from app.email.spam import get_spam_score
from app.pgp_utils import PGPException
from app.models import Alias, SMTPCredentials, EmailLog, Contact, Mailbox, VerpType
from app.email_validation import is_valid_email
from app.config import (
    SMTP_SSL_KEY_FILEPATH,
    SMTP_SSL_CERT_FILEPATH,
    NOREPLY,
    ENABLE_SPAM_ASSASSIN,
    SPAMASSASSIN_HOST,
    MAX_REPLY_PHASE_SPAM_SCORE,
    BOUNCE_PREFIX_FOR_REPLY_PHASE,
    LOAD_PGP_EMAIL_HANDLER,
)
from app.email_utils import (
    copy,
    save_email_for_debugging,
    sanitize_header,
    get_header_unicode,
    parse_full_address,
    is_valid_alias_address_domain,
    get_spam_info,
    delete_all_headers_except,
    sl_sendmail,
    add_or_replace_header,
    should_add_dkim_signature,
    add_dkim_signature,
    send_email,
    render,
    get_email_domain_part,
    generate_reply_email,
    generate_verp_email,
    replace
)

from email_handler import (
    send_no_reply_response,
    handle_spam,
    prepare_pgp_message,
    replace_original_message_id,
    replace_header_when_reply,
    notify_mailbox
)


def get_or_create_contact_for_SMTP_phase(mail_from: str, alias: Alias) -> Contact:
    """
    Create Contact for SMTP phase
    """
    contact_email = mail_from

    if not is_valid_email(contact_email):
        LOG.w(
            "invalid contact email %s.",
            contact_email,
        )
        # either reuse a contact with empty email or create a new contact with empty email
        contact_email = ""

    contact_email = sanitize_email(contact_email, not_lower=True)

    contact = Contact.get_by(alias_id=alias.id, website_email=contact_email)
    if not contact:
        try:
            contact = Contact.create(
                user_id=alias.user_id,
                alias_id=alias.id,
                website_email=contact_email,
                mail_from=mail_from,
                reply_email=generate_reply_email(contact_email, alias.user)
                if is_valid_email(contact_email)
                else NOREPLY,
                automatic_created=True,
            )
            if not contact_email:
                LOG.d("Create a contact with invalid email for %s", alias)
                contact.invalid_email = True

            LOG.d(
                "create contact %s for %s, reverse alias:%s",
                contact_email,
                alias,
                contact.reply_email,
            )

            Session.commit()
        except IntegrityError:
            LOG.w("Contact %s %s already exist", alias, contact_email)
            Session.rollback()
            contact = Contact.get_by(alias_id=alias.id, website_email=contact_email)

    return contact


def handle_SMTP(envelope, msg: Message, rcpt_to: str) -> (bool, str):
    """
    Return whether an email has been delivered and
    the smtp status ("250 Message accepted", "550 Non-existent email address", etc)
    """
    website_email = rcpt_to

    alias_address: str = envelope.mail_from
    alias = Alias.get_by(email=alias_address)
    if not alias:
        LOG.e("Alias: %s isn't known", alias_address)
        return False, status.E503

    user = alias.user
    if user.disabled:
        LOG.e(
            "User %s disabled, disable sending emails from %s to %s",
            user,
            alias,
            website_email,
        )
        return [(False, status.E504)]

    alias_domain = get_email_domain_part(alias_address)

    # Sanity check: verify alias domain is managed by SimpleLogin
    # scenario: a user have removed a domain but due to a bug, the aliases are still there
    if not is_valid_alias_address_domain(alias.email):
        LOG.e("%s domain isn't known", alias)
        return False, status.E503

    contact = Contact.get_by(website_email=website_email)

    # Check if website email id a reverse alias.
    if not contact:
        contact = Contact.get_by(reply_email=website_email)
        if contact:
            LOG.d(f"{website_email} is a reverse-alias. Changing 'To:' to actual website email.")
            website_email = contact.website_email
            replace_header_when_reply(msg, alias, headers.TO)
            replace_header_when_reply(msg, alias, headers.CC)

    if not contact:
        LOG.d(f"No contact with {website_email} as website email")
    try:
        LOG.d("Create or get contact for website_email:%s", website_email)
        contact = get_or_create_contact_for_SMTP_phase(website_email, alias)
    except ObjectDeletedError:
        LOG.d("maybe alias was deleted in the meantime")
        alias = Alias.get_by(email=alias_address)
        if not alias:
            LOG.i("Alias %s was deleted in the meantime", alias_address)
            return [(False, status.E515)]

    mailbox = Mailbox.get_by(id=alias.mailbox_id)

    email_log = EmailLog.create(
        contact_id=contact.id,
        alias_id=contact.alias_id,
        is_reply=True,
        is_SMTP=True,
        user_id=contact.user_id,
        mailbox_id=mailbox.id,
        message_id=msg[headers.MESSAGE_ID],
        commit=True,
    )
    LOG.d("Create %s for %s, %s, %s", email_log, contact, user, mailbox)

    # Spam check
    if ENABLE_SPAM_ASSASSIN:
        spam_status = ""
        is_spam = False

        # do not use user.max_spam_score here
        if SPAMASSASSIN_HOST:
            start = time.time()
            spam_score, spam_report = get_spam_score(msg, email_log)
            LOG.d(
                "%s -> %s - spam score %s in %s seconds. Spam report %s",
                alias,
                contact,
                spam_score,
                time.time() - start,
                spam_report,
            )
            email_log.spam_score = spam_score
            if spam_score > MAX_REPLY_PHASE_SPAM_SCORE:
                is_spam = True
                # only set the spam report for spam
                email_log.spam_report = spam_report
        else:
            is_spam, spam_status = get_spam_info(
                msg, max_score=MAX_REPLY_PHASE_SPAM_SCORE
            )

        if is_spam:
            LOG.w(
                "Email detected as spam. SMTP phase. %s -> %s. Spam Score: %s, Spam Report: %s",
                alias,
                contact,
                email_log.spam_score,
                email_log.spam_report,
            )

            email_log.is_spam = True
            email_log.spam_status = spam_status
            Session.commit()

            handle_spam(contact, alias, msg, user, mailbox, email_log, is_reply=True)
            return False, status.E506

    delete_all_headers_except(
        msg,
        [
            headers.FROM,
            headers.TO,
            headers.CC,
            headers.SUBJECT,
            headers.DATE,
            # do not delete original message id
            headers.MESSAGE_ID,
            # References and In-Reply-To are used for keeping the email thread
            headers.REFERENCES,
            headers.IN_REPLY_TO,
            headers.SL_QUEUE_ID,
        ]
        + headers.MIME_HEADERS,
    )

    orig_to = msg[headers.TO]
    orig_cc = msg[headers.CC]

    # replace the reverse-alias by the contact email in the email body
    # as this is usually included when replying
    # This can rarely happen in SMTP Stage, but it's better to check and replace
    if user.replace_reverse_alias:
        revese_alias_email = contact.reply_email
        LOG.d("Replace reverse-alias %s by contact email %s", revese_alias_email, contact)
        msg = replace(msg, revese_alias_email, contact.website_email)
        LOG.d("Replace mailbox %s by alias email %s", mailbox.email, alias.email)
        msg = replace(msg, mailbox.email, alias.email)

        if config.ENABLE_ALL_REVERSE_ALIAS_REPLACEMENT:
            start = time.time()
            # MAX_NB_REVERSE_ALIAS_REPLACEMENT is there to limit potential attack
            contact_query = (
                Contact.query()
                .filter(Contact.alias_id == alias.id)
                .limit(config.MAX_NB_REVERSE_ALIAS_REPLACEMENT)
            )

            # replace reverse alias by real address for all contacts
            for reply_email, website_email in contact_query.values(
                    Contact.reply_email, Contact.website_email
            ):
                msg = replace(msg, reply_email, website_email)

            elapsed = time.time() - start
            LOG.d(
                "Replace reverse alias by real address for %s contacts takes %s seconds",
                contact_query.count(),
                elapsed,
            )
            newrelic.agent.record_custom_metric(
                "Custom/reverse_alias_replacement_time", elapsed
            )

    # create PGP email if needed
    if contact.pgp_finger_print and user.is_premium():
        LOG.d("Encrypt message for contact %s", contact)
        try:
            msg = prepare_pgp_message(
                msg, contact.pgp_finger_print, contact.pgp_public_key
            )
        except PGPException:
            LOG.e(
                "Cannot encrypt message %s -> %s. %s %s", alias, contact, mailbox, user
            )
            # programming error, user shouldn't see a new email log
            EmailLog.delete(email_log.id, commit=True)
            # return 421 so the client can retry later
            return False, status.E402

    Session.commit()

    recipient_name = get_alias_recipient_name(alias)
    if recipient_name.message:
        LOG.d(recipient_name.message)
    LOG.d("From header is %s", recipient_name.name)
    add_or_replace_header(msg, headers.FROM, recipient_name.name)

    replace_original_message_id(alias, email_log, msg)

    if not msg[headers.DATE]:
        date_header = formatdate()
        LOG.w("missing date header, add one")
        msg[headers.DATE] = date_header

    msg[headers.SL_DIRECTION] = "Reply"
    msg[headers.SL_EMAIL_LOG_ID] = str(email_log.id)

    LOG.d(
        "send email from %s to %s, mail_options:%s,rcpt_options:%s",
        alias.email,
        contact.website_email,
        envelope.mail_options,
        envelope.rcpt_options,
    )

    if should_add_dkim_signature(alias_domain):
        add_dkim_signature(msg, alias_domain)

    try:
        sl_sendmail(
            generate_verp_email(VerpType.bounce_reply, email_log.id, alias_domain),
            contact.website_email,
            msg,
            envelope.mail_options,
            envelope.rcpt_options,
            is_forward=False,
        )

        # if alias belongs to several mailboxes, notify other mailboxes about this email
        other_mailboxes = [mb for mb in alias.mailboxes if mb.email != mailbox.email]
        for mb in other_mailboxes:
            notify_mailbox(alias, mailbox, mb, msg, orig_to, orig_cc, alias_domain)

    except Exception:
        LOG.w("Cannot send email from %s to %s", alias, contact)
        EmailLog.delete(email_log.id, commit=True)
        send_email(
            mailbox.email,
            f"Email cannot be sent to {contact.email} from {alias.email}",
            render(
                "transactional/reply-error.txt.jinja2",
                user=user,
                alias=alias,
                contact=contact,
                contact_domain=get_email_domain_part(contact.email),
            ),
            render(
                "transactional/reply-error.html",
                user=user,
                alias=alias,
                contact=contact,
                contact_domain=get_email_domain_part(contact.email),
            ),
        )

    # return 250 even if error as user is already informed of the incident and can retry sending the email
    return True, status.E200


class SMTPAuthenticator:
    def fail_nothandled(self, message=None) -> AuthResult:
        return AuthResult(success=False, handled=False, message=message)

    def __call__(self, server, session, envelope, mechanism, auth_data):
        if mechanism not in ("LOGIN", "PLAIN"):
            LOG.e("mechanism %s not supported.", mechanism)
            return self.fail_nothandled("550 Mechanism not supported")

        if not isinstance(auth_data, LoginPassword):
            LOG.e("Incorrect Format for Credentials")
            return self.fail_nothandled(status.E501)

        username = auth_data.login.decode("utf-8")
        password = auth_data.password.decode("utf-8")

        alias = Alias.get_by(email=username)
        if not alias:
            LOG.e("alias %s does not exist.", username)
            return self.fail_nothandled(status.E502)

        user = alias.user

        if not user or user.disabled:
            LOG.e("User for alias %s is disabled", username)
            return self.fail_nothandled(status.E504)

        is_smtp_enabled_for_aliases = user.enable_SMTP_aliases

        if not is_smtp_enabled_for_aliases:
            LOG.e("SMTP disabled by user")
            return self.fail_nothandled("521 SMTP disabled by user")

        SMTPCred = SMTPCredentials.get_by(alias_id=alias.id)
        if not SMTPCred or not SMTPCred.check_password(password):
            LOG.e(
                "Credentials Mismatch for alias %s",
                username,
            )
            return self.fail_nothandled()

        return AuthResult(success=True, auth_data=auth_data)


def handle(envelope: Envelope, msg: Message) -> str:
    """Return SMTP status"""

    # sanitize mail_from, rcpt_tos
    mail_from = sanitize_email(envelope.mail_from)
    rcpt_tos = [sanitize_email(rcpt_to) for rcpt_to in envelope.rcpt_tos]
    envelope.mail_from = mail_from
    envelope.rcpt_tos = rcpt_tos

    # sanitize email headers
    sanitize_header(msg, "from")
    sanitize_header(msg, "to")
    sanitize_header(msg, "cc")
    sanitize_header(msg, "reply-to")

    LOG.d(
        "==>> Handle mail_from:%s, rcpt_tos:%s, header_from:%s, header_to:%s, "
        "cc:%s, reply-to:%s, message_id:%s, client_ip:%s, headers:%s, mail_options:%s, rcpt_options:%s",
        mail_from,
        rcpt_tos,
        msg[headers.FROM],
        msg[headers.TO],
        msg[headers.CC],
        msg[headers.REPLY_TO],
        msg[headers.MESSAGE_ID],
        msg[headers.SL_CLIENT_IP],
        msg._headers,
        envelope.mail_options,
        envelope.rcpt_options,
    )

    res: [(bool, str)] = []

    nb_rcpt_tos = len(rcpt_tos)
    for rcpt_index, rcpt_to in enumerate(rcpt_tos):
        if rcpt_to in config.NOREPLIES:
            LOG.i("email sent to {} address from {}".format(NOREPLY, mail_from))
            send_no_reply_response(mail_from, msg)
            return status.E200

        # create a copy of msg for each recipient except the last one
        # as copy() is a slow function
        if rcpt_index < nb_rcpt_tos - 1:
            LOG.d("copy message for rcpt %s", rcpt_to)
            copy_msg = copy(msg)
        else:
            copy_msg = msg

        # SMTP case
        LOG.d("SMTP phase %s(%s) -> %s", mail_from, copy_msg[headers.FROM], rcpt_to)
        is_delivered, smtp_status = handle_SMTP(envelope, copy_msg, rcpt_to)
        res.append((is_delivered, smtp_status))

    # to know whether both successful and unsuccessful deliveries can happen at the same time
    nb_success = len([is_success for (is_success, smtp_status) in res if is_success])
    # ignore E518 which is a normal condition
    nb_non_success = len(
        [
            is_success
            for (is_success, smtp_status) in res
            if not is_success and smtp_status != status.E518
        ]
    )

    if nb_success > 0 and nb_non_success > 0:
        LOG.e(f"some deliveries fail and some success, {mail_from}, {rcpt_tos}, {res}")

    for (is_success, smtp_status) in res:
        # Consider all deliveries successful if 1 delivery is successful
        if is_success:
            return smtp_status

    # Failed delivery for all, return the first failure
    return res[0][1]


class SMTPHandler:
    async def handle_DATA(self, server, session, envelope: Envelope):
        username = session.auth_data.login.decode("utf-8")
        msg = email.message_from_bytes(envelope.original_content)
        try:
            ret = self.check_and_handle(envelope, msg, username)
            return ret
        except Exception as e:
            LOG.e(
                "email handling fail with error:%s "
                "mail_from:%s, rcpt_tos:%s, header_from:%s, header_to:%s, saved to %s",
                e,
                envelope.mail_from,
                envelope.rcpt_tos,
                msg[headers.FROM],
                msg[headers.TO],
                save_email_for_debugging(
                    msg, file_name_prefix=e.__class__.__name__
                ),  # todo: remove
            )
            return status.E404

    def check_and_handle(self, envelope: Envelope, msg: Message, username) -> str:
        """Return SMTP status"""
        mail_from = sanitize_email(envelope.mail_from)
        envelope.mail_from = mail_from

        # sanitize email headers
        sanitize_header(msg, "from")

        # If Sending from MUA, "mail_from", "from" and "username" should match <- This should prevent Spoofing
        from_header = get_header_unicode(msg[headers.FROM])
        if from_header:
            try:
                _, from_header_address = parse_full_address(from_header)
            except ValueError:
                LOG.w("cannot parse the From header %s", from_header)
                return status.E501  # Could be changed
            else:
                if mail_from != username or from_header_address != username:
                    LOG.e(
                        "Mail_From: '%s' , From Header: '%s' and username '%s' does not match",
                        mail_from,
                        msg[headers.FROM],
                        username,
                    )
                    return status.E509

        return self._handle(envelope, msg)

    @newrelic.agent.background_task()
    def _handle(self, envelope: Envelope, msg: Message):
        start = time.time()

        # generate a different message_id to keep track of an email lifecycle
        message_id = str(uuid.uuid4())
        set_message_id(message_id)

        LOG.d("====>=====>====>====>====>====>====>====>")
        LOG.i(
            "New message, mail from %s, rctp tos %s ",
            envelope.mail_from,
            envelope.rcpt_tos,
        )
        newrelic.agent.record_custom_metric(
            "Custom/nb_rcpt_tos", len(envelope.rcpt_tos)
        )

        with create_light_app().app_context():
            ret = handle(envelope, msg)
            elapsed = time.time() - start

            LOG.i(
                "Finish mail_from %s, rcpt_tos %s, takes %s seconds <<===",
                envelope.mail_from,
                envelope.rcpt_tos,
                elapsed,
            )
            newrelic.agent.record_custom_metric("Custom/email_handler_time", elapsed)
            newrelic.agent.record_custom_metric("Custom/number_incoming_email", 1)
            return ret


def main(port: int):
    """Use aiosmtpd Controller"""
    handler = SMTPHandler()
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS)
    ssl_context.load_cert_chain(certfile=SMTP_SSL_CERT_FILEPATH, keyfile=SMTP_SSL_KEY_FILEPATH)
    controller = Controller(
        handler,
        hostname="0.0.0.0",
        port=port,
        ssl_context=ssl_context,  # Implicit SSL/TLS
        authenticator=SMTPAuthenticator(),
        auth_required=True,
        # Below param needs to be set in case of implicit SSL/TLS as per (https://github.com/aio-libs/aiosmtpd/issues/281)
        auth_require_tls=False,
    )

    controller.start()
    LOG.d("Start SMTP controller %s %s", controller.hostname, controller.port)

    if LOAD_PGP_EMAIL_HANDLER:
        LOG.w("LOAD PGP keys")
        load_pgp_public_keys()

    while True:
        time.sleep(2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-p", "--port", help="SMTP port to listen for", type=int, default=465
    )
    args = parser.parse_args()

    LOG.i("Listen for port %s", args.port)
    main(port=args.port)
