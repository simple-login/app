"""
Handle the email *forward* and *reply*. phase. There are 3 actors:
- contact: who sends emails to alias@sl.co address
- SL email handler (this script)
- user personal email: to be protected. Should never leak to contact.

This script makes sure that in the forward phase, the email that is forwarded to user personal email has the following
envelope and header fields:
Envelope:
    mail from: @contact
    rcpt to: @personal_email
Header:
    From: @contact
    To: alias@sl.co # so user knows this email is sent to alias
    Reply-to: special@sl.co # magic HERE

And in the reply phase:
Envelope:
    mail from: @contact
    rcpt to: @contact

Header:
    From: alias@sl.co # so for contact the email comes from alias. magic HERE
    To: @contact

The special@sl.co allows to hide user personal email when user clicks "Reply" to the forwarded email.
It should contain the following info:
- alias
- @contact


"""
import email
import time
import uuid
from email import encoders
from email.message import Message
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.utils import parseaddr, formataddr
from io import BytesIO
from smtplib import SMTP

from aiosmtpd.controller import Controller
from aiosmtpd.smtp import Envelope

from app import pgp_utils, s3
from app.alias_utils import try_auto_create
from app.config import (
    EMAIL_DOMAIN,
    POSTFIX_SERVER,
    URL,
    ALIAS_DOMAINS,
    POSTFIX_SUBMISSION_TLS,
    UNSUBSCRIBER,
)
from app.email_utils import (
    send_email,
    add_dkim_signature,
    add_or_replace_header,
    delete_header,
    email_belongs_to_alias_domains,
    render,
    get_orig_message_from_bounce,
    delete_all_headers_except,
    get_addrs_from_header,
    get_spam_info,
    get_orig_message_from_spamassassin_report,
    parseaddr_unicode,
)
from app.extensions import db
from app.greylisting import greylisting_needed
from app.log import LOG
from app.models import (
    Alias,
    Contact,
    EmailLog,
    CustomDomain,
    User,
    RefusedEmail,
)
from app.utils import random_string
from server import create_app

# used when an alias receives email from its own mailbox
# can happen when user "Reply All" on some email clients
_SELF_FORWARDING_STATUS = "550 SL self-forward"

# fix the database connection leak issue
# use this method instead of create_app
def new_app():
    app = create_app()

    @app.teardown_appcontext
    def shutdown_session(response_or_exc):
        # same as shutdown_session() in flask-sqlalchemy but this is not enough
        db.session.remove()

        # dispose the engine too
        db.engine.dispose()

    return app


def get_or_create_contact(contact_from_header: str, alias: Alias) -> Contact:
    """
    contact_from_header is the RFC 2047 format FROM header
    """
    # force convert header to string, sometimes contact_from_header is Header object
    contact_from_header = str(contact_from_header)
    contact_name, contact_email = parseaddr_unicode(contact_from_header)
    contact = Contact.get_by(alias_id=alias.id, website_email=contact_email)
    if contact:
        if contact.name != contact_name:
            LOG.d(
                "Update contact %s name %s to %s", contact, contact.name, contact_name,
            )
            contact.name = contact_name
            db.session.commit()
    else:
        LOG.debug(
            "create contact for alias %s and contact %s", alias, contact_from_header,
        )

        reply_email = generate_reply_email()

        contact = Contact.create(
            user_id=alias.user_id,
            alias_id=alias.id,
            website_email=contact_email,
            name=contact_name,
            reply_email=reply_email,
        )
        db.session.commit()

    return contact


def replace_header_when_forward(msg: Message, alias: Alias, header: str):
    """
    Replace CC or To header by Reply emails in forward phase
    """
    addrs = get_addrs_from_header(msg, header)

    # Nothing to do
    if not addrs:
        return

    new_addrs: [str] = []
    need_replace = False

    for addr in addrs:
        contact_name, contact_email = parseaddr_unicode(addr)

        # no transformation when alias is already in the header
        if contact_email == alias.email:
            new_addrs.append(addr)
            continue

        contact = Contact.get_by(alias_id=alias.id, website_email=contact_email)
        if contact:
            # update the contact name if needed
            if contact.name != contact_name:
                LOG.d(
                    "Update contact %s name %s to %s",
                    contact,
                    contact.name,
                    contact_name,
                )
                contact.name = contact_name
                db.session.commit()
        else:
            LOG.debug(
                "create contact for alias %s and email %s, header %s",
                alias,
                contact_email,
                header,
            )

            reply_email = generate_reply_email()

            contact = Contact.create(
                user_id=alias.user_id,
                alias_id=alias.id,
                website_email=contact_email,
                name=contact_name,
                reply_email=reply_email,
                is_cc=header.lower() == "cc",
            )
            db.session.commit()

        new_addrs.append(contact.new_addr())
        need_replace = True

    if need_replace:
        new_header = ",".join(new_addrs)
        LOG.d("Replace %s header, old: %s, new: %s", header, msg[header], new_header)
        add_or_replace_header(msg, header, new_header)
    else:
        LOG.d("No need to replace %s header", header)


def replace_header_when_reply(msg: Message, alias: Alias, header: str):
    """
    Replace CC or To Reply emails by original emails
    """
    addrs = get_addrs_from_header(msg, header)

    # Nothing to do
    if not addrs:
        return

    new_addrs: [str] = []

    for addr in addrs:
        name, reply_email = parseaddr(addr)

        # no transformation when alias is already in the header
        if reply_email == alias.email:
            continue

        contact = Contact.get_by(reply_email=reply_email)
        if not contact:
            LOG.warning(
                "%s email in reply phase %s must be reply emails", header, reply_email
            )
            # still keep this email in header
            new_addrs.append(addr)
        else:
            new_addrs.append(formataddr((contact.name, contact.website_email)))

    new_header = ",".join(new_addrs)
    LOG.d("Replace %s header, old: %s, new: %s", header, msg[header], new_header)
    add_or_replace_header(msg, header, new_header)


def generate_reply_email():
    # generate a reply_email, make sure it is unique
    # not use while loop to avoid infinite loop
    reply_email = f"reply+{random_string(30)}@{EMAIL_DOMAIN}"
    for _ in range(1000):
        if not Contact.get_by(reply_email=reply_email):
            # found!
            break
        reply_email = f"reply+{random_string(30)}@{EMAIL_DOMAIN}"

    return reply_email


def should_append_alias(msg: Message, address: str):
    """whether an alias should be appended to TO header in message"""

    if msg["To"] and address in msg["To"]:
        return False
    if msg["Cc"] and address in msg["Cc"]:
        return False

    return True


def prepare_pgp_message(orig_msg: Message, pgp_fingerprint: str):
    msg = MIMEMultipart("encrypted", protocol="application/pgp-encrypted")

    # copy all headers from original message except the "Content-Type"
    for i in reversed(range(len(orig_msg._headers))):
        header_name = orig_msg._headers[i][0].lower()
        if header_name != "Content-Type".lower():
            msg[header_name] = orig_msg._headers[i][1]

    # Delete unnecessary headers in orig_msg except to save space
    delete_all_headers_except(
        orig_msg,
        [
            "MIME-Version",
            "Content-Type",
            "Content-Disposition",
            "Content-Transfer-Encoding",
        ],
    )

    first = MIMEApplication(
        _subtype="pgp-encrypted", _encoder=encoders.encode_7or8bit, _data=""
    )
    first.set_payload("Version: 1")
    msg.attach(first)

    second = MIMEApplication("octet-stream", _encoder=encoders.encode_7or8bit)
    second.add_header("Content-Disposition", "inline")
    # encrypt original message
    encrypted_data = pgp_utils.encrypt_file(
        BytesIO(orig_msg.as_bytes()), pgp_fingerprint
    )
    second.set_payload(encrypted_data)
    msg.attach(second)

    return msg


def handle_forward(envelope, smtp: SMTP, msg: Message, rcpt_to: str) -> (bool, str):
    """return whether an email has been delivered and
    the smtp status ("250 Message accepted", "550 Non-existent email address", etc)
    """
    address = rcpt_to.lower()  # alias@SL

    alias = Alias.get_by(email=address)
    if not alias:
        LOG.d("alias %s not exist. Try to see if it can be created on the fly", address)
        alias = try_auto_create(address)
        if not alias:
            LOG.d("alias %s cannot be created on-the-fly, return 550", address)
            return False, "550 SL Email not exist"

    mailbox = alias.mailbox
    mailbox_email = mailbox.email
    user = alias.user

    # Sometimes when user clicks on "reply all"
    # an email is sent to the same alias that the previous message is destined to
    if envelope.mail_from == mailbox_email:
        # nothing to do
        LOG.d("Forward from %s to %s, nothing to do", envelope.mail_from, mailbox_email)
        return False, _SELF_FORWARDING_STATUS

    contact = get_or_create_contact(msg["From"], alias)

    spam_check = True

    # create PGP email if needed
    if mailbox.pgp_finger_print and user.is_premium():
        LOG.d("Encrypt message using mailbox %s", mailbox)
        msg = prepare_pgp_message(msg, mailbox.pgp_finger_print)

        # no need to spam check for encrypted message
        spam_check = False

    if spam_check:
        is_spam, spam_status = get_spam_info(msg)
        if is_spam:
            LOG.warning("Email detected as spam. Alias: %s, from: %s", alias, contact)
            handle_spam(contact, alias, msg, user, mailbox_email, spam_status)
            return False, "550 SL ignored"

    forward_log = EmailLog.create(contact_id=contact.id, user_id=contact.user_id)

    if alias.enabled:
        # add custom header
        add_or_replace_header(msg, "X-SimpleLogin-Type", "Forward")

        # remove reply-to & sender header if present
        delete_header(msg, "Reply-To")
        delete_header(msg, "Sender")

        # change the from header so the sender comes from @SL
        # so it can pass DMARC check
        # replace the email part in from: header
        contact_from_header = msg["From"]
        new_from_header = contact.new_addr()
        add_or_replace_header(msg, "From", new_from_header)
        LOG.d("new_from_header:%s, old header %s", new_from_header, contact_from_header)

        # replace CC & To emails by reply-email for all emails that are not alias
        replace_header_when_forward(msg, alias, "Cc")
        replace_header_when_forward(msg, alias, "To")

        # append alias into the TO header if it's not present in To or CC
        if should_append_alias(msg, alias.email):
            LOG.d("append alias %s  to TO header %s", alias, msg["To"])
            if msg["To"]:
                to_header = msg["To"] + "," + alias.email
            else:
                to_header = alias.email

            add_or_replace_header(msg, "To", to_header.strip())

        # add List-Unsubscribe header
        if UNSUBSCRIBER:
            unsubscribe_link = f"mailto:{UNSUBSCRIBER}?subject={alias.id}="
            add_or_replace_header(msg, "List-Unsubscribe", f"<{unsubscribe_link}>")
        else:
            unsubscribe_link = f"{URL}/dashboard/unsubscribe/{alias.id}"
            add_or_replace_header(msg, "List-Unsubscribe", f"<{unsubscribe_link}>")
            add_or_replace_header(
                msg, "List-Unsubscribe-Post", "List-Unsubscribe=One-Click"
            )

        add_dkim_signature(msg, EMAIL_DOMAIN)

        LOG.d(
            "Forward mail from %s to %s, mail_options %s, rcpt_options %s ",
            contact.website_email,
            mailbox_email,
            envelope.mail_options,
            envelope.rcpt_options,
        )

        # smtp.send_message has UnicodeEncodeErroremail issue
        # encode message raw directly instead
        smtp.sendmail(
            contact.reply_email,
            mailbox_email,
            msg.as_bytes(),
            envelope.mail_options,
            envelope.rcpt_options,
        )
    else:
        LOG.d("%s is disabled, do not forward", alias)
        forward_log.blocked = True

    db.session.commit()
    return True, "250 Message accepted for delivery"


def handle_reply(envelope, smtp: SMTP, msg: Message, rcpt_to: str) -> (bool, str):
    """
    return whether an email has been delivered and
    the smtp status ("250 Message accepted", "550 Non-existent email address", etc)
    """
    reply_email = rcpt_to.lower()

    # reply_email must end with EMAIL_DOMAIN
    if not reply_email.endswith(EMAIL_DOMAIN):
        LOG.warning(f"Reply email {reply_email} has wrong domain")
        return False, "550 SL wrong reply email"

    contact = Contact.get_by(reply_email=reply_email)
    if not contact:
        LOG.warning(f"No such forward-email with {reply_email} as reply-email")
        return False, "550 SL wrong reply email"

    alias = contact.alias
    address: str = contact.alias.email
    alias_domain = address[address.find("@") + 1 :]

    # alias must end with one of the ALIAS_DOMAINS or custom-domain
    if not email_belongs_to_alias_domains(alias.email):
        if not CustomDomain.get_by(domain=alias_domain):
            return False, "550 SL alias unknown by SimpleLogin"

    user = alias.user
    mailbox_email = alias.mailbox_email()

    # bounce email initiated by Postfix
    # can happen in case emails cannot be delivered to user-email
    # in this case Postfix will try to send a bounce report to original sender, which is
    # the "reply email"
    if envelope.mail_from == "<>":
        LOG.warning(
            "Bounce when sending to alias %s from %s, user %s",
            alias,
            contact.website_email,
            alias.user,
        )

        handle_bounce(contact, alias, msg, user, mailbox_email)
        return False, "550 SL ignored"

    # only mailbox can send email to the reply-email
    if envelope.mail_from.lower() != mailbox_email.lower():
        LOG.warning(
            f"Reply email can only be used by mailbox. "
            f"Actual mail_from: %s. msg from header: %s, Mailbox %s. reply_email %s",
            envelope.mail_from,
            msg["From"],
            mailbox_email,
            reply_email,
        )

        send_email(
            mailbox_email,
            f"Reply from your alias {alias.email} only works from your mailbox",
            render(
                "transactional/reply-must-use-personal-email.txt",
                name=user.name,
                alias=alias.email,
                sender=envelope.mail_from,
                mailbox_email=mailbox_email,
            ),
            render(
                "transactional/reply-must-use-personal-email.html",
                name=user.name,
                alias=alias.email,
                sender=envelope.mail_from,
                mailbox_email=mailbox_email,
            ),
        )

        # Notify sender that they cannot send emails to this address
        send_email(
            envelope.mail_from,
            f"Your email ({envelope.mail_from}) is not allowed to send emails to {reply_email}",
            render(
                "transactional/send-from-alias-from-unknown-sender.txt",
                sender=envelope.mail_from,
                reply_email=reply_email,
            ),
            render(
                "transactional/send-from-alias-from-unknown-sender.html",
                sender=envelope.mail_from,
                reply_email=reply_email,
            ),
        )

        return False, "550 SL ignored"

    delete_header(msg, "DKIM-Signature")

    delete_header(msg, "Received")

    # make the email comes from alias
    add_or_replace_header(msg, "From", alias.email)

    # some email providers like ProtonMail adds automatically the Reply-To field
    # make sure to delete it
    delete_header(msg, "Reply-To")

    # remove sender header if present as this could reveal user real email
    delete_header(msg, "Sender")
    delete_header(msg, "X-Sender")

    replace_header_when_reply(msg, alias, "To")
    replace_header_when_reply(msg, alias, "Cc")

    # Received-SPF is injected by postfix-policyd-spf-python can reveal user original email
    delete_header(msg, "Received-SPF")

    LOG.d(
        "send email from %s to %s, mail_options:%s,rcpt_options:%s",
        alias.email,
        contact.website_email,
        envelope.mail_options,
        envelope.rcpt_options,
    )

    if alias_domain in ALIAS_DOMAINS:
        add_dkim_signature(msg, alias_domain)
    # add DKIM-Signature for custom-domain alias
    else:
        custom_domain: CustomDomain = CustomDomain.get_by(domain=alias_domain)
        if custom_domain.dkim_verified:
            add_dkim_signature(msg, alias_domain)

    smtp.sendmail(
        alias.email,
        contact.website_email,
        msg.as_bytes(),
        envelope.mail_options,
        envelope.rcpt_options,
    )

    EmailLog.create(contact_id=contact.id, is_reply=True, user_id=contact.user_id)
    db.session.commit()

    return True, "250 Message accepted for delivery"


def handle_bounce(
    contact: Contact, alias: Alias, msg: Message, user: User, mailbox_email: str
):
    address = alias.email
    email_log: EmailLog = EmailLog.create(
        contact_id=contact.id, bounced=True, user_id=contact.user_id
    )
    db.session.commit()

    nb_bounced = EmailLog.filter_by(contact_id=contact.id, bounced=True).count()
    disable_alias_link = f"{URL}/dashboard/unsubscribe/{alias.id}"

    # Store the bounced email
    orig_msg = get_orig_message_from_bounce(msg)
    # generate a name for the email
    random_name = str(uuid.uuid4())

    full_report_path = f"refused-emails/full-{random_name}.eml"
    s3.upload_email_from_bytesio(full_report_path, BytesIO(msg.as_bytes()), random_name)

    file_path = None
    if orig_msg:
        file_path = f"refused-emails/{random_name}.eml"
        s3.upload_email_from_bytesio(
            file_path, BytesIO(orig_msg.as_bytes()), random_name
        )

    refused_email = RefusedEmail.create(
        path=file_path, full_report_path=full_report_path, user_id=user.id
    )
    db.session.flush()

    email_log.refused_email_id = refused_email.id
    db.session.commit()

    LOG.d("Create refused email %s", refused_email)

    refused_email_url = (
        URL + f"/dashboard/refused_email?highlight_id=" + str(email_log.id)
    )

    # inform user if this is the first bounced email
    if nb_bounced == 1:
        LOG.d(
            "Inform user %s about bounced email sent by %s to alias %s",
            user,
            contact.website_email,
            address,
        )
        send_email(
            # use user mail here as only user is authenticated to see the refused email
            user.email,
            f"Email from {contact.website_email} to {address} cannot be delivered to your inbox",
            render(
                "transactional/bounced-email.txt",
                name=user.name,
                alias=alias,
                website_email=contact.website_email,
                disable_alias_link=disable_alias_link,
                refused_email_url=refused_email_url,
                mailbox_email=mailbox_email,
            ),
            render(
                "transactional/bounced-email.html",
                name=user.name,
                alias=alias,
                website_email=contact.website_email,
                disable_alias_link=disable_alias_link,
                refused_email_url=refused_email_url,
                mailbox_email=mailbox_email,
            ),
            # cannot include bounce email as it can contain spammy text
            # bounced_email=msg,
        )
    # disable the alias the second time email is bounced
    elif nb_bounced >= 2:
        LOG.d(
            "Bounce happens again with alias %s from %s. Disable alias now ",
            address,
            contact.website_email,
        )
        alias.enabled = False
        db.session.commit()

        send_email(
            # use user mail here as only user is authenticated to see the refused email
            user.email,
            f"Alias {address} has been disabled due to second undelivered email from {contact.website_email}",
            render(
                "transactional/automatic-disable-alias.txt",
                name=user.name,
                alias=alias,
                website_email=contact.website_email,
                refused_email_url=refused_email_url,
                mailbox_email=mailbox_email,
            ),
            render(
                "transactional/automatic-disable-alias.html",
                name=user.name,
                alias=alias,
                website_email=contact.website_email,
                refused_email_url=refused_email_url,
                mailbox_email=mailbox_email,
            ),
            # cannot include bounce email as it can contain spammy text
            # bounced_email=msg,
        )


def handle_spam(
    contact: Contact,
    alias: Alias,
    msg: Message,
    user: User,
    mailbox_email: str,
    spam_status: str,
):
    email_log: EmailLog = EmailLog.create(
        contact_id=contact.id,
        user_id=contact.user_id,
        is_spam=True,
        spam_status=spam_status,
    )
    db.session.commit()

    # Store the report & original email
    orig_msg = get_orig_message_from_spamassassin_report(msg)
    # generate a name for the email
    random_name = str(uuid.uuid4())

    full_report_path = f"spams/full-{random_name}.eml"
    s3.upload_email_from_bytesio(full_report_path, BytesIO(msg.as_bytes()), random_name)

    file_path = None
    if orig_msg:
        file_path = f"spams/{random_name}.eml"
        s3.upload_email_from_bytesio(
            file_path, BytesIO(orig_msg.as_bytes()), random_name
        )

    refused_email = RefusedEmail.create(
        path=file_path, full_report_path=full_report_path, user_id=user.id
    )
    db.session.flush()

    email_log.refused_email_id = refused_email.id
    db.session.commit()

    LOG.d("Create spam email %s", refused_email)

    refused_email_url = (
        URL + f"/dashboard/refused_email?highlight_id=" + str(email_log.id)
    )
    disable_alias_link = f"{URL}/dashboard/unsubscribe/{alias.id}"

    # inform user
    LOG.d(
        "Inform user %s about spam email sent by %s to alias %s",
        user,
        contact.website_email,
        alias.email,
    )
    send_email(
        mailbox_email,
        f"Email from {contact.website_email} to {alias.email} is detected as spam",
        render(
            "transactional/spam-email.txt",
            name=user.name,
            alias=alias,
            website_email=contact.website_email,
            disable_alias_link=disable_alias_link,
            refused_email_url=refused_email_url,
        ),
        render(
            "transactional/spam-email.html",
            name=user.name,
            alias=alias,
            website_email=contact.website_email,
            disable_alias_link=disable_alias_link,
            refused_email_url=refused_email_url,
        ),
    )


def handle_unsubscribe(envelope: Envelope):
    msg = email.message_from_bytes(envelope.original_content)

    # format: alias_id:
    subject = msg["Subject"]
    try:
        alias_id = int(subject[:-1])
        alias = Alias.get(alias_id)
    except Exception:
        LOG.warning("Cannot parse alias from subject %s", msg["Subject"])
        return "550 SL ignored"

    if not alias:
        LOG.warning("No such alias %s", alias_id)
        return "550 SL ignored"

    # This sender cannot unsubscribe
    if alias.mailbox_email() != envelope.mail_from:
        LOG.d("%s cannot disable alias %s", envelope.mail_from, alias)
        return "550 SL ignored"

    # Sender is owner of this alias
    alias.enabled = False
    db.session.commit()
    user = alias.user

    enable_alias_url = URL + f"/dashboard/?highlight_alias_id={alias.id}"
    send_email(
        envelope.mail_from,
        f"Alias {alias.email} has been disabled successfully",
        render(
            "transactional/unsubscribe-disable-alias.txt",
            user=user,
            alias=alias.email,
            enable_alias_url=enable_alias_url,
        ),
        render(
            "transactional/unsubscribe-disable-alias.html",
            user=user,
            alias=alias.email,
            enable_alias_url=enable_alias_url,
        ),
    )

    return "250 Unsubscribe request accepted"


def handle(envelope: Envelope, smtp: SMTP) -> str:
    """Return SMTP status"""
    # unsubscribe request
    if UNSUBSCRIBER and envelope.rcpt_tos == [UNSUBSCRIBER]:
        LOG.d("Handle unsubscribe request from %s", envelope.mail_from)
        return handle_unsubscribe(envelope)

    # Whether it's necessary to apply greylisting
    if greylisting_needed(envelope.mail_from, envelope.rcpt_tos):
        LOG.warning(
            "Grey listing applied for %s %s", envelope.mail_from, envelope.rcpt_tos
        )
        return "421 SL Retry later"

    # result of all deliveries
    # each element is a couple of whether the delivery is successful and the smtp status
    res: [(bool, str)] = []

    for rcpt_to in envelope.rcpt_tos:
        msg = email.message_from_bytes(envelope.original_content)

        # Reply case
        # recipient starts with "reply+" or "ra+" (ra=reverse-alias) prefix
        if rcpt_to.startswith("reply+") or rcpt_to.startswith("ra+"):
            LOG.debug(">>> Reply phase %s -> %s", envelope.mail_from, rcpt_to)
            is_delivered, smtp_status = handle_reply(envelope, smtp, msg, rcpt_to)
            res.append((is_delivered, smtp_status))
        else:  # Forward case
            LOG.debug(">>> Forward phase %s -> %s", envelope.mail_from, rcpt_to)
            is_delivered, smtp_status = handle_forward(envelope, smtp, msg, rcpt_to)
            res.append((is_delivered, smtp_status))

    # special handling for self-forwarding
    # just consider success delivery in this case
    if len(res) == 1 and res[0][1] == _SELF_FORWARDING_STATUS:
        LOG.d("Self-forwarding, ignore")
        return "250 SL OK"

    for (is_success, smtp_status) in res:
        # Consider all deliveries successful if 1 delivery is successful
        if is_success:
            return smtp_status

    # Failed delivery for all, return the first failure
    return res[0][1]


class MailHandler:
    async def handle_DATA(self, server, session, envelope: Envelope):
        LOG.debug(
            "===>> New message, mail from %s, rctp tos %s ",
            envelope.mail_from,
            envelope.rcpt_tos,
        )

        if POSTFIX_SUBMISSION_TLS:
            smtp = SMTP(POSTFIX_SERVER, 587)
            smtp.starttls()
        else:
            smtp = SMTP(POSTFIX_SERVER, 25)

        app = new_app()
        with app.app_context():
            return handle(envelope, smtp)


if __name__ == "__main__":
    controller = Controller(MailHandler(), hostname="0.0.0.0", port=20381)

    controller.start()
    LOG.d("Start mail controller %s %s", controller.hostname, controller.port)

    while True:
        time.sleep(2)
