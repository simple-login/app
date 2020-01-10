import asyncio
import concurrent
from email.parser import Parser
from email.policy import SMTPUTF8
from smtplib import SMTP

from aiosmtpd.controller import Controller

from app.config import EMAIL_DOMAIN, URL
from app.email_utils import (
    get_email_domain_part,
    get_email_part,
    get_email_name,
    add_dkim_signature,
    send_email,
)
from app.extensions import db
from app.log import LOG
from app.models import GenEmail, CustomDomain, ForwardEmail, ForwardEmailLog
from app.utils import random_string
from email_handler import add_or_replace_header
from server import create_app

SMTP_SERVER = "localhost"
SMTP_PORT = 2410


def safe_flask_app():
    app = create_app()

    @app.teardown_appcontext
    def safe_session(_):
        db.session.remove()
        db.engine.dispose()

    return app


def handle_reply(client, envelope) -> str:
    """Keeping the handle_reply method from the previous version"""
    message_data = envelope.content.decode("utf8", errors="replace")
    msg = Parser(policy=SMTPUTF8).parsestr(message_data)
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

        return "550 ignored"

    # remove DKIM-Signature
    if msg["DKIM-Signature"]:
        LOG.d("Remove DKIM-Signature %s", msg["DKIM-Signature"])
        del msg["DKIM-Signature"]

    # email seems to come from alias
    msg.replace_header("From", alias)
    msg.replace_header("To", forward_email.website_email)

    # add List-Unsubscribe header
    unsubscribe_link = f"{URL}/dashboard/unsubscribe/{forward_email.gen_email_id}"
    add_or_replace_header(msg, "List-Unsubscribe", f"<{unsubscribe_link}>")
    add_or_replace_header(msg, "List-Unsubscribe-Post", "List-Unsubscribe=One-Click")

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
    client.sendmail(
        alias,
        forward_email.website_email,
        msg_raw,
        envelope.mail_options,
        envelope.rcpt_options,
    )

    ForwardEmailLog.create(forward_id=forward_email.id, is_reply=True)
    db.session.commit()

    return "250 Message accepted for delivery"


def handle_forward(client: SMTP, envelope) -> str:
    """Keeping the handle_forward method from the previous version"""
    alias = envelope.rcpt_tos[0].lower()  # alias@SL
    message_data = envelope.content.decode("utf8", errors="replace")
    msg = Parser(policy=SMTPUTF8).parsestr(message_data)
    gen_email = GenEmail.get_by(email=alias)
    if not gen_email:
        LOG.d("alias %s not exist")

        # check if alias is custom-domain alias and if the custom-domain has catch-all enabled
        alias_domain = get_email_domain_part(alias)
        custom_domain = CustomDomain.get_by(domain=alias_domain)
        if custom_domain and custom_domain.catch_all:
            LOG.d("create alias %s for domain %s", alias, custom_domain)

            gen_email = GenEmail.create(
                email=alias,
                user_id=custom_domain.user_id,
                custom_domain_id=custom_domain.id,
                automatic_creation=True,
            )
            db.session.commit()
        else:
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
        if msg["Reply-To"]:
            LOG.d("Delete reply-to header %s", msg["Reply-To"])
            del msg["Reply-To"]

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
        client.sendmail(
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


def processing_data(envelope):
    app = (
        safe_flask_app()
    )  # TODO: This will create an `app` instance on EVERY email sending. Consider to move it into the `amain` function
    client = SMTP(SMTP_SERVER, SMTP_PORT)
    rcpt_to = envelope.rcpt_tos[0].lower()

    with app.app_context():
        if rcpt_to.startswith("reply+") or rcpt_to.startswith("ra+"):
            return handle_reply(client, envelope)
        return handle_forward(client, envelope)


class AMailHandler:
    async def handle_DATA(self, server, session, envelope):
        event_loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            # Here we throw the blocking function (including sendmail, talk to db, ...)
            # into a thread pool and return the result after it finished
            return await event_loop.run_in_executor(pool, processing_data, envelope)


class BlockingMailHandler:
    async def handle_DATA(self, server, session, envelope):
        return processing_data(envelope)


async def amain():
    """ Async main function, it handles incoming SMTP connections"""
    controller = Controller(AMailHandler(), hostname="0.0.0.0", port=8025)
    controller.start()


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(amain())

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        LOG.debug("Stopping the app")
        loop.stop()
