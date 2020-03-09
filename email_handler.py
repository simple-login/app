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
from email.message import Message
from email.parser import Parser
from email.policy import SMTPUTF8
from smtplib import SMTP
from typing import Optional

from aiosmtpd.controller import Controller

from app.config import (
    EMAIL_DOMAIN,
    POSTFIX_SERVER,
    URL,
    ALIAS_DOMAINS,
    ADMIN_EMAIL,
    SUPPORT_EMAIL,
    POSTFIX_SUBMISSION_TLS,
)
from app.email_utils import (
    get_email_name,
    get_email_part,
    send_email,
    add_dkim_signature,
    get_email_domain_part,
    add_or_replace_header,
    delete_header,
    send_cannot_create_directory_alias,
    send_cannot_create_domain_alias,
    email_belongs_to_alias_domains,
    render,
)
from app.extensions import db
from app.log import LOG
from app.models import (
    GenEmail,
    ForwardEmail,
    ForwardEmailLog,
    CustomDomain,
    Directory,
    User,
    DeletedAlias,
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


def try_auto_create(alias: str) -> Optional[GenEmail]:
    """Try to auto-create the alias using directory or catch-all domain
    """
    gen_email = try_auto_create_catch_all_domain(alias)
    if not gen_email:
        gen_email = try_auto_create_directory(alias)

    return gen_email


def try_auto_create_directory(alias: str) -> Optional[GenEmail]:
    """
    Try to create an alias with directory
    """
    # check if alias belongs to a directory, ie having directory/anything@EMAIL_DOMAIN format
    if email_belongs_to_alias_domains(alias):
        # if there's no directory separator in the alias, no way to auto-create it
        if "/" not in alias and "+" not in alias and "#" not in alias:
            return None

        # alias contains one of the 3 special directory separator: "/", "+" or "#"
        if "/" in alias:
            sep = "/"
        elif "+" in alias:
            sep = "+"
        else:
            sep = "#"

        directory_name = alias[: alias.find(sep)]
        LOG.d("directory_name %s", directory_name)

        directory = Directory.get_by(name=directory_name)
        if not directory:
            return None

        dir_user: User = directory.user

        if not dir_user.can_create_new_alias():
            send_cannot_create_directory_alias(dir_user, alias, directory_name)
            return None

        # if alias has been deleted before, do not auto-create it
        if DeletedAlias.get_by(email=alias, user_id=directory.user_id):
            LOG.warning(
                "Alias %s was deleted before, cannot auto-create using directory %s, user %s",
                alias,
                directory_name,
                dir_user,
            )
            return None

        LOG.d("create alias %s for directory %s", alias, directory)

        gen_email = GenEmail.create(
            email=alias,
            user_id=directory.user_id,
            directory_id=directory.id,
            mailbox_id=dir_user.default_mailbox_id,
        )
        db.session.commit()
        return gen_email


def try_auto_create_catch_all_domain(alias: str) -> Optional[GenEmail]:
    """Try to create an alias with catch-all domain"""

    # try to create alias on-the-fly with custom-domain catch-all feature
    # check if alias is custom-domain alias and if the custom-domain has catch-all enabled
    alias_domain = get_email_domain_part(alias)
    custom_domain = CustomDomain.get_by(domain=alias_domain)

    if not custom_domain:
        return None

    # custom_domain exists
    if not custom_domain.catch_all:
        return None

    # custom_domain has catch-all enabled
    domain_user: User = custom_domain.user

    if not domain_user.can_create_new_alias():
        send_cannot_create_domain_alias(domain_user, alias, alias_domain)
        return None

    # if alias has been deleted before, do not auto-create it
    if DeletedAlias.get_by(email=alias, user_id=custom_domain.user_id):
        LOG.warning(
            "Alias %s was deleted before, cannot auto-create using domain catch-all %s, user %s",
            alias,
            custom_domain,
            domain_user,
        )
        return None

    LOG.d("create alias %s for domain %s", alias, custom_domain)

    gen_email = GenEmail.create(
        email=alias,
        user_id=custom_domain.user_id,
        custom_domain_id=custom_domain.id,
        automatic_creation=True,
        mailbox_id=domain_user.default_mailbox_id,
    )

    db.session.commit()
    return gen_email


def get_or_create_forward_email(
    website_from_header: str, gen_email: GenEmail
) -> ForwardEmail:
    """
    website_from_header can be the full-form email, i.e. "First Last <email@example.com>"
    """
    website_email = get_email_part(website_from_header)
    forward_email = ForwardEmail.get_by(
        gen_email_id=gen_email.id, website_email=website_email
    )
    if forward_email:
        # update the website_from if needed
        if forward_email.website_from != website_from_header:
            LOG.d("Update From header for %s", forward_email)
            forward_email.website_from = website_from_header
            db.session.commit()
    else:
        LOG.debug(
            "create forward email for alias %s and website email %s",
            gen_email,
            website_from_header,
        )

        # generate a reply_email, make sure it is unique
        # not use while loop to avoid infinite loop
        reply_email = f"reply+{random_string(30)}@{EMAIL_DOMAIN}"
        for _ in range(1000):
            if not ForwardEmail.get_by(reply_email=reply_email):
                # found!
                break
            reply_email = f"reply+{random_string(30)}@{EMAIL_DOMAIN}"

        forward_email = ForwardEmail.create(
            gen_email_id=gen_email.id,
            website_email=website_email,
            website_from=website_from_header,
            reply_email=reply_email,
        )
        db.session.commit()

    return forward_email


def should_append_alias(msg, alias):
    """whether an alias should be appened to TO header in message"""

    if msg["To"] and alias in msg["To"]:
        return False
    if msg["Cc"] and alias in msg["Cc"]:
        return False

    return True


def handle_forward(envelope, smtp: SMTP, msg: Message, rcpt_to: str) -> str:
    """return *status_code message*"""
    alias = rcpt_to.lower()  # alias@SL

    gen_email = GenEmail.get_by(email=alias)
    if not gen_email:
        LOG.d("alias %s not exist. Try to see if it can be created on the fly", alias)
        gen_email = try_auto_create(alias)
        if not gen_email:
            LOG.d("alias %s cannot be created on-the-fly, return 510", alias)
            return "510 Email not exist"

    mailbox_email = gen_email.mailbox_email()
    forward_email = get_or_create_forward_email(msg["From"], gen_email)
    forward_log = ForwardEmailLog.create(forward_id=forward_email.id)

    if gen_email.enabled:
        # add custom header
        add_or_replace_header(msg, "X-SimpleLogin-Type", "Forward")

        # remove reply-to header if present
        delete_header(msg, "Reply-To")

        # change the from header so the sender comes from @SL
        # so it can pass DMARC check
        # replace the email part in from: header
        website_from_header = msg["From"]
        website_email = get_email_part(website_from_header)
        from_header = (
            get_email_name(website_from_header)
            + ("" if get_email_name(website_from_header) == "" else " - ")
            + website_email.replace("@", " at ")
            + f" <{forward_email.reply_email}>"
        )
        msg.replace_header("From", from_header)
        LOG.d("new from header:%s", from_header)

        # append alias into the TO header if it's not present in To or CC
        if should_append_alias(msg, alias):
            LOG.d("append alias %s  to TO header %s", alias, msg["To"])
            if msg["To"]:
                to_header = msg["To"] + "," + alias
            else:
                to_header = alias

            msg.replace_header("To", to_header)

        # add List-Unsubscribe header
        unsubscribe_link = f"{URL}/dashboard/unsubscribe/{gen_email.id}"
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
            forward_email.reply_email,
            mailbox_email,
            msg_raw,
            envelope.mail_options,
            envelope.rcpt_options,
        )
    else:
        LOG.d("%s is disabled, do not forward", gen_email)
        forward_log.blocked = True

    db.session.commit()
    return "250 Message accepted for delivery"


def handle_reply(envelope, smtp: SMTP, msg: Message, rcpt_to: str) -> str:
    reply_email = rcpt_to.lower()

    # reply_email must end with EMAIL_DOMAIN
    if not reply_email.endswith(EMAIL_DOMAIN):
        LOG.warning(f"Reply email {reply_email} has wrong domain")
        return "550 wrong reply email"

    forward_email = ForwardEmail.get_by(reply_email=reply_email)
    if not forward_email:
        LOG.warning(f"No such forward-email with {reply_email} as reply-email")
        return "550 wrong reply email"

    alias: str = forward_email.gen_email.email
    alias_domain = alias[alias.find("@") + 1 :]

    # alias must end with one of the ALIAS_DOMAINS or custom-domain
    if not email_belongs_to_alias_domains(alias):
        if not CustomDomain.get_by(domain=alias_domain):
            return "550 alias unknown by SimpleLogin"

    gen_email = forward_email.gen_email
    user = gen_email.user
    mailbox_email = gen_email.mailbox_email()

    # bounce email initiated by Postfix
    # can happen in case emails cannot be delivered to user-email
    # in this case Postfix will try to send a bounce report to original sender, which is
    # the "reply email"
    if envelope.mail_from == "<>":
        LOG.error(
            "Bounce when sending to alias %s, user %s", alias, gen_email.user,
        )

        handle_bounce(
            alias, envelope, forward_email, gen_email, msg, smtp, user, mailbox_email
        )
        return "550 ignored"

    # only mailbox can send email to the reply-email
    if envelope.mail_from.lower() != mailbox_email.lower():
        LOG.warning(
            f"Reply email can only be used by user email. Actual mail_from: %s. msg from header: %s, User email %s. reply_email %s",
            envelope.mail_from,
            msg["From"],
            mailbox_email,
            reply_email,
        )

        user = gen_email.user
        send_email(
            mailbox_email,
            f"Reply from your alias {alias} only works from your mailbox",
            render(
                "transactional/reply-must-use-personal-email.txt",
                name=user.name,
                alias=alias,
                sender=envelope.mail_from,
                mailbox_email=mailbox_email,
            ),
            render(
                "transactional/reply-must-use-personal-email.html",
                name=user.name,
                alias=alias,
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
    msg.replace_header("From", alias)

    # some email providers like ProtonMail adds automatically the Reply-To field
    # make sure to delete it
    delete_header(msg, "Reply-To")

    msg.replace_header("To", forward_email.website_email)

    # add List-Unsubscribe header
    unsubscribe_link = f"{URL}/dashboard/unsubscribe/{forward_email.gen_email_id}"
    add_or_replace_header(msg, "List-Unsubscribe", f"<{unsubscribe_link}>")
    add_or_replace_header(msg, "List-Unsubscribe-Post", "List-Unsubscribe=One-Click")

    # Received-SPF is injected by postfix-policyd-spf-python can reveal user original email
    delete_header(msg, "Received-SPF")

    LOG.d(
        "send email from %s to %s, mail_options:%s,rcpt_options:%s",
        alias,
        forward_email.website_email,
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
        alias,
        forward_email.website_email,
        msg_raw,
        envelope.mail_options,
        envelope.rcpt_options,
    )

    ForwardEmailLog.create(forward_id=forward_email.id, is_reply=True)
    db.session.commit()

    return "250 Message accepted for delivery"


def handle_bounce(
    alias, envelope, forward_email, gen_email, msg, smtp, user, mailbox_email
):
    ForwardEmailLog.create(forward_id=forward_email.id, bounced=True)
    db.session.commit()

    nb_bounced = ForwardEmailLog.filter_by(
        forward_id=forward_email.id, bounced=True
    ).count()
    disable_alias_link = f"{URL}/dashboard/unsubscribe/{gen_email.id}"

    # inform user if this is the first bounced email
    if nb_bounced == 1:
        LOG.d(
            "Inform user %s about bounced email sent by %s to alias %s",
            user,
            forward_email.website_from,
            alias,
        )
        send_email(
            mailbox_email,
            f"Email from {forward_email.website_from} to {alias} cannot be delivered to your inbox",
            render(
                "transactional/bounced-email.txt",
                name=user.name,
                alias=alias,
                website_from=forward_email.website_from,
                website_email=forward_email.website_email,
                disable_alias_link=disable_alias_link,
            ),
            render(
                "transactional/bounced-email.html",
                name=user.name,
                alias=alias,
                website_from=forward_email.website_from,
                website_email=forward_email.website_email,
                disable_alias_link=disable_alias_link,
            ),
            bounced_email=msg,
        )
    # disable the alias the second time email is bounced
    elif nb_bounced >= 2:
        LOG.d(
            "Bounce happens again with alias %s from %s. Disable alias now ",
            alias,
            forward_email.website_from,
        )
        gen_email.enabled = False
        db.session.commit()

        send_email(
            mailbox_email,
            f"Alias {alias} has been disabled due to second undelivered email from {forward_email.website_from}",
            render(
                "transactional/automatic-disable-alias.txt",
                name=user.name,
                alias=alias,
                website_from=forward_email.website_from,
                website_email=forward_email.website_email,
            ),
            render(
                "transactional/automatic-disable-alias.html",
                name=user.name,
                alias=alias,
                website_from=forward_email.website_from,
                website_email=forward_email.website_email,
            ),
            bounced_email=msg,
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
