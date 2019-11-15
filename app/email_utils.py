# using SendGrid's Python Library
# https://github.com/sendgrid/sendgrid-python
from email.message import EmailMessage
from smtplib import SMTP

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

from app.config import SUPPORT_EMAIL, SENDGRID_API_KEY, NOT_SEND_EMAIL
from app.log import LOG


def send_by_sendgrid(to_email, subject, html_content, plain_content=None):
    # On local only print out email content
    if NOT_SEND_EMAIL:
        LOG.d(
            "send mail to %s, subject:%s, content:%s", to_email, subject, html_content
        )
        return

    if not plain_content:
        plain_content = subject

    message = Mail(
        from_email=SUPPORT_EMAIL,
        to_emails=to_email,
        subject=subject,
        html_content=html_content,
        plain_text_content=plain_content,
    )

    sg = SendGridAPIClient(SENDGRID_API_KEY)
    response = sg.send(message)
    LOG.d("sendgrid res:%s, email:%s", response.status_code, to_email)


def send_by_postfix(to_email, subject, content):
    # host IP, setup via Docker network
    smtp = SMTP("1.1.1.1", 25)
    msg = EmailMessage()

    msg["Subject"] = subject
    msg["From"] = SUPPORT_EMAIL
    msg["To"] = to_email
    msg.set_content(content)

    smtp.send_message(msg, from_addr=SUPPORT_EMAIL, to_addrs=[to_email])


def notify_admin(subject, html_content=""):
    send_by_postfix(SUPPORT_EMAIL, subject, html_content)
