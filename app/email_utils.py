import base64
import email
import enum
import os
import quopri
import random
import re
from email.header import decode_header
from email.message import Message
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid, formatdate, parseaddr
from smtplib import SMTP

import arrow
import dkim
from jinja2 import Environment, FileSystemLoader
from validate_email import validate_email

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
    MAX_NB_EMAIL_FREE_PLAN,
    DISPOSABLE_EMAIL_DOMAINS,
    MAX_ALERT_24H,
    POSTFIX_PORT,
    SENDER,
    URL,
    LANDING_PAGE_URL,
    EMAIL_DOMAIN,
    ALERT_DIRECTORY_DISABLED_ALIAS_CREATION,
)
from app.dns_utils import get_mx_domains
from app.extensions import db
from app.log import LOG
from app.models import (
    Mailbox,
    User,
    SentAlert,
    CustomDomain,
    SLDomain,
    Contact,
    Alias,
    EmailLog,
)
from app.utils import (
    random_string,
    convert_to_id,
    convert_to_alphanumeric,
    sanitize_email,
)


def render(template_name, **kwargs) -> str:
    templates_dir = os.path.join(ROOT_DIR, "templates", "emails")
    env = Environment(loader=FileSystemLoader(templates_dir))

    template = env.get_template(template_name)

    return template.render(
        MAX_NB_EMAIL_FREE_PLAN=MAX_NB_EMAIL_FREE_PLAN,
        URL=URL,
        LANDING_PAGE_URL=LANDING_PAGE_URL,
        **kwargs,
    )


def send_welcome_email(user):
    to_email, unsubscribe_link, via_email = user.get_communication_email()
    if not to_email:
        return

    # whether this email is sent to an alias
    alias = to_email if to_email != user.email else None

    send_email(
        to_email,
        f"Welcome to SimpleLogin",
        render("com/welcome.txt", user=user, alias=alias),
        render("com/welcome.html", user=user, alias=alias),
        unsubscribe_link,
        via_email,
    )


def send_trial_end_soon_email(user):
    send_email(
        user.email,
        f"Your trial will end soon",
        render("transactional/trial-end.txt", user=user),
        render("transactional/trial-end.html", user=user),
    )


def send_activation_email(email, activation_link):
    send_email(
        email,
        f"Just one more step to join SimpleLogin",
        render(
            "transactional/activation.txt",
            activation_link=activation_link,
            email=email,
        ),
        render(
            "transactional/activation.html",
            activation_link=activation_link,
            email=email,
        ),
    )


def send_reset_password_email(email, reset_password_link):
    send_email(
        email,
        "Reset your password on SimpleLogin",
        render(
            "transactional/reset-password.txt",
            reset_password_link=reset_password_link,
        ),
        render(
            "transactional/reset-password.html",
            reset_password_link=reset_password_link,
        ),
    )


def send_change_email(new_email, current_email, link):
    send_email(
        new_email,
        "Confirm email update on SimpleLogin",
        render(
            "transactional/change-email.txt",
            link=link,
            new_email=new_email,
            current_email=current_email,
        ),
        render(
            "transactional/change-email.html",
            link=link,
            new_email=new_email,
            current_email=current_email,
        ),
    )


def send_test_email_alias(email, name):
    send_email(
        email,
        f"This email is sent to {email}",
        render("transactional/test-email.txt", name=name, alias=email),
        render("transactional/test-email.html", name=name, alias=email),
    )


def send_cannot_create_directory_alias(user, alias_address, directory_name):
    """when user cancels their subscription, they cannot create alias on the fly.
    If this happens, send them an email to notify
    """
    send_email(
        user.email,
        f"Alias {alias_address} cannot be created",
        render(
            "transactional/cannot-create-alias-directory.txt",
            alias=alias_address,
            directory=directory_name,
        ),
        render(
            "transactional/cannot-create-alias-directory.html",
            alias=alias_address,
            directory=directory_name,
        ),
    )


def send_cannot_create_directory_alias_disabled(user, alias_address, directory_name):
    """when the directory is disabled, new alias can't be created on-the-fly.
    Send user an email to notify of an attempt
    """
    send_email_with_rate_control(
        user,
        ALERT_DIRECTORY_DISABLED_ALIAS_CREATION,
        user.email,
        f"Alias {alias_address} cannot be created",
        render(
            "transactional/cannot-create-alias-directory-disabled.txt",
            alias=alias_address,
            directory=directory_name,
        ),
        render(
            "transactional/cannot-create-alias-directory-disabled.html",
            alias=alias_address,
            directory=directory_name,
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
            alias=alias,
            domain=domain,
        ),
        render(
            "transactional/cannot-create-alias-domain.html",
            alias=alias,
            domain=domain,
        ),
    )


def send_email(
    to_email,
    subject,
    plaintext,
    html=None,
    unsubscribe_link=None,
    unsubscribe_via_email=False,
):
    if NOT_SEND_EMAIL:
        LOG.d(
            "send email with subject '%s' to '%s', plaintext: %s",
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
        smtp = SMTP(POSTFIX_SERVER, POSTFIX_PORT or 25)

    msg = MIMEMultipart("alternative")
    msg.attach(MIMEText(plaintext))

    if not html:
        LOG.d("Use plaintext as html")
        html = plaintext.replace("\n", "<br>")
    msg.attach(MIMEText(html, "html"))

    msg["Subject"] = subject
    msg["From"] = f"{SUPPORT_NAME} <{SUPPORT_EMAIL}>"
    msg["To"] = to_email

    msg_id_header = make_msgid()
    msg["Message-ID"] = msg_id_header

    date_header = formatdate()
    msg["Date"] = date_header

    if unsubscribe_link:
        add_or_replace_header(msg, "List-Unsubscribe", f"<{unsubscribe_link}>")
        if not unsubscribe_via_email:
            add_or_replace_header(
                msg, "List-Unsubscribe-Post", "List-Unsubscribe=One-Click"
            )

    # add DKIM
    email_domain = SUPPORT_EMAIL[SUPPORT_EMAIL.find("@") + 1 :]
    add_dkim_signature(msg, email_domain)

    msg_raw = to_bytes(msg)
    if SENDER:
        smtp.sendmail(SENDER, to_email, msg_raw)
    else:
        smtp.sendmail(SUPPORT_EMAIL, to_email, msg_raw)


def send_email_with_rate_control(
    user: User,
    alert_type: str,
    to_email: str,
    subject,
    plaintext,
    html=None,
    max_nb_alert=MAX_ALERT_24H,
    nb_day=1,
) -> bool:
    """Same as send_email with rate control over alert_type.
    Make sure no more than `max_nb_alert` emails are sent over the period of `nb_day` days

    Return true if the email is sent, otherwise False
    """
    to_email = sanitize_email(to_email)
    min_dt = arrow.now().shift(days=-1 * nb_day)
    nb_alert = (
        SentAlert.query.filter_by(alert_type=alert_type, to_email=to_email)
        .filter(SentAlert.created_at > min_dt)
        .count()
    )

    if nb_alert >= max_nb_alert:
        LOG.warning(
            "%s emails were sent to %s in the last %s days, alert type %s",
            nb_alert,
            to_email,
            nb_day,
            alert_type,
        )
        return False

    SentAlert.create(user_id=user.id, alert_type=alert_type, to_email=to_email)
    db.session.commit()
    send_email(to_email, subject, plaintext, html)
    return True


def send_email_at_most_times(
    user: User,
    alert_type: str,
    to_email: str,
    subject,
    plaintext,
    html=None,
    max_times=1,
) -> bool:
    """Same as send_email with rate control over alert_type.
    Sent at most `max_times`
    This is used to inform users about a warning.

    Return true if the email is sent, otherwise False
    """
    to_email = sanitize_email(to_email)
    nb_alert = SentAlert.query.filter_by(
        alert_type=alert_type, to_email=to_email
    ).count()

    if nb_alert >= max_times:
        LOG.warning(
            "%s emails were sent to %s alert type %s",
            nb_alert,
            to_email,
            alert_type,
        )
        return False

    SentAlert.create(user_id=user.id, alert_type=alert_type, to_email=to_email)
    db.session.commit()
    send_email(to_email, subject, plaintext, html)
    return True


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
    address = sanitize_email(address)
    return address[address.find("@") + 1 :]


def add_dkim_signature(msg: Message, email_domain: str):
    delete_header(msg, "DKIM-Signature")

    # Specify headers in "byte" form
    # Generate message signature
    sig = dkim.sign(
        to_bytes(msg),
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


def can_create_directory_for_address(address: str) -> bool:
    """return True if an email ends with one of the alias domains provided by SimpleLogin"""
    # not allow creating directory with premium domain
    for domain in ALIAS_DOMAINS:
        if address.endswith("@" + domain):
            return True

    return False


def is_valid_alias_address_domain(address) -> bool:
    """Return whether an address domain might a domain handled by SimpleLogin"""
    domain = get_email_domain_part(address)
    if SLDomain.get_by(domain=domain):
        return True

    if CustomDomain.get_by(domain=domain, verified=True):
        return True

    return False


def email_can_be_used_as_mailbox(email: str) -> bool:
    """Return True if an email can be used as a personal email.
    Use the email domain as criteria. A domain can be used if it is not:
    - one of ALIAS_DOMAINS
    - one of PREMIUM_ALIAS_DOMAINS
    - one of custom domains
    - a disposable domain
    """
    domain = get_email_domain_part(email)
    if not domain:
        return False

    if SLDomain.get_by(domain=domain):
        return False

    from app.models import CustomDomain

    if CustomDomain.get_by(domain=domain, verified=True):
        LOG.d("domain %s is a SimpleLogin custom domain", domain)
        return False

    if is_disposable_domain(domain):
        LOG.d("Domain %s is disposable", domain)
        return False

    # check if email MX domain is disposable
    mx_domains = get_mx_domain_list(domain)

    # if no MX record, email is not valid
    if not mx_domains:
        LOG.d("No MX record for domain %s", domain)
        return False

    for mx_domain in mx_domains:
        if is_disposable_domain(mx_domain):
            LOG.d("MX Domain %s %s is disposable", mx_domain, domain)
            return False

    return True


def is_disposable_domain(domain):
    for d in DISPOSABLE_EMAIL_DOMAINS:
        if domain == d:
            return True
        # subdomain
        if domain.endswith("." + d):
            return True

    return False


def get_mx_domain_list(domain) -> [str]:
    """return list of MX domains for a given email.
    domain name ends *without* a dot (".") at the end.
    """
    priority_domains = get_mx_domains(domain)

    return [d[:-1] for _, d in priority_domains]


def personal_email_already_used(email: str) -> bool:
    """test if an email can be used as user email"""
    if User.get_by(email=email):
        return True

    return False


def mailbox_already_used(email: str, user) -> bool:
    if Mailbox.get_by(email=email, user_id=user.id):
        return True

    # support the case user wants to re-add their real email as mailbox
    # can happen when user changes their root email and wants to add this new email as mailbox
    if email == user.email:
        return False

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


def get_header_from_bounce(msg: Message, header: str) -> str:
    """using regex to get header value from bounce message
    get_orig_message_from_bounce is better. This should be the last option
    """
    msg_str = str(msg)
    exp = re.compile(f"{header}.*\n")
    r = re.search(exp, msg_str)
    if r:
        # substr should be something like 'HEADER: 1234'
        substr = msg_str[r.start() : r.end()].strip()
        parts = substr.split(":")
        return parts[1].strip()

    return None


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


def get_spam_info(msg: Message, max_score=None) -> (bool, str):
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

    return get_spam_from_header(spamassassin_status, max_score=max_score)


def get_spam_from_header(spam_status_header, max_score=None) -> (bool, str):
    """get spam info from X-Spam-Status header
      Return (is spam, spam status detail).
      The spam_status_header has the following format
      ```No, score=-0.1 required=5.0 tests=DKIM_SIGNED,DKIM_VALID,
    DKIM_VALID_AU,RCVD_IN_DNSWL_BLOCKED,RCVD_IN_MSPIKE_H2,SPF_PASS,
    URIBL_BLOCKED autolearn=unavailable autolearn_force=no version=3.4.2```
    """
    # yes or no
    spamassassin_answer = spam_status_header[: spam_status_header.find(",")]

    if max_score:
        # spam score
        # get the score section "score=-0.1"
        score_section = (
            spam_status_header[spam_status_header.find(",") + 1 :].strip().split(" ")[0]
        )
        score = float(score_section[len("score=") :])
        if score >= max_score:
            LOG.warning("Spam score %s exceeds %s", score, max_score)
            return True, spam_status_header

    return spamassassin_answer.lower() == "yes", spam_status_header


def get_header_unicode(header: str):
    decoded_string, charset = decode_header(header)[0]
    if charset is not None:
        try:
            return decoded_string.decode(charset)
        except UnicodeDecodeError:
            LOG.warning("Cannot decode header %s", header)
        except LookupError:  # charset is unknown
            LOG.warning("Cannot decode %s with %s, use utf-8", decoded_string, charset)
            return decoded_string.decode("utf-8")

    return header


def parseaddr_unicode(addr) -> (str, str):
    """Like parseaddr() but return name in unicode instead of in RFC 2047 format
    Should be used instead of parseaddr()
    '=?UTF-8?B?TmjGoW4gTmd1eeG7hW4=?= <abcd@gmail.com>' -> ('Nhơn Nguyễn', "abcd@gmail.com")
    """
    # sometimes linebreaks are present in addr
    addr = addr.replace("\n", "").strip()
    name, email = parseaddr(addr)
    # email can have whitespace so we can't remove whitespace here
    email = email.strip().lower()
    if name:
        name = name.strip()
        decoded_string, charset = decode_header(name)[0]
        if charset is not None:
            try:
                name = decoded_string.decode(charset)
            except UnicodeDecodeError:
                LOG.warning("Cannot decode addr name %s", name)
                name = ""
            except LookupError:  # charset is unknown
                LOG.warning(
                    "Cannot decode %s with %s, use utf-8", decoded_string, charset
                )
                name = decoded_string.decode("utf-8")
        else:
            name = decoded_string

    if type(name) == bytes:
        name = name.decode()
    return name, email


def copy(msg: Message) -> Message:
    """return a copy of message"""
    try:
        # prefer the unicode way
        return email.message_from_string(msg.as_string())
    except (UnicodeEncodeError, KeyError, LookupError):
        LOG.warning("as_string() fails, try to_bytes")
        return email.message_from_bytes(to_bytes(msg))


def to_bytes(msg: Message):
    """replace Message.as_bytes() method by trying different policies"""
    try:
        return msg.as_bytes()
    except UnicodeEncodeError:
        LOG.warning("as_bytes fails with default policy, try SMTP policy")
        try:
            return msg.as_bytes(policy=email.policy.SMTP)
        except UnicodeEncodeError:
            LOG.warning("as_bytes fails with SMTP policy, try SMTPUTF8 policy")
            try:
                return msg.as_bytes(policy=email.policy.SMTPUTF8)
            except UnicodeEncodeError:
                LOG.warning(
                    "as_bytes fails with SMTPUTF8 policy, try converting to string"
                )
                return msg.as_string().encode()


def should_add_dkim_signature(domain: str) -> bool:
    if SLDomain.get_by(domain=domain):
        return True

    custom_domain: CustomDomain = CustomDomain.get_by(domain=domain)
    if custom_domain.dkim_verified:
        return True

    return False


def is_valid_email(email_address: str) -> bool:
    """Used to check whether an email address is valid"""
    return validate_email(
        email_address=email_address, check_mx=False, use_blacklist=False
    )


class EmailEncoding(enum.Enum):
    BASE64 = "base64"
    QUOTED = "quoted-printable"
    NO = "no-encoding"


def get_encoding(msg: Message) -> EmailEncoding:
    """
    Return the message encoding, possible values:
    - quoted-printable
    - base64
    - 7bit: default if unknown or empty
    """
    cte = str(msg.get("content-transfer-encoding", "")).lower()
    if cte in ("", "7bit", "8bit", "binary"):
        return EmailEncoding.NO

    if cte == "base64":
        return EmailEncoding.BASE64

    if cte == "quoted-printable":
        return EmailEncoding.QUOTED

    LOG.exception("Unknown encoding %s", cte)

    return EmailEncoding.NO


def encode_text(text: str, encoding: EmailEncoding = EmailEncoding.NO) -> str:
    if encoding == EmailEncoding.QUOTED:
        encoded = quopri.encodestring(text.encode("utf-8"))
        return str(encoded, "utf-8")
    elif encoding == EmailEncoding.BASE64:
        encoded = base64.b64encode(text.encode("utf-8"))
        return str(encoded, "utf-8")
    else:  # 7bit - no encoding
        return text


def decode_text(text: str, encoding: EmailEncoding = EmailEncoding.NO) -> str:
    if encoding == EmailEncoding.QUOTED:
        decoded = quopri.decodestring(text.encode("utf-8"))
        return decoded.decode(errors="ignore")
    elif encoding == EmailEncoding.BASE64:
        decoded = base64.b64decode(text.encode("utf-8"))
        return decoded.decode(errors="ignore")
    else:  # 7bit - no encoding
        return text


def add_header(msg: Message, text_header, html_header) -> Message:
    content_type = msg.get_content_type().lower()
    if content_type == "text/plain":
        encoding = get_encoding(msg)
        payload = msg.get_payload()
        if type(payload) is str:
            clone_msg = copy(msg)
            new_payload = f"""{text_header}
---
{decode_text(payload, encoding)}"""
            clone_msg.set_payload(encode_text(new_payload, encoding))
            return clone_msg
    elif content_type == "text/html":
        encoding = get_encoding(msg)
        payload = msg.get_payload()
        if type(payload) is str:
            new_payload = f"""<table width="100%" style="width: 100%; -premailer-width: 100%; -premailer-cellpadding: 0;
  -premailer-cellspacing: 0; margin: 0; padding: 0;">
    <tr>
        <td style="border-bottom:1px dashed #5675E2; padding: 10px 0px">{html_header}</td>
    </tr>
    <tr>
        <td>
        {decode_text(payload, encoding)}
        </td>
    </tr>
</table>
"""

            clone_msg = copy(msg)
            clone_msg.set_payload(encode_text(new_payload, encoding))
            return clone_msg
    elif content_type in ("multipart/alternative", "multipart/related"):
        new_parts = []
        for part in msg.get_payload():
            new_parts.append(add_header(part, text_header, html_header))
        clone_msg = copy(msg)
        clone_msg.set_payload(new_parts)
        return clone_msg

    elif content_type in ("multipart/mixed", "multipart/signed"):
        new_parts = []
        parts = list(msg.get_payload())
        LOG.d("only add header for the first part for %s", content_type)
        for ix, part in enumerate(parts):
            if ix == 0:
                new_parts.append(add_header(part, text_header, html_header))
            else:
                new_parts.append(part)

        clone_msg = copy(msg)
        clone_msg.set_payload(new_parts)
        return clone_msg

    LOG.d("No header added for %s", content_type)
    return msg


def replace(msg: Message, old, new) -> Message:
    content_type = msg.get_content_type()

    if (
        content_type.startswith("image/")
        or content_type.startswith("video/")
        or content_type.startswith("audio/")
        or content_type == "multipart/signed"
        or content_type.startswith("application/")
        or content_type == "text/calendar"
        or content_type == "text/directory"
        or content_type == "text/csv"
    ):
        LOG.d("not applicable for %s", content_type)
        return msg

    if content_type in ("text/plain", "text/html"):
        encoding = get_encoding(msg)
        payload = msg.get_payload()
        if type(payload) is str:
            clone_msg = copy(msg)
            new_payload = payload.replace(
                encode_text(old, encoding), encode_text(new, encoding)
            )
            clone_msg.set_payload(new_payload)
            return clone_msg

    elif content_type in (
        "multipart/alternative",
        "multipart/related",
        "multipart/mixed",
    ):
        new_parts = []
        for part in msg.get_payload():
            new_parts.append(replace(part, old, new))
        clone_msg = copy(msg)
        clone_msg.set_payload(new_parts)
        return clone_msg

    LOG.exception("Cannot replace text for %s", msg.get_content_type())
    return msg


def generate_reply_email(contact_email: str, user: User) -> str:
    """
    generate a reply_email (aka reverse-alias), make sure it isn't used by any contact
    """
    # shorten email to avoid exceeding the 64 characters
    # from https://tools.ietf.org/html/rfc5321#section-4.5.3
    # "The maximum total length of a user name or other local-part is 64
    #    octets."

    include_sender_in_reverse_alias = False

    # user has chosen an option explicitly
    if user.include_sender_in_reverse_alias is not None:
        include_sender_in_reverse_alias = user.include_sender_in_reverse_alias

    if include_sender_in_reverse_alias and contact_email:
        # control char: 4 chars (ra+, +)
        # random suffix: max 10 chars
        # maximum: 64

        # make sure contact_email can be ascii-encoded
        contact_email = convert_to_id(contact_email)
        contact_email = sanitize_email(contact_email)
        contact_email = contact_email[:45]
        contact_email = contact_email.replace("@", ".at.")
        contact_email = convert_to_alphanumeric(contact_email)

    # not use while to avoid infinite loop
    for _ in range(1000):
        if include_sender_in_reverse_alias and contact_email:
            random_length = random.randint(5, 10)
            reply_email = (
                f"ra+{contact_email}+{random_string(random_length)}@{EMAIL_DOMAIN}"
            )
        else:
            random_length = random.randint(20, 50)
            reply_email = f"ra+{random_string(random_length)}@{EMAIL_DOMAIN}"

        if not Contact.get_by(reply_email=reply_email):
            return reply_email

    raise Exception("Cannot generate reply email")


def is_reply_email(address: str) -> bool:
    return address.startswith("reply+") or address.startswith("ra+")


# allow also + and @ that are present in a reply address
_ALLOWED_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.+@"


def normalize_reply_email(reply_email: str) -> str:
    """Handle the case where reply email contains *strange* char that was wrongly generated in the past"""
    if not reply_email.isascii():
        reply_email = convert_to_id(reply_email)

    ret = []
    # drop all control characters like shift, separator, etc
    for c in reply_email:
        if c not in _ALLOWED_CHARS:
            ret.append("_")
        else:
            ret.append(c)

    return "".join(ret)


def should_disable(alias: Alias) -> bool:
    """Disable an alias if it has more than 5 bounces in the last 24h"""
    # Bypass the bounce rule
    if alias.cannot_be_disabled:
        LOG.warning("%s cannot be disabled", alias)
        return False

    yesterday = arrow.now().shift(days=-1)
    nb_bounced_last_24h = (
        db.session.query(EmailLog)
        .join(Contact, EmailLog.contact_id == Contact.id)
        .filter(
            EmailLog.bounced.is_(True),
            EmailLog.is_reply.is_(False),
            EmailLog.created_at > yesterday,
        )
        .filter(Contact.alias_id == alias.id)
        .count()
    )
    if nb_bounced_last_24h > 5:
        return True
    return False


def parse_email_log_id_from_bounce(email_address: str) -> int:
    return int(email_address[email_address.find("+") : email_address.rfind("+")])
