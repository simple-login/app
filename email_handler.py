"""
Handle the email *forward* and *reply*. phase. There are 3 actors:
- website: who sends emails to alias@sl.co address
- SL email handler (this script)
- user personal email: to be protected. Should never leak to website.

This script makes sure that in the forward phase, the email that is forwarded to user personal email has the following
envelope and header fields:
Envelope:
    mail from: @website
    rcpt to: @personal_email
Header:
    From: @website
    To: alias@sl.co # so user knows this email is sent to alias
    Reply-to: special@sl.co # magic HERE

And in the reply phase:
Envelope:
    mail from: @website
    rcpt to: @website

Header:
    From: alias@sl.co # so for website the email comes from alias. magic HERE
    To: @website

The special@sl.co allows to hide user personal email when user clicks "Reply" to the forwarded email.
It should contain the following info:
- alias
- @website


"""
import time
import uuid
from email import encoders
from email.message import Message
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.parser import Parser
from email.policy import SMTPUTF8
from email.utils import parseaddr, formataddr
from io import BytesIO
from smtplib import SMTP
from typing import Optional

from aiosmtpd.controller import Controller

from app import pgp_utils, s3
from app.config import (
    EMAIL_DOMAIN,
    POSTFIX_SERVER,
    URL,
    ALIAS_DOMAINS,
    POSTFIX_SUBMISSION_TLS,
)
from app.email_utils import (
    send_email,
    add_dkim_signature,
    get_email_domain_part,
    add_or_replace_header,
    delete_header,
    send_cannot_create_directory_alias,
    send_cannot_create_domain_alias,
    email_belongs_to_alias_domains,
    render,
    get_orig_message_from_bounce,
    delete_all_headers_except,
)
from app.extensions import db
from app.log import LOG
from app.models import (
    Alias,
    Contact,
    EmailLog,
    CustomDomain,
    Directory,
    User,
    DeletedAlias,
    RefusedEmail,
)
from app.utils import random_string
from server import create_app


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


def try_auto_create(address: str) -> Optional[Alias]:
    """Try to auto-create the alias using directory or catch-all domain
    """
    alias = try_auto_create_catch_all_domain(address)
    if not alias:
        alias = try_auto_create_directory(address)

    return alias


def try_auto_create_directory(address: str) -> Optional[Alias]:
    """
    Try to create an alias with directory
    """
    # check if alias belongs to a directory, ie having directory/anything@EMAIL_DOMAIN format
    if email_belongs_to_alias_domains(address):
        # if there's no directory separator in the alias, no way to auto-create it
        if "/" not in address and "+" not in address and "#" not in address:
            return None

        # alias contains one of the 3 special directory separator: "/", "+" or "#"
        if "/" in address:
            sep = "/"
        elif "+" in address:
            sep = "+"
        else:
            sep = "#"

        directory_name = address[: address.find(sep)]
        LOG.d("directory_name %s", directory_name)

        directory = Directory.get_by(name=directory_name)
        if not directory:
            return None

        dir_user: User = directory.user

        if not dir_user.can_create_new_alias():
            send_cannot_create_directory_alias(dir_user, address, directory_name)
            return None

        # if alias has been deleted before, do not auto-create it
        if DeletedAlias.get_by(email=address, user_id=directory.user_id):
            LOG.warning(
                "Alias %s was deleted before, cannot auto-create using directory %s, user %s",
                address,
                directory_name,
                dir_user,
            )
            return None

        LOG.d("create alias %s for directory %s", address, directory)

        alias = Alias.create(
            email=address,
            user_id=directory.user_id,
            directory_id=directory.id,
            mailbox_id=dir_user.default_mailbox_id,
        )
        db.session.commit()
        return alias


def try_auto_create_catch_all_domain(address: str) -> Optional[Alias]:
    """Try to create an alias with catch-all domain"""

    # try to create alias on-the-fly with custom-domain catch-all feature
    # check if alias is custom-domain alias and if the custom-domain has catch-all enabled
    alias_domain = get_email_domain_part(address)
    custom_domain = CustomDomain.get_by(domain=alias_domain)

    if not custom_domain:
        return None

    # custom_domain exists
    if not custom_domain.catch_all:
        return None

    # custom_domain has catch-all enabled
    domain_user: User = custom_domain.user

    if not domain_user.can_create_new_alias():
        send_cannot_create_domain_alias(domain_user, address, alias_domain)
        return None

    # if alias has been deleted before, do not auto-create it
    if DeletedAlias.get_by(email=address, user_id=custom_domain.user_id):
        LOG.warning(
            "Alias %s was deleted before, cannot auto-create using domain catch-all %s, user %s",
            address,
            custom_domain,
            domain_user,
        )
        return None

    LOG.d("create alias %s for domain %s", address, custom_domain)

    alias = Alias.create(
        email=address,
        user_id=custom_domain.user_id,
        custom_domain_id=custom_domain.id,
        automatic_creation=True,
        mailbox_id=domain_user.default_mailbox_id,
    )

    db.session.commit()
    return alias


def get_or_create_contact(website_from_header: str, alias: Alias) -> Contact:
    """
    website_from_header can be the full-form email, i.e. "First Last <email@example.com>"
    """
    _, website_email = parseaddr(website_from_header)
    contact = Contact.get_by(alias_id=alias.id, website_email=website_email)
    if contact:
        # update the website_from if needed
        if contact.website_from != website_from_header:
            LOG.d("Update From header for %s", contact)
            contact.website_from = website_from_header
            db.session.commit()
    else:
        LOG.debug(
            "create forward email for alias %s and website email %s",
            alias,
            website_from_header,
        )

        # generate a reply_email, make sure it is unique
        # not use while loop to avoid infinite loop
        reply_email = f"reply+{random_string(30)}@{EMAIL_DOMAIN}"
        for _ in range(1000):
            if not Contact.get_by(reply_email=reply_email):
                # found!
                break
            reply_email = f"reply+{random_string(30)}@{EMAIL_DOMAIN}"

        contact = Contact.create(
            alias_id=alias.id,
            website_email=website_email,
            website_from=website_from_header,
            reply_email=reply_email,
        )
        db.session.commit()

    return contact


def should_append_alias(msg: Message, address: str):
    """whether an alias should be appened to TO header in message"""

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
    encrypted_data = pgp_utils.encrypt(orig_msg.as_string(), pgp_fingerprint)
    second.set_payload(encrypted_data)
    msg.attach(second)

    return msg


def handle_forward(envelope, smtp: SMTP, msg: Message, rcpt_to: str) -> str:
    """return *status_code message*"""
    address = rcpt_to.lower()  # alias@SL

    alias = Alias.get_by(email=address)
    if not alias:
        LOG.d("alias %s not exist. Try to see if it can be created on the fly", alias)
        alias = try_auto_create(address)
        if not alias:
            LOG.d("alias %s cannot be created on-the-fly, return 510", address)
            return "510 Email not exist"

    mailbox = alias.mailbox
    mailbox_email = mailbox.email

    # create PGP email if needed
    if mailbox.pgp_finger_print:
        LOG.d("Encrypt message using mailbox %s", mailbox)
        msg = prepare_pgp_message(msg, mailbox.pgp_finger_print)

    contact = get_or_create_contact(msg["From"], alias)
    forward_log = EmailLog.create(contact_id=contact.id)

    if alias.enabled:
        # add custom header
        add_or_replace_header(msg, "X-SimpleLogin-Type", "Forward")

        # remove reply-to & sender header if present
        delete_header(msg, "Reply-To")
        delete_header(msg, "Sender")

        # change the from header so the sender comes from @SL
        # so it can pass DMARC check
        # replace the email part in from: header
        website_from_header = msg["From"]
        website_name, website_email = parseaddr(website_from_header)
        new_website_name = (
            website_name
            + (" - " if website_name else "")
            + website_email.replace("@", " at ")
        )
        from_header = formataddr((new_website_name, contact.reply_email))
        add_or_replace_header(msg, "From", from_header)
        LOG.d("new from header:%s", from_header)

        # append alias into the TO header if it's not present in To or CC
        if should_append_alias(msg, alias.email):
            LOG.d("append alias %s  to TO header %s", alias, msg["To"])
            if msg["To"]:
                to_header = msg["To"] + "," + alias.email
            else:
                to_header = alias.email

            add_or_replace_header(msg, "To", to_header)

        # add List-Unsubscribe header
        unsubscribe_link = f"{URL}/dashboard/unsubscribe/{alias.id}"
        add_or_replace_header(msg, "List-Unsubscribe", f"<{unsubscribe_link}>")
        add_or_replace_header(
            msg, "List-Unsubscribe-Post", "List-Unsubscribe=One-Click"
        )

        add_dkim_signature(msg, EMAIL_DOMAIN)

        LOG.d(
            "Forward mail from %s to %s, mail_options %s, rcpt_options %s ",
            website_email,
            mailbox_email,
            envelope.mail_options,
            envelope.rcpt_options,
        )

        # smtp.send_message has UnicodeEncodeErroremail issue
        # encode message raw directly instead
        msg_raw = msg.as_string().encode()
        smtp.sendmail(
            contact.reply_email,
            mailbox_email,
            msg_raw,
            envelope.mail_options,
            envelope.rcpt_options,
        )
    else:
        LOG.d("%s is disabled, do not forward", alias)
        forward_log.blocked = True

    db.session.commit()
    return "250 Message accepted for delivery"


def handle_reply(envelope, smtp: SMTP, msg: Message, rcpt_to: str) -> str:
    reply_email = rcpt_to.lower()

    # reply_email must end with EMAIL_DOMAIN
    if not reply_email.endswith(EMAIL_DOMAIN):
        LOG.warning(f"Reply email {reply_email} has wrong domain")
        return "550 wrong reply email"

    contact = Contact.get_by(reply_email=reply_email)
    if not contact:
        LOG.warning(f"No such forward-email with {reply_email} as reply-email")
        return "550 wrong reply email"

    address: str = contact.alias.email
    alias_domain = address[address.find("@") + 1 :]

    # alias must end with one of the ALIAS_DOMAINS or custom-domain
    if not email_belongs_to_alias_domains(address):
        if not CustomDomain.get_by(domain=alias_domain):
            return "550 alias unknown by SimpleLogin"

    alias = contact.alias
    user = alias.user
    mailbox_email = alias.mailbox_email()

    # bounce email initiated by Postfix
    # can happen in case emails cannot be delivered to user-email
    # in this case Postfix will try to send a bounce report to original sender, which is
    # the "reply email"
    if envelope.mail_from == "<>":
        LOG.error(
            "Bounce when sending to alias %s from %s, user %s",
            address,
            contact.website_from,
            alias.user,
        )

        handle_bounce(contact, alias, msg, user, mailbox_email)
        return "550 ignored"

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

        user = alias.user
        send_email(
            mailbox_email,
            f"Reply from your alias {address} only works from your mailbox",
            render(
                "transactional/reply-must-use-personal-email.txt",
                name=user.name,
                alias=address,
                sender=envelope.mail_from,
                mailbox_email=mailbox_email,
            ),
            render(
                "transactional/reply-must-use-personal-email.html",
                name=user.name,
                alias=address,
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
            "",
        )

        return "550 ignored"

    delete_header(msg, "DKIM-Signature")

    # the email comes from alias
    add_or_replace_header(msg, "From", address)

    # some email providers like ProtonMail adds automatically the Reply-To field
    # make sure to delete it
    delete_header(msg, "Reply-To")

    # remove sender header if present as this could reveal user real email
    delete_header(msg, "Sender")

    add_or_replace_header(msg, "To", contact.website_email)

    # add List-Unsubscribe header
    unsubscribe_link = f"{URL}/dashboard/unsubscribe/{contact.alias_id}"
    add_or_replace_header(msg, "List-Unsubscribe", f"<{unsubscribe_link}>")
    add_or_replace_header(msg, "List-Unsubscribe-Post", "List-Unsubscribe=One-Click")

    # Received-SPF is injected by postfix-policyd-spf-python can reveal user original email
    delete_header(msg, "Received-SPF")

    LOG.d(
        "send email from %s to %s, mail_options:%s,rcpt_options:%s",
        address,
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

    msg_raw = msg.as_string().encode()
    smtp.sendmail(
        address,
        contact.website_email,
        msg_raw,
        envelope.mail_options,
        envelope.rcpt_options,
    )

    EmailLog.create(contact_id=contact.id, is_reply=True)
    db.session.commit()

    return "250 Message accepted for delivery"


def handle_bounce(
    contact: Contact, alias: Alias, msg: Message, user: User, mailbox_email: str
):
    address = alias.email
    fel: EmailLog = EmailLog.create(contact_id=contact.id, bounced=True)
    db.session.commit()

    nb_bounced = EmailLog.filter_by(contact_id=contact.id, bounced=True).count()
    disable_alias_link = f"{URL}/dashboard/unsubscribe/{alias.id}"

    # Store the bounced email
    orig_msg = get_orig_message_from_bounce(msg)
    # generate a name for the email
    random_name = str(uuid.uuid4())

    full_report_path = f"refused-emails/full-{random_name}.eml"
    s3.upload_email_from_bytesio(full_report_path, BytesIO(msg.as_bytes()), random_name)

    file_path = f"refused-emails/{random_name}.eml"
    s3.upload_email_from_bytesio(file_path, BytesIO(orig_msg.as_bytes()), random_name)

    refused_email = RefusedEmail.create(
        path=file_path, full_report_path=full_report_path, user_id=user.id
    )
    db.session.flush()

    fel.refused_email_id = refused_email.id
    db.session.commit()

    LOG.d("Create refused email %s", refused_email)

    refused_email_url = (
        URL + f"/dashboard/refused_email?highlight_fel_id=" + str(fel.id)
    )

    # inform user if this is the first bounced email
    if nb_bounced == 1:
        LOG.d(
            "Inform user %s about bounced email sent by %s to alias %s",
            user,
            contact.website_from,
            address,
        )
        send_email(
            # use user mail here as only user is authenticated to see the refused email
            user.email,
            f"Email from {contact.website_from} to {address} cannot be delivered to your inbox",
            render(
                "transactional/bounced-email.txt",
                name=user.name,
                alias=alias,
                website_from=contact.website_from,
                website_email=contact.website_email,
                disable_alias_link=disable_alias_link,
                refused_email_url=refused_email_url,
                mailbox_email=mailbox_email,
            ),
            render(
                "transactional/bounced-email.html",
                name=user.name,
                alias=alias,
                website_from=contact.website_from,
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
            contact.website_from,
        )
        alias.enabled = False
        db.session.commit()

        send_email(
            # use user mail here as only user is authenticated to see the refused email
            user.email,
            f"Alias {address} has been disabled due to second undelivered email from {contact.website_from}",
            render(
                "transactional/automatic-disable-alias.txt",
                name=user.name,
                alias=alias,
                website_from=contact.website_from,
                website_email=contact.website_email,
                refused_email_url=refused_email_url,
                mailbox_email=mailbox_email,
            ),
            render(
                "transactional/automatic-disable-alias.html",
                name=user.name,
                alias=alias,
                website_from=contact.website_from,
                website_email=contact.website_email,
                refused_email_url=refused_email_url,
                mailbox_email=mailbox_email,
            ),
            # cannot include bounce email as it can contain spammy text
            # bounced_email=msg,
        )


class MailHandler:
    async def handle_DATA(self, server, session, envelope):
        LOG.debug(">>> New message <<<")

        LOG.debug("Mail from %s", envelope.mail_from)
        LOG.debug("Rcpt to %s", envelope.rcpt_tos)
        message_data = envelope.content.decode("utf8", errors="replace")

        if POSTFIX_SUBMISSION_TLS:
            smtp = SMTP(POSTFIX_SERVER, 587)
            smtp.starttls()
        else:
            smtp = SMTP(POSTFIX_SERVER, 25)

        msg = Parser(policy=SMTPUTF8).parsestr(message_data)

        for rcpt_to in envelope.rcpt_tos:
            # Reply case
            # recipient starts with "reply+" or "ra+" (ra=reverse-alias) prefix
            if rcpt_to.startswith("reply+") or rcpt_to.startswith("ra+"):
                LOG.debug("Reply phase")
                app = new_app()

                with app.app_context():
                    return handle_reply(envelope, smtp, msg, rcpt_to)
            else:  # Forward case
                LOG.debug("Forward phase")
                app = new_app()

                with app.app_context():
                    return handle_forward(envelope, smtp, msg, rcpt_to)


if __name__ == "__main__":
    controller = Controller(MailHandler(), hostname="0.0.0.0", port=20381)

    controller.start()
    LOG.d("Start mail controller %s %s", controller.hostname, controller.port)

    while True:
        time.sleep(2)
