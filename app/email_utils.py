import os
from email.message import EmailMessage
from email.utils import make_msgid, formatdate
from smtplib import SMTP

import dkim
from jinja2 import Environment, FileSystemLoader

from app.config import (
    SUPPORT_EMAIL,
    ROOT_DIR,
    POSTFIX_SERVER,
    NOT_SEND_EMAIL,
    DKIM_SELECTOR,
    DKIM_PRIVATE_KEY,
    DKIM_HEADERS,
)
from app.log import LOG


def _render(template_name, **kwargs) -> str:
    templates_dir = os.path.join(ROOT_DIR, "templates", "emails")
    env = Environment(loader=FileSystemLoader(templates_dir))

    template = env.get_template(template_name)

    return template.render(**kwargs)


def send_welcome_email(email, name):
    send_email(
        email,
        f"{name}, welcome to SimpleLogin!",
        _render("welcome.txt", name=name),
        _render("welcome.html", name=name),
    )


def send_activation_email(email, name, activation_link):
    send_email(
        email,
        f"{name}, just one more step to join SimpleLogin",
        _render(
            "activation.txt", name=name, activation_link=activation_link, email=email
        ),
        _render(
            "activation.html", name=name, activation_link=activation_link, email=email
        ),
    )


def send_reset_password_email(email, name, reset_password_link):
    send_email(
        email,
        f"{name}, reset your password on SimpleLogin",
        _render(
            "reset-password.txt", name=name, reset_password_link=reset_password_link
        ),
        _render(
            "reset-password.html", name=name, reset_password_link=reset_password_link
        ),
    )


def send_change_email(new_email, current_email, name, link):
    send_email(
        new_email,
        f"{name}, confirm email update on SimpleLogin",
        _render(
            "change-email.txt",
            name=name,
            link=link,
            new_email=new_email,
            current_email=current_email,
        ),
        _render(
            "change-email.html",
            name=name,
            link=link,
            new_email=new_email,
            current_email=current_email,
        ),
    )


def send_new_app_email(email, name):
    send_email(
        email,
        f"{name}, any questions/feedbacks for SimpleLogin?",
        _render("new-app.txt", name=name),
        _render("new-app.html", name=name),
    )


def send_test_email_alias(email, name):
    send_email(
        email,
        f"{name}, this email is sent to {email}",
        _render("test-email.txt", name=name, alias=email),
        _render("test-email.html", name=name, alias=email),
    )


def send_email(to_email, subject, plaintext, html):
    if NOT_SEND_EMAIL:
        LOG.d(
            "send email with subject %s to %s, plaintext: %s",
            subject,
            to_email,
            plaintext,
        )
        return

    # host IP, setup via Docker network
    smtp = SMTP(POSTFIX_SERVER, 25)
    msg = EmailMessage()

    msg["Subject"] = subject
    msg["From"] = f"Son from SimpleLogin <{SUPPORT_EMAIL}>"
    msg["To"] = to_email

    msg.set_content(plaintext)
    if html is not None:
        msg.add_alternative(html, subtype="html")

    msg_id_header = make_msgid()
    LOG.d("message-id %s", msg_id_header)
    msg["Message-ID"] = msg_id_header

    date_header = formatdate()
    LOG.d("Date header: %s", date_header)
    msg["Date"] = date_header

    # add DKIM
    email_domain = SUPPORT_EMAIL[SUPPORT_EMAIL.find("@") + 1 :]
    add_dkim_signature(msg, email_domain)

    msg_raw = msg.as_string().encode()
    smtp.sendmail(SUPPORT_EMAIL, to_email, msg_raw)


def get_email_name(email_from):
    """parse email from header and return the name part
    First Last <ab@cd.com> -> First Last
    ab@cd.com -> ""
    """
    if "<" in email_from:
        return email_from[: email_from.find("<")].strip()

    return ""


def get_email_part(email_from):
    """parse email from header and return the email part
    First Last <ab@cd.com> -> ab@cd.com
    ab@cd.com -> ""
    """
    if "<" in email_from:
        return email_from[email_from.find("<") + 1 : email_from.find(">")].strip()

    return email_from


def add_dkim_signature(msg: EmailMessage, email_domain: str):
    if msg["DKIM-Signature"]:
        LOG.d("Remove DKIM-Signature %s", msg["DKIM-Signature"])
        del msg["DKIM-Signature"]

    # Specify headers in "byte" form
    # Generate message signature
    sig = dkim.sign(
        msg.as_string().encode(),
        DKIM_SELECTOR,
        email_domain.encode(),
        DKIM_PRIVATE_KEY.encode(),
        include_headers=DKIM_HEADERS,
    )
    sig = sig.decode()

    # remove linebreaks from sig
    sig = sig.replace("\n", " ").replace("\r", "")

    msg.add_header("DKIM-Signature", sig[len("DKIM-Signature: ") :])
