import os
from email.message import EmailMessage, Message
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
    ALIAS_DOMAINS,
    SUPPORT_NAME,
)
from app.log import LOG


def _render(template_name, **kwargs) -> str:
    templates_dir = os.path.join(ROOT_DIR, "templates", "emails")
    env = Environment(loader=FileSystemLoader(templates_dir))

    template = env.get_template(template_name)

    return template.render(**kwargs)


def send_welcome_email(user):
    send_email(
        user.email,
        f"Welcome to SimpleLogin {user.name}",
        _render("com/welcome.txt", name=user.name, user=user),
        _render("com/welcome.html", name=user.name, user=user),
    )


def send_trial_end_soon_email(user):
    send_email(
        user.email,
        f"Your trial will end soon {user.name}",
        _render("transactional/trial-end.txt", name=user.name, user=user),
        _render("transactional/trial-end.html", name=user.name, user=user),
    )


def send_activation_email(email, name, activation_link):
    send_email(
        email,
        f"Just one more step to join SimpleLogin {name}",
        _render(
            "transactional/activation.txt", name=name, activation_link=activation_link, email=email
        ),
        _render(
            "transactional/activation.html", name=name, activation_link=activation_link, email=email
        ),
    )


def send_reset_password_email(email, name, reset_password_link):
    send_email(
        email,
        f"Reset your password on SimpleLogin",
        _render(
            "transactional/reset-password.txt", name=name, reset_password_link=reset_password_link
        ),
        _render(
            "transactional/reset-password.html", name=name, reset_password_link=reset_password_link
        ),
    )


def send_change_email(new_email, current_email, name, link):
    send_email(
        new_email,
        f"Confirm email update on SimpleLogin",
        _render(
            "transactional/change-email.txt",
            name=name,
            link=link,
            new_email=new_email,
            current_email=current_email,
        ),
        _render(
            "transactional/change-email.html",
            name=name,
            link=link,
            new_email=new_email,
            current_email=current_email,
        ),
    )


def send_new_app_email(email, name):
    send_email(
        email,
        f"Any question/feedback for SimpleLogin {name}?",
        _render("com/new-app.txt", name=name),
        _render("com/new-app.html", name=name),
    )


def send_test_email_alias(email, name):
    send_email(
        email,
        f"This email is sent to {email}",
        _render("transactional/test-email.txt", name=name, alias=email),
        _render("transactional/test-email.html", name=name, alias=email),
    )


def send_cannot_create_directory_alias(user, alias, directory):
    """when user cancels their subscription, they cannot create alias on the fly.
    If this happens, send them an email to notify
    """
    send_email(
        user.email,
        f"Alias {alias} cannot be created",
        _render(
            "transactional/cannot-create-alias-directory.txt",
            name=user.name,
            alias=alias,
            directory=directory,
        ),
        _render(
            "transactional/cannot-create-alias-directory.html",
            name=user.name,
            alias=alias,
            directory=directory,
        ),
    )


def send_cannot_create_domain_alias(user, alias, domain):
    """when user cancels their subscription, they cannot create alias on the fly with custom domain.
    If this happens, send them an email to notify
    """
    send_email(
        user.email,
        f"Alias {alias} cannot be created",
        _render(
            "transactional/cannot-create-alias-domain.txt", name=user.name, alias=alias, domain=domain
        ),
        _render(
            "transactional/cannot-create-alias-domain.html",
            name=user.name,
            alias=alias,
            domain=domain,
        ),
    )


def send_reply_alias_must_use_personal_email(user, alias, sender):
    """
    The reply_email can be used only by user personal email.
    Notify user if it's used by someone else
    """
    send_email(
        user.email,
        f"Reply from your alias {alias} only works with your personal email",
        _render(
            "transactional/reply-must-use-personal-email.txt",
            name=user.name,
            alias=alias,
            sender=sender,
            user_email=user.email,
        ),
        _render(
            "transactional/reply-must-use-personal-email.html",
            name=user.name,
            alias=alias,
            sender=sender,
            user_email=user.email,
        ),
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
    msg["From"] = f"{SUPPORT_NAME} <{SUPPORT_EMAIL}>"
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


def get_email_local_part(email):
    """
    Get the local part from email
    ab@cd.com -> ab
    """
    return email[: email.find("@")]


def get_email_domain_part(email):
    """
    Get the domain part from email
    ab@cd.com -> cd.com
    """
    return email[email.find("@") + 1 :]


def add_dkim_signature(msg: Message, email_domain: str):
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


def add_or_replace_header(msg: Message, header: str, value: str):
    try:
        msg.add_header(header, value)
    except ValueError:
        # the header exists already
        msg.replace_header(header, value)


def delete_header(msg: Message, header: str):
    """a header can appear several times in message."""
    for h in msg._headers:
        if h[0].lower() == header.lower():
            msg._headers.remove(h)


def email_belongs_to_alias_domains(email: str) -> bool:
    """return True if an emails ends with one of the alias domains provided by SimpleLogin"""
    for domain in ALIAS_DOMAINS:
        if email.endswith("@" + domain):
            return True

    return False


def can_be_used_as_personal_email(email: str) -> bool:
    """return True if an email can be used as a personal email. Currently the only condition is email domain is not
    - one of ALIAS_DOMAINS
    - one of custom domains
    """
    domain = get_email_domain_part(email)
    if not domain:
        return False

    if domain in ALIAS_DOMAINS:
        return False

    from app.models import CustomDomain

    if CustomDomain.get_by(domain=domain, verified=True):
        return False

    return True
