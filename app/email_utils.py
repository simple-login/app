import os
from email.message import EmailMessage
from email.utils import make_msgid, formatdate
from smtplib import SMTP

from jinja2 import Environment, FileSystemLoader

from app.config import SUPPORT_EMAIL, ROOT_DIR
from app.log import LOG


def _render(template_name, **kwargs) -> str:
    templates_dir = os.path.join(ROOT_DIR, "templates", "emails")
    env = Environment(loader=FileSystemLoader(templates_dir))

    template = env.get_template(template_name)

    return template.render(**kwargs)


def send_welcome_email(email, name):
    send_by_postfix(
        email,
        f"{name}, welcome to SimpleLogin!",
        _render("welcome.txt", name=name),
        _render("welcome.html", name=name),
    )


def send_activation_email(email, name, activation_link):
    send_by_postfix(
        email,
        f"{name}, just one more step to join SimpleLogin",
        _render("activation.txt", name=name, activation_link=activation_link),
        _render("activation.html", name=name, activation_link=activation_link),
    )


def send_reset_password_email(email, name, reset_password_link):
    send_by_postfix(
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
    send_by_postfix(
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
    send_by_postfix(
        email,
        f"{name}, any questions/feedbacks for SimpleLogin?",
        _render("new-app.txt", name=name),
        _render("new-app.html", name=name),
    )


def send_test_email_alias(email, name):
    send_by_postfix(
        email,
        f"{name}, this email is sent to {email}",
        _render("test-email.txt", name=name, alias=email),
        _render("test-email.html", name=name, alias=email),
    )


def send_by_postfix(to_email, subject, plaintext, html):
    # host IP, setup via Docker network
    smtp = SMTP("1.1.1.1", 25)
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

    smtp.send_message(msg, from_addr=SUPPORT_EMAIL, to_addrs=[to_email])


def notify_admin(subject, html_content=""):
    send_by_postfix(SUPPORT_EMAIL, subject, html_content, html_content)
