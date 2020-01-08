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

from aiosmtpd.controller import Controller

from app.config import EMAIL_DOMAIN, POSTFIX_SERVER, URL
from app.email_utils import (
    get_email_name,
    get_email_part,
    send_email,
    add_dkim_signature,
    get_email_domain_part,
    add_or_replace_header,
    delete_header,
)
from app.extensions import db
from app.log import LOG
from app.models import GenEmail, ForwardEmail, ForwardEmailLog, CustomDomain, Directory
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


class MailHandler:
    async def handle_DATA(self, server, session, envelope):
        LOG.debug(">>> New message <<<")

        LOG.debug("Mail from %s", envelope.mail_from)
        LOG.debug("Rcpt to %s", envelope.rcpt_tos)
        message_data = envelope.content.decode("utf8", errors="replace")

        # Only when debug
        # LOG.debug("Message data:\n")
        # LOG.debug(message_data)

        # host IP, setup via Docker network
        smtp = SMTP(POSTFIX_SERVER, 25)
        msg = Parser(policy=SMTPUTF8).parsestr(message_data)

        rcpt_to = envelope.rcpt_tos[0].lower()

        # Reply case
        # reply+ or ra+ (reverse-alias) prefix
        if rcpt_to.startswith("reply+") or rcpt_to.startswith("ra+"):
            LOG.debug("Reply phase")
            app = new_app()

            with app.app_context():
                return self.handle_reply(envelope, smtp, msg)
        else:  # Forward case
            LOG.debug("Forward phase")
            app = new_app()

            with app.app_context():
                return self.handle_forward(envelope, smtp, msg)

    def handle_forward(self, envelope, smtp: SMTP, msg: Message) -> str:
        """return *status_code message*"""
        alias = envelope.rcpt_tos[0].lower()  # alias@SL

        gen_email = GenEmail.get_by(email=alias)
        if not gen_email:
            LOG.d("alias %s not exist. Try to see if it can created on the fly", alias)

            # try to see if alias could be created on-the-fly
            on_the_fly = False

            # check if alias belongs to a directory, ie having directory/anything@EMAIL_DOMAIN format
            if alias.endswith(EMAIL_DOMAIN):
                if "/" in alias:
                    directory_name = alias[: alias.find("/")]
                    LOG.d("directory_name %s", directory_name)

                    directory = Directory.get_by(name=directory_name)
                    if directory:
                        LOG.d("create alias %s for directory %s", alias, directory)
                        on_the_fly = True

                        gen_email = GenEmail.create(
                            email=alias,
                            user_id=directory.user_id,
                            directory_id=directory.id,
                        )
                        db.session.commit()
            else:
                # check if alias is custom-domain alias and if the custom-domain has catch-all enabled
                alias_domain = get_email_domain_part(alias)
                custom_domain = CustomDomain.get_by(domain=alias_domain)
                if custom_domain and custom_domain.catch_all:
                    LOG.d("create alias %s for domain %s", alias, custom_domain)
                    on_the_fly = True

                    gen_email = GenEmail.create(
                        email=alias,
                        user_id=custom_domain.user_id,
                        custom_domain_id=custom_domain.id,
                        automatic_creation=True,
                    )
                    db.session.commit()

            if not on_the_fly:
                LOG.d("alias %s not exist, return 510", alias)
                return "510 Email not exist"

        user_email = gen_email.user.email

        website_email = get_email_part(msg["From"])

        forward_email = ForwardEmail.get_by(
            gen_email_id=gen_email.id, website_email=website_email
        )
        if not forward_email:
            LOG.debug(
                "create forward email for alias %s and website email %s",
                alias,
                website_email,
            )

            # generate a reply_email, make sure it is unique
            # not use while to avoid infinite loop
            for _ in range(1000):
                reply_email = f"reply+{random_string(30)}@{EMAIL_DOMAIN}"
                if not ForwardEmail.get_by(reply_email=reply_email):
                    break

            forward_email = ForwardEmail.create(
                gen_email_id=gen_email.id,
                website_email=website_email,
                website_from=msg["From"],
                reply_email=reply_email,
            )
            db.session.commit()

        forward_log = ForwardEmailLog.create(forward_id=forward_email.id)

        if gen_email.enabled:
            # add custom header
            add_or_replace_header(msg, "X-SimpleLogin-Type", "Forward")

            # remove reply-to header if present
            delete_header(msg, "Reply-To")

            # change the from header so the sender comes from @SL
            # so it can pass DMARC check
            # replace the email part in from: header
            from_header = (
                get_email_name(msg["From"])
                + " - "
                + website_email.replace("@", " at ")
                + f" <{forward_email.reply_email}>"
            )
            msg.replace_header("From", from_header)
            LOG.d("new from header:%s", from_header)

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
                user_email,
                envelope.mail_options,
                envelope.rcpt_options,
            )

            # smtp.send_message has UnicodeEncodeErroremail issue
            # encode message raw directly instead
            msg_raw = msg.as_string().encode()
            smtp.sendmail(
                forward_email.reply_email,
                user_email,
                msg_raw,
                envelope.mail_options,
                envelope.rcpt_options,
            )
        else:
            LOG.d("%s is disabled, do not forward", gen_email)
            forward_log.blocked = True

        db.session.commit()
        return "250 Message accepted for delivery"

    def handle_reply(self, envelope, smtp: SMTP, msg: Message) -> str:
        reply_email = envelope.rcpt_tos[0].lower()

        # reply_email must end with EMAIL_DOMAIN
        if not reply_email.endswith(EMAIL_DOMAIN):
            LOG.error(f"Reply email {reply_email} has wrong domain")
            return "550 wrong reply email"

        forward_email = ForwardEmail.get_by(reply_email=reply_email)
        alias: str = forward_email.gen_email.email

        # alias must end with EMAIL_DOMAIN or custom-domain
        alias_domain = alias[alias.find("@") + 1 :]
        if alias_domain != EMAIL_DOMAIN:
            if not CustomDomain.get_by(domain=alias_domain):
                return "550 alias unknown by SimpleLogin"

        user_email = forward_email.gen_email.user.email
        if envelope.mail_from.lower() != user_email.lower():
            LOG.error(
                f"Reply email can only be used by user email. Actual mail_from: %s. User email %s",
                envelope.mail_from,
                user_email,
            )

            send_email(
                envelope.mail_from,
                f"Your email ({envelope.mail_from}) is not allowed to send email to {reply_email}",
                "",
                "",
            )

            return "450 ignored"

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
        add_or_replace_header(
            msg, "List-Unsubscribe-Post", "List-Unsubscribe=One-Click"
        )

        LOG.d(
            "send email from %s to %s, mail_options:%s,rcpt_options:%s",
            alias,
            forward_email.website_email,
            envelope.mail_options,
            envelope.rcpt_options,
        )

        if alias_domain == EMAIL_DOMAIN:
            add_dkim_signature(msg, EMAIL_DOMAIN)
        # add DKIM-Signature for non-custom-domain alias
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


if __name__ == "__main__":
    controller = Controller(MailHandler(), hostname="0.0.0.0", port=20381)

    controller.start()
    LOG.d("Start mail controller %s %s", controller.hostname, controller.port)

    while True:
        time.sleep(2)
