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
from email.message import EmailMessage
from email.parser import Parser
from email.policy import SMTPUTF8
from smtplib import SMTP

from aiosmtpd.controller import Controller

from app.config import EMAIL_DOMAIN, POSTFIX_SERVER
from app.email_utils import notify_admin
from app.extensions import db
from app.log import LOG
from app.models import GenEmail, ForwardEmail, ForwardEmailLog
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
        smtp = SMTP(POSTFIX_SERVER, 25)
        msg = Parser(policy=SMTPUTF8).parsestr(message_data)

        if not envelope.rcpt_tos[0].startswith("reply+"):  # Forward case
            LOG.debug("Forward phase, add Reply-To header")
            app = create_app()

            with app.app_context():
                return self.handle_forward(envelope, smtp, msg)

        else:
            LOG.debug("Reply phase")
            app = create_app()

            with app.app_context():
                return self.handle_reply(envelope, smtp, msg)

    def handle_forward(self, envelope, smtp, msg: EmailMessage) -> str:
        """return *status_code message*"""
        alias = envelope.rcpt_tos[0]  # alias@SL

        gen_email = GenEmail.get_by(email=alias)
        if not gen_email:
            LOG.d("alias %s not exist")
            return "510 Email not exist"

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

        forward_log = ForwardEmailLog.create(forward_id=forward_email.id)

        if gen_email.enabled:
            # add custom header
            msg.add_header("X-SimpleLogin-Type", "Forward")

            # no need to modify reply-to as it is used in From: header directly
            # try:
            #     msg.add_header("Reply-To", forward_email.reply_email)
            # except ValueError:
            #     # the header exists already
            #     msg.replace_header("Reply-To", forward_email.reply_email)

            # remove reply-to header if present
            if msg["Reply-To"]:
                LOG.d("Delete reply-to header %s", msg["Reply-To"])
                del msg["Reply-To"]

            # change the from header so the sender comes from @simplelogin
            # so it can pass DMARC check
            from_header = f"Sender {website_email.replace('@', ' at ')} <{forward_email.reply_email}>"
            msg.replace_header("From", from_header)

            # modify subject to let user know the email is forwarded from SL
            original_subject = msg["Subject"]
            # msg.replace_header(
            #     "Subject",
            #     f"Forwarded by SimpleLogin. Subject: {original_subject}. From: {website_email}",
            # )

            LOG.d(
                "Forward mail from %s to %s, subject %s, mail_options %s, rcpt_options %s ",
                website_email,
                gen_email.user.email,
                original_subject,
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
            LOG.d("%s is disabled, do not forward", gen_email)
            forward_log.blocked = True

        db.session.commit()
        return "250 Message accepted for delivery"

    def handle_reply(self, envelope, smtp, msg: EmailMessage) -> str:
        reply_email = envelope.rcpt_tos[0]

        forward_email = ForwardEmail.get_by(reply_email=reply_email)
        alias = forward_email.gen_email.email

        notify_admin(f"Reply phase used by user: {forward_email.gen_email.user.email} ")

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

        ForwardEmailLog.create(forward_id=forward_email.id, is_reply=True)
        db.session.commit()

        return "250 Message accepted for delivery"


if __name__ == "__main__":
    controller = Controller(MailHandler(), hostname="0.0.0.0", port=20381)

    controller.start()
    LOG.d("Start mail controller %s %s", controller.hostname, controller.port)

    while True:
        time.sleep(10)
