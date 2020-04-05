import os
from email.header import decode_header
from email.message import Message
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid, formatdate, parseaddr, formataddr
from smtplib import SMTP
from typing import Optional

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
    POSTFIX_SUBMISSION_TLS,
)
from app.log import LOG
from app.models import Mailbox, User


def render(template_name, **kwargs) -> str:
    templates_dir = os.path.join(ROOT_DIR, "templates", "emails")
    env = Environment(loader=FileSystemLoader(templates_dir))

    template = env.get_template(template_name)

    return template.render(**kwargs)


def send_welcome_email(user):
    send_email(
        user.email,
        f"Welcome to SimpleLogin {user.name}",
        render("com/welcome.txt", name=user.name, user=user),
        render("com/welcome.html", name=user.name, user=user),
    )


def send_trial_end_soon_email(user):
    send_email(
        user.email,
        f"Your trial will end soon {user.name}",
        render("transactional/trial-end.txt", name=user.name, user=user),
        render("transactional/trial-end.html", name=user.name, user=user),
    )


def send_activation_email(email, name, activation_link):
    send_email(
        email,
        f"Just one more step to join SimpleLogin {name}",
        render(
            "transactional/activation.txt",
            name=name,
            activation_link=activation_link,
            email=email,
        ),
        render(
            "transactional/activation.html",
            name=name,
            activation_link=activation_link,
            email=email,
        ),
    )


def send_reset_password_email(email, name, reset_password_link):
    send_email(
        email,
        f"Reset your password on SimpleLogin",
        render(
            "transactional/reset-password.txt",
            name=name,
            reset_password_link=reset_password_link,
        ),
        render(
            "transactional/reset-password.html",
            name=name,
            reset_password_link=reset_password_link,
        ),
    )


def send_change_email(new_email, current_email, name, link):
    send_email(
        new_email,
        f"Confirm email update on SimpleLogin",
        render(
            "transactional/change-email.txt",
            name=name,
            link=link,
            new_email=new_email,
            current_email=current_email,
        ),
        render(
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
        render("com/new-app.txt", name=name),
        render("com/new-app.html", name=name),
    )


def send_test_email_alias(email, name):
    send_email(
        email,
        f"This email is sent to {email}",
        render("transactional/test-email.txt", name=name, alias=email),
        render("transactional/test-email.html", name=name, alias=email),
    )


def send_cannot_create_directory_alias(user, alias, directory):
    """when user cancels their subscription, they cannot create alias on the fly.
    If this happens, send them an email to notify
    """
    send_email(
        user.email,
        f"Alias {alias} cannot be created",
        render(
            "transactional/cannot-create-alias-directory.txt",
            name=user.name,
            alias=alias,
            directory=directory,
        ),
        render(
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
        render(
            "transactional/cannot-create-alias-domain.txt",
            name=user.name,
            alias=alias,
            domain=domain,
        ),
        render(
            "transactional/cannot-create-alias-domain.html",
            name=user.name,
            alias=alias,
            domain=domain,
        ),
    )


def send_email(
    to_email, subject, plaintext, html=None, bounced_email: Optional[Message] = None
):
    if NOT_SEND_EMAIL:
        LOG.d(
            "send email with subject %s to %s, plaintext: %s",
            subject,
            to_email,
            plaintext,
        )
        return

    LOG.d("send email to %s, subject %s", to_email, subject)

    if POSTFIX_SUBMISSION_TLS:
        smtp = SMTP(POSTFIX_SERVER, 587)
        smtp.starttls()
    else:
        smtp = SMTP(POSTFIX_SERVER, 25)

    if bounced_email:
        msg = MIMEMultipart("mixed")

        # add email main body
        body = MIMEMultipart("alternative")
        body.attach(MIMEText(plaintext, "text"))
        if html:
            body.attach(MIMEText(html, "html"))

        msg.attach(body)

        # add attachment
        rfcmessage = MIMEBase("message", "rfc822")
        rfcmessage.attach(bounced_email)
        msg.attach(rfcmessage)
    else:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(plaintext, "text"))
        if html:
            msg.attach(MIMEText(html, "html"))

    msg["Subject"] = subject
    msg["From"] = f"{SUPPORT_NAME} <{SUPPORT_EMAIL}>"
    msg["To"] = to_email

    msg_id_header = make_msgid()
    msg["Message-ID"] = msg_id_header

    date_header = formatdate()
    msg["Date"] = date_header

    # add DKIM
    email_domain = SUPPORT_EMAIL[SUPPORT_EMAIL.find("@") + 1 :]
    add_dkim_signature(msg, email_domain)

    msg_raw = msg.as_bytes()
    smtp.sendmail(SUPPORT_EMAIL, to_email, msg_raw)


def get_email_local_part(address):
    """
    Get the local part from email
    ab@cd.com -> ab
    """
    return address[: address.find("@")]


def get_email_domain_part(address):
    """
    Get the domain part from email
    ab@cd.com -> cd.com
    """
    return address[address.find("@") + 1 :]


def add_dkim_signature(msg: Message, email_domain: str):
    delete_header(msg, "DKIM-Signature")

    # Specify headers in "byte" form
    # Generate message signature
    sig = dkim.sign(
        msg.as_bytes(),
        DKIM_SELECTOR,
        email_domain.encode(),
        DKIM_PRIVATE_KEY.encode(),
        include_headers=DKIM_HEADERS,
    )
    sig = sig.decode()

    # remove linebreaks from sig
    sig = sig.replace("\n", " ").replace("\r", "")
    msg["DKIM-Signature"] = sig[len("DKIM-Signature: ") :]


def add_or_replace_header(msg: Message, header: str, value: str):
    """
    Remove all occurrences of `header` and add `header` with `value`.
    """
    delete_header(msg, header)
    msg[header] = value


def delete_header(msg: Message, header: str):
    """a header can appear several times in message."""
    # inspired from https://stackoverflow.com/a/47903323/1428034
    for i in reversed(range(len(msg._headers))):
        header_name = msg._headers[i][0].lower()
        if header_name == header.lower():
            del msg._headers[i]


def delete_all_headers_except(msg: Message, headers: [str]):
    headers = [h.lower() for h in headers]

    for i in reversed(range(len(msg._headers))):
        header_name = msg._headers[i][0].lower()
        if header_name not in headers:
            del msg._headers[i]


def email_belongs_to_alias_domains(address: str) -> bool:
    """return True if an email ends with one of the alias domains provided by SimpleLogin"""
    for domain in ALIAS_DOMAINS:
        if address.endswith("@" + domain):
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


def email_already_used(email: str) -> bool:
    """test if an email can be used when:
    - user signs up
    - add a new mailbox
    """
    if User.get_by(email=email):
        return True

    if Mailbox.get_by(email=email):
        return True

    return False


def mailbox_already_used(email: str, user) -> bool:
    if Mailbox.get_by(email=email):
        return True

    # support the case user wants to re-add their real email as mailbox
    # can happen when user changes their root email and wants to add this new email as mailbox
    if email == user.email:
        return False

    if User.get_by(email=email):
        return True

    return False


def get_orig_message_from_bounce(msg: Message) -> Message:
    """parse the original email from Bounce"""
    i = 0
    for part in msg.walk():
        i += 1

        # the original message is the 4th part
        # 1st part is the root part,  multipart/report
        # 2nd is text/plain, Postfix log
        # ...
        # 7th is original message
        if i == 7:
            return part


def get_orig_message_from_spamassassin_report(msg: Message) -> Message:
    """parse the original email from Spamassassin report"""
    i = 0
    for part in msg.walk():
        i += 1

        # the original message is the 4th part
        # 1st part is the root part,  multipart/report
        # 2nd is text/plain, SpamAssassin part
        # 3rd is the original message in message/rfc822 content type
        # 4th is original message
        if i == 4:
            return part


def get_addrs_from_header(msg: Message, header) -> [str]:
    """Get all addresses contained in `header`
    Used for To or CC header.
    """
    ret = []
    header_content = msg.get_all(header)
    if not header_content:
        return ret

    for addrs in header_content:
        for addr in addrs.split(","):
            ret.append(addr.strip())

    # do not return empty string
    return [r for r in ret if r]


def get_spam_info(msg: Message) -> (bool, str):
    """parse SpamAssassin header to detect whether a message is classified as spam.
    Return (is spam, spam status detail)
    The header format is
    ```X-Spam-Status: No, score=-0.1 required=5.0 tests=DKIM_SIGNED,DKIM_VALID,
  DKIM_VALID_AU,RCVD_IN_DNSWL_BLOCKED,RCVD_IN_MSPIKE_H2,SPF_PASS,
  URIBL_BLOCKED autolearn=unavailable autolearn_force=no version=3.4.2```
    """
    spamassassin_status = msg["X-Spam-Status"]
    if not spamassassin_status:
        return False, ""

    # yes or no
    spamassassin_answer = spamassassin_status[: spamassassin_status.find(",")]

    return spamassassin_answer.lower() == "yes", spamassassin_status


def parseaddr_unicode(addr) -> (str, str):
    """Like parseaddr but return name in unicode instead of in RFC 2047 format
    '=?UTF-8?B?TmjGoW4gTmd1eeG7hW4=?= <abcd@gmail.com>' -> ('Nhơn Nguyễn', "abcd@gmail.com")
    """
    name, email = parseaddr(addr)
    email = email.strip().lower()
    if name:
        name = name.strip()
        decoded_string, charset = decode_header(name)[0]
        if charset is not None:
            name = decoded_string.decode(charset)
        else:
            name = decoded_string

    return name, email
