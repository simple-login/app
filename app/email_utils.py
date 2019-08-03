# using SendGrid's Python Library
# https://github.com/sendgrid/sendgrid-python

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

from app.config import SUPPORT_EMAIL, SENDGRID_API_KEY, NOT_SEND_EMAIL
from app.log import LOG


def send(to_email, subject, html_content, plain_content=None):
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


def notify_admin(subject, html_content=""):
    send(
        SUPPORT_EMAIL,
        subject,
        f"""
        <html><body>
    {html_content}
    </body></html>""",
    )
