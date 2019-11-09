"""
Handle the email *forward* and *reply*. phase. There are 3 actors:
- website: who sends emails to alias@sl.co address
- SL email handler (this script)
- user personal email: to be protected. Should never leak to website.

This script makes sure that in the forward phase, the email that is forwarded to user personal email has the following
envelope and header fields:
Envelope:
    mail from: srs@sl.co # managed by SRS
    rcpt to: @personal_email
Header:
    From: @website
    To: alias@sl.co # so user knows this email is sent to alias
    Reply-to: special@sl.co # magic HERE

And in the reply phase:
Envelope:
    mail from: srs@sl.co # managed by SRS
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
from email.parser import Parser
from email.policy import default
from smtplib import SMTP

from aiosmtpd.controller import Controller

from app.config import EMAIL_DOMAIN
from app.email_utils import notify_admin
from app.extensions import db
from app.log import LOG
from app.models import GenEmail, ForwardEmail
from app.utils import random_words
from server import create_app


def parse_srs_email(srs) -> str:
    """
    Parse srs0=8lgw=y6=outlook.com=abcd@mailsl.meo.ovh and return abcd@outlook.com
    """
    local_part = srs[: srs.find("@")]  # srs0=8lgw=y6=outlook.com=abcd
    local_email_part = local_part[local_part.rfind("=") + 1 :]  # abcd

    rest = local_part[: local_part.rfind("=")]  # srs0=8lgw=y6=outlook.com
    domain_email_part = rest[rest.rfind("=") + 1 :]  # outlook.com

    return f"{local_email_part}@{domain_email_part}"


class MailHandler:
    async def handle_RCPT(self, server, session, envelope, address, rcpt_options):
        if not address.endswith(EMAIL_DOMAIN):
            LOG.error(f"Not handle email  {address}")
            return "550 not relaying to that domain"

        envelope.rcpt_tos.append(address)

        return "250 OK"

    async def handle_DATA(self, server, session, envelope):
        LOG.debug(">>> New message <<<")

        LOG.debug("Mail from %s", envelope.mail_from)
        LOG.debug("Rcpt to %s", envelope.rcpt_tos)
        message_data = envelope.content.decode("utf8", errors="replace")

        # Only when debug
        # LOG.debug("Message data:\n")
        # LOG.debug(message_data)

        # host IP, setup via Docker network
        smtp = SMTP("1.1.1.1", 25)
        msg = Parser(policy=default).parsestr(message_data)

        if not envelope.rcpt_tos[0].startswith("reply+"):  # Forward case
            LOG.debug("Forward phase, add Reply-To header")
            alias = envelope.rcpt_tos[0]  # alias@SL

            app = create_app()

            with app.app_context():
                gen_email = GenEmail.get_by(email=alias)
                website_email = parse_srs_email(envelope.mail_from)

                forward_email = ForwardEmail.get_by(
                    gen_email_id=gen_email.id, website_email=website_email
                )
                if not forward_email:
                    LOG.debug(
                        "create forward email for alias %s and website email %s",
                        alias,
                        website_email,
                    )
                    # todo: make sure reply_email is unique
                    reply_email = f"reply+{random_words()}@{EMAIL_DOMAIN}"
                    forward_email = ForwardEmail.create(
                        gen_email_id=gen_email.id,
                        website_email=website_email,
                        reply_email=reply_email,
                    )
                    db.session.commit()

                # add custom header
                msg.add_header("X-SimpleLogin-Type", "Forward")
                msg.add_header("Reply-To", forward_email.reply_email)

                msg.replace_header("To", f"{alias} <{gen_email.user.email}>")

                LOG.d(
                    "Send mail from %s to %s, mail_options %s, rcpt_options %s ",
                    envelope.mail_from,
                    gen_email.user.email,
                    envelope.mail_options,
                    envelope.rcpt_options,
                )

                smtp.send_message(
                    msg,
                    from_addr=envelope.mail_from,
                    to_addrs=[gen_email.user.email],  # user personal email
                    mail_options=envelope.mail_options,
                    rcpt_options=envelope.rcpt_options,
                )
        else:
            LOG.debug("Reply phase")
            reply_email = envelope.rcpt_tos[0]

            app = create_app()

            with app.app_context():
                forward_email = ForwardEmail.get_by(reply_email=reply_email)

                alias = forward_email.gen_email.email

                notify_admin(
                    f"Reply phase used by user: {forward_email.gen_email.user.email} "
                )

                # email seems to come from alias
                msg.replace_header("From", alias)
                msg.replace_header("To", forward_email.website_email)

                LOG.d(
                    "send email from %s to %s, mail_options:%s,rcpt_options:%s",
                    alias,
                    forward_email.website_email,
                    envelope.mail_options,
                    envelope.rcpt_options,
                )

                smtp.send_message(
                    msg,
                    from_addr=alias,
                    to_addrs=[forward_email.website_email],
                    mail_options=envelope.mail_options,
                    rcpt_options=envelope.rcpt_options,
                )

        return "250 Message accepted for delivery"


if __name__ == "__main__":
    controller = Controller(MailHandler(), hostname="0.0.0.0", port=20381)

    controller.start()
    LOG.d("Start mail controller %s %s", controller.hostname, controller.port)

    while True:
        time.sleep(10)
