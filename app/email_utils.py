import base64
import binascii
import enum
import hmac
import json
import os
import quopri
import random
import time
import uuid
from copy import deepcopy
from email import policy, message_from_bytes, message_from_string
from email.header import decode_header, Header
from email.message import Message, EmailMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid, formatdate, formataddr
from smtplib import SMTP, SMTPException
from typing import Tuple, List, Optional, Union

import arrow
import dkim
import re2 as re
import spf
from aiosmtpd.smtp import Envelope
from cachetools import cached, TTLCache
from email_validator import (
    validate_email,
    EmailNotValidError,
    ValidatedEmail,
)
from flanker.addresslib import address
from flanker.addresslib.address import EmailAddress
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import func

from app.config import (
    ROOT_DIR,
    POSTFIX_SERVER,
    DKIM_SELECTOR,
    DKIM_PRIVATE_KEY,
    ALIAS_DOMAINS,
    POSTFIX_SUBMISSION_TLS,
    MAX_NB_EMAIL_FREE_PLAN,
    MAX_ALERT_24H,
    POSTFIX_PORT,
    URL,
    LANDING_PAGE_URL,
    EMAIL_DOMAIN,
    ALERT_DIRECTORY_DISABLED_ALIAS_CREATION,
    ALERT_SPF,
    ALERT_INVALID_TOTP_LOGIN,
    TEMP_DIR,
    ALIAS_AUTOMATIC_DISABLE,
    RSPAMD_SIGN_DKIM,
    NOREPLY,
    VERP_PREFIX,
    VERP_MESSAGE_LIFETIME,
    VERP_EMAIL_SECRET,
)
from app.db import Session
from app.dns_utils import get_mx_domains
from app.email import headers
from app.log import LOG
from app.mail_sender import sl_sendmail
from app.message_utils import message_to_bytes
from app.models import (
    Mailbox,
    User,
    SentAlert,
    CustomDomain,
    SLDomain,
    Contact,
    Alias,
    EmailLog,
    TransactionalEmail,
    IgnoreBounceSender,
    InvalidMailboxDomain,
    VerpType,
)
from app.utils import (
    random_string,
    convert_to_id,
    convert_to_alphanumeric,
    sanitize_email,
)

# 2022-01-01 00:00:00
VERP_TIME_START = 1640995200
VERP_HMAC_ALGO = "sha3-224"


def render(template_name, **kwargs) -> str:
    templates_dir = os.path.join(ROOT_DIR, "templates", "emails")
    env = Environment(loader=FileSystemLoader(templates_dir))

    template = env.get_template(template_name)

    return template.render(
        MAX_NB_EMAIL_FREE_PLAN=MAX_NB_EMAIL_FREE_PLAN,
        URL=URL,
        LANDING_PAGE_URL=LANDING_PAGE_URL,
        YEAR=arrow.now().year,
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
        render("transactional/trial-end.txt.jinja2", user=user),
        render("transactional/trial-end.html", user=user),
        ignore_smtp_error=True,
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


def send_invalid_totp_login_email(user, totp_type):
    send_email_with_rate_control(
        user,
        ALERT_INVALID_TOTP_LOGIN,
        user.email,
        "Unsuccessful attempt to login to your SimpleLogin account",
        render(
            "transactional/invalid-totp-login.txt",
            type=totp_type,
        ),
        render(
            "transactional/invalid-totp-login.html",
            type=totp_type,
        ),
        1,
    )


def send_test_email_alias(email, name):
    send_email(
        email,
        f"This email is sent to {email}",
        render(
            "transactional/test-email.txt",
            name=name,
            alias=email,
        ),
        render(
            "transactional/test-email.html",
            name=name,
            alias=email,
        ),
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
    retries=0,  # by default no retry if sending fails
    ignore_smtp_error=False,
    from_name=None,
    from_addr=None,
):
    to_email = sanitize_email(to_email)

    LOG.d("send email to %s, subject '%s'", to_email, subject)

    from_name = from_name or NOREPLY
    from_addr = from_addr or NOREPLY

    if html:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(plaintext))
        msg.attach(MIMEText(html, "html"))
    else:
        msg = EmailMessage()
        msg.set_payload(plaintext)
        msg[headers.CONTENT_TYPE] = "text/plain"

    msg[headers.SUBJECT] = subject
    msg[headers.FROM] = f'"{from_name}" <{from_addr}>'
    msg[headers.TO] = to_email

    msg_id_header = make_msgid(domain=EMAIL_DOMAIN)
    msg[headers.MESSAGE_ID] = msg_id_header

    date_header = formatdate()
    msg[headers.DATE] = date_header

    if headers.MIME_VERSION not in msg:
        msg[headers.MIME_VERSION] = "1.0"

    if unsubscribe_link:
        add_or_replace_header(msg, headers.LIST_UNSUBSCRIBE, f"<{unsubscribe_link}>")
        if not unsubscribe_via_email:
            add_or_replace_header(
                msg, headers.LIST_UNSUBSCRIBE_POST, "List-Unsubscribe=One-Click"
            )

    # add DKIM
    email_domain = from_addr[from_addr.find("@") + 1 :]
    add_dkim_signature(msg, email_domain)

    transaction = TransactionalEmail.create(email=to_email, commit=True)

    # use a different envelope sender for each transactional email (aka VERP)
    sl_sendmail(
        generate_verp_email(VerpType.transactional, transaction.id),
        to_email,
        msg,
        retries=retries,
        ignore_smtp_error=ignore_smtp_error,
    )


def send_email_with_rate_control(
    user: User,
    alert_type: str,
    to_email: str,
    subject,
    plaintext,
    html=None,
    max_nb_alert=MAX_ALERT_24H,
    nb_day=1,
    ignore_smtp_error=False,
    retries=0,
) -> bool:
    """Same as send_email with rate control over alert_type.
    Make sure no more than `max_nb_alert` emails are sent over the period of `nb_day` days

    Return true if the email is sent, otherwise False
    """
    to_email = sanitize_email(to_email)
    min_dt = arrow.now().shift(days=-1 * nb_day)
    nb_alert = (
        SentAlert.filter_by(alert_type=alert_type, to_email=to_email)
        .filter(SentAlert.created_at > min_dt)
        .count()
    )

    if nb_alert >= max_nb_alert:
        LOG.w(
            "%s emails were sent to %s in the last %s days, alert type %s",
            nb_alert,
            to_email,
            nb_day,
            alert_type,
        )
        return False

    SentAlert.create(user_id=user.id, alert_type=alert_type, to_email=to_email)
    Session.commit()

    if ignore_smtp_error:
        try:
            send_email(to_email, subject, plaintext, html, retries=retries)
        except SMTPException:
            LOG.w("Cannot send email to %s, subject %s", to_email, subject)
    else:
        send_email(to_email, subject, plaintext, html, retries=retries)

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
    nb_alert = SentAlert.filter_by(alert_type=alert_type, to_email=to_email).count()

    if nb_alert >= max_times:
        LOG.w(
            "%s emails were sent to %s alert type %s",
            nb_alert,
            to_email,
            alert_type,
        )
        return False

    SentAlert.create(user_id=user.id, alert_type=alert_type, to_email=to_email)
    Session.commit()
    send_email(to_email, subject, plaintext, html)
    return True


def get_email_local_part(address) -> str:
    """
    Get the local part from email
    ab@cd.com -> ab
    Convert the local part to lowercase
    """
    r: ValidatedEmail = validate_email(
        address, check_deliverability=False, allow_smtputf8=False
    )
    return r.local_part.lower()


def get_email_domain_part(address):
    """
    Get the domain part from email
    ab@cd.com -> cd.com
    """
    address = sanitize_email(address)
    return address[address.find("@") + 1 :]


def add_dkim_signature(msg: Message, email_domain: str):
    if RSPAMD_SIGN_DKIM:
        LOG.d("DKIM signature will be added by rspamd")
        msg[headers.SL_WANT_SIGNING] = "yes"
        return

    for dkim_headers in headers.DKIM_HEADERS:
        try:
            add_dkim_signature_with_header(msg, email_domain, dkim_headers)
            return
        except dkim.DKIMException:
            LOG.w("DKIM fail with %s", dkim_headers, exc_info=True)
            # try with another headers
            continue

    # To investigate why some emails can't be DKIM signed. todo: remove
    if TEMP_DIR:
        file_name = str(uuid.uuid4()) + ".eml"
        with open(os.path.join(TEMP_DIR, file_name), "wb") as f:
            f.write(msg.as_bytes())

        LOG.w("email saved to %s", file_name)

    raise Exception("Cannot create DKIM signature")


def add_dkim_signature_with_header(
    msg: Message, email_domain: str, dkim_headers: [bytes]
):
    delete_header(msg, "DKIM-Signature")

    # Specify headers in "byte" form
    # Generate message signature
    if DKIM_PRIVATE_KEY:
        sig = dkim.sign(
            message_to_bytes(msg),
            DKIM_SELECTOR,
            email_domain.encode(),
            DKIM_PRIVATE_KEY.encode(),
            include_headers=dkim_headers,
        )
        sig = sig.decode()

        # remove linebreaks from sig
        sig = sig.replace("\n", " ").replace("\r", "")
        msg[headers.DKIM_SIGNATURE] = sig[len("DKIM-Signature: ") :]


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


def sanitize_header(msg: Message, header: str):
    """remove trailing space and remove linebreak from a header"""
    for i in reversed(range(len(msg._headers))):
        header_name = msg._headers[i][0].lower()
        if header_name == header.lower():
            # msg._headers[i] is a tuple like ('From', 'hey@google.com')
            if msg._headers[i][1]:
                msg._headers[i] = (
                    msg._headers[i][0],
                    msg._headers[i][1].strip().replace("\n", " "),
                )


def delete_all_headers_except(msg: Message, headers: [str]):
    headers = [h.lower() for h in headers]

    for i in reversed(range(len(msg._headers))):
        header_name = msg._headers[i][0].lower()
        if header_name not in headers:
            del msg._headers[i]


def can_create_directory_for_address(email_address: str) -> bool:
    """return True if an email ends with one of the alias domains provided by SimpleLogin"""
    # not allow creating directory with premium domain
    for domain in ALIAS_DOMAINS:
        if email_address.endswith("@" + domain):
            return True

    return False


def is_valid_alias_address_domain(email_address) -> bool:
    """Return whether an address domain might a domain handled by SimpleLogin"""
    domain = get_email_domain_part(email_address)
    if SLDomain.get_by(domain=domain):
        return True

    if CustomDomain.get_by(domain=domain, verified=True):
        return True

    return False


def email_can_be_used_as_mailbox(email_address: str) -> bool:
    """Return True if an email can be used as a personal email.
    Use the email domain as criteria. A domain can be used if it is not:
    - one of ALIAS_DOMAINS
    - one of PREMIUM_ALIAS_DOMAINS
    - one of custom domains
    - a disposable domain
    """
    try:
        domain = validate_email(
            email_address, check_deliverability=False, allow_smtputf8=False
        ).domain
    except EmailNotValidError:
        LOG.d("%s is invalid email address", email_address)
        return False

    if not domain:
        LOG.d("no valid domain associated to %s", email_address)
        return False

    if SLDomain.get_by(domain=domain):
        LOG.d("%s is a SL domain", email_address)
        return False

    from app.models import CustomDomain

    if CustomDomain.get_by(domain=domain, verified=True):
        LOG.d("domain %s is a SimpleLogin custom domain", domain)
        return False

    if is_invalid_mailbox_domain(domain):
        LOG.d("Domain %s is invalid mailbox domain", domain)
        return False

    # check if email MX domain is disposable
    mx_domains = get_mx_domain_list(domain)

    # if no MX record, email is not valid
    if not mx_domains:
        LOG.d("No MX record for domain %s", domain)
        return False

    for mx_domain in mx_domains:
        if is_invalid_mailbox_domain(mx_domain):
            LOG.d("MX Domain %s %s is invalid mailbox domain", mx_domain, domain)
            return False

    return True


def is_invalid_mailbox_domain(domain):
    """
    Whether a domain is invalid mailbox domain
    Also return True if `domain` is a subdomain of an invalid mailbox domain
    """
    parts = domain.split(".")
    for i in range(0, len(parts) - 1):
        parent_domain = ".".join(parts[i:])

        if InvalidMailboxDomain.get_by(domain=parent_domain):
            return True

    return False


def get_mx_domain_list(domain) -> [str]:
    """return list of MX domains for a given email.
    domain name ends *without* a dot (".") at the end.
    """
    priority_domains = get_mx_domains(domain)

    return [d[:-1] for _, d in priority_domains]


def personal_email_already_used(email_address: str) -> bool:
    """test if an email can be used as user email"""
    if User.get_by(email=email_address):
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


def get_orig_message_from_bounce(bounce_report: Message) -> Optional[Message]:
    """parse the original email from Bounce"""
    i = 0
    for part in bounce_report.walk():
        i += 1

        # 1st part is the container (bounce report)
        # 2nd part is the report from our own Postfix
        # 3rd is report from other mailbox
        # 4th is the container of the original message
        # ...
        # 7th is original message
        if i == 7:
            return part


def get_mailbox_bounce_info(bounce_report: Message) -> Optional[Message]:
    """
    Return the bounce info from the bounce report
    An example of bounce info:

    Final-Recipient: rfc822; not-existing@gmail.com
    Original-Recipient: rfc822;not-existing@gmail.com
    Action: failed
    Status: 5.1.1
    Remote-MTA: dns; gmail-smtp-in.l.google.com
    Diagnostic-Code: smtp;
     550-5.1.1 The email account that you tried to reach does
        not exist. Please try 550-5.1.1 double-checking the recipient's email
        address for typos or 550-5.1.1 unnecessary spaces. Learn more at 550 5.1.1
        https://support.google.com/mail/?p=NoSuchUser z127si6173191wmc.132 - gsmtp

    """
    i = 0
    for part in bounce_report.walk():
        i += 1

        # 1st part is the container (bounce report)
        # 2nd part is the report from our own Postfix
        # 3rd is report from other mailbox
        # 4th is the container of the original message
        # 5th is a child of 3rd that contains more info about the bounce
        if i == 5:
            if not part["content-transfer-encoding"]:
                LOG.w("add missing content-transfer-encoding header")
                part["content-transfer-encoding"] = "7bit"

            try:
                part.as_bytes().decode()
            except UnicodeDecodeError:
                LOG.w("cannot use this bounce report")
                return
            else:
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
    spamassassin_status = msg[headers.X_SPAM_STATUS]
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
            LOG.w("Spam score %s exceeds %s", score, max_score)
            return True, spam_status_header

    return spamassassin_answer.lower() == "yes", spam_status_header


def get_header_unicode(header: Union[str, Header]) -> str:
    """
    Convert a header to unicode
    Should be used to handle headers like From:, To:, CC:, Subject:
    """
    if header is None:
        return ""

    ret = ""
    for to_decoded_str, charset in decode_header(header):
        if charset is None:
            if type(to_decoded_str) is bytes:
                decoded_str = to_decoded_str.decode()
            else:
                decoded_str = to_decoded_str
        else:
            try:
                decoded_str = to_decoded_str.decode(charset)
            except (LookupError, UnicodeDecodeError):  # charset is unknown
                LOG.w("Cannot decode %s with %s, try utf-8", to_decoded_str, charset)
                try:
                    decoded_str = to_decoded_str.decode("utf-8")
                except UnicodeDecodeError:
                    LOG.w("Cannot UTF-8 decode %s", to_decoded_str)
                    decoded_str = to_decoded_str.decode("utf-8", errors="replace")
        ret += decoded_str

    return ret


def copy(msg: Message) -> Message:
    """return a copy of message"""
    try:
        return deepcopy(msg)
    except Exception:
        LOG.w("deepcopy fails, try string parsing")
        try:
            return message_from_string(msg.as_string())
        except (UnicodeEncodeError, LookupError):
            LOG.w("as_string() fails, try bytes parsing")
            return message_from_bytes(message_to_bytes(msg))


def to_bytes(msg: Message):
    """replace Message.as_bytes() method by trying different policies"""
    for generator_policy in [None, policy.SMTP, policy.SMTPUTF8]:
        try:
            return msg.as_bytes(policy=generator_policy)
        except:
            LOG.w("as_bytes() fails with %s policy", policy, exc_info=True)

    msg_string = msg.as_string()
    try:
        return msg_string.encode()
    except:
        LOG.w("as_string().encode() fails", exc_info=True)

    return msg_string.encode(errors="replace")


def should_add_dkim_signature(domain: str) -> bool:
    if SLDomain.get_by(domain=domain):
        return True

    custom_domain: CustomDomain = CustomDomain.get_by(domain=domain)
    if custom_domain.dkim_verified:
        return True

    return False


def is_valid_email(email_address: str) -> bool:
    """
    Used to check whether an email address is valid
    NOT run MX check.
    NOT allow unicode.
    """
    try:
        validate_email(email_address, check_deliverability=False, allow_smtputf8=False)
        return True
    except EmailNotValidError:
        return False


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
    cte = (
        str(msg.get(headers.CONTENT_TRANSFER_ENCODING, ""))
        .lower()
        .strip()
        .strip('"')
        .strip("'")
    )
    if cte in (
        "",
        "7bit",
        "7-bit",
        "7bits",
        "8bit",
        "8bits",
        "binary",
        "8bit;",
        "utf-8",
    ):
        return EmailEncoding.NO

    if cte == "base64":
        return EmailEncoding.BASE64

    if cte == "quoted-printable":
        return EmailEncoding.QUOTED

    # some email services use unknown encoding
    if cte in ("amazonses.com",):
        return EmailEncoding.NO

    LOG.e("Unknown encoding %s", cte)

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


def add_header(msg: Message, text_header, html_header=None) -> Message:
    if not html_header:
        html_header = text_header
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
            if isinstance(part, Message):
                new_parts.append(add_header(part, text_header, html_header))
            else:
                new_parts.append(part)
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


def replace(msg: Union[Message, str], old, new) -> Union[Message, str]:
    if type(msg) is str:
        msg = msg.replace(old, new)
        return msg

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
        or content_type == "text/x-python-script"
    ):
        LOG.d("not applicable for %s", content_type)
        return msg

    if content_type in ("text/plain", "text/html"):
        encoding = get_encoding(msg)
        payload = msg.get_payload()
        if type(payload) is str:
            if encoding == EmailEncoding.QUOTED:
                LOG.d("handle quoted-printable replace %s -> %s", old, new)
                # first decode the payload
                try:
                    new_payload = quopri.decodestring(payload).decode("utf-8")
                except UnicodeDecodeError:
                    LOG.w("cannot decode payload:%s", payload)
                    return msg
                # then replace the old text
                new_payload = new_payload.replace(old, new)
                clone_msg = copy(msg)
                clone_msg.set_payload(quopri.encodestring(new_payload.encode()))
                return clone_msg
            elif encoding == EmailEncoding.BASE64:
                new_payload = decode_text(payload, encoding).replace(old, new)
                new_payload = base64.b64encode(new_payload.encode("utf-8"))
                clone_msg = copy(msg)
                clone_msg.set_payload(new_payload)
                return clone_msg
            else:
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
        "message/rfc822",
    ):
        new_parts = []
        for part in msg.get_payload():
            new_parts.append(replace(part, old, new))
        clone_msg = copy(msg)
        clone_msg.set_payload(new_parts)
        return clone_msg

    LOG.w("Cannot replace text for %s", msg.get_content_type())
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

    # user has set this option explicitly
    if user.include_sender_in_reverse_alias is not None:
        include_sender_in_reverse_alias = user.include_sender_in_reverse_alias

    if include_sender_in_reverse_alias and contact_email:
        # make sure contact_email can be ascii-encoded
        contact_email = convert_to_id(contact_email)
        contact_email = sanitize_email(contact_email)
        contact_email = contact_email[:45]
        # use _ instead of . to avoid AC_FROM_MANY_DOTS SpamAssassin rule
        contact_email = contact_email.replace("@", "_at_")
        contact_email = contact_email.replace(".", "_")
        contact_email = convert_to_alphanumeric(contact_email)

    # not use while to avoid infinite loop
    for _ in range(1000):
        if include_sender_in_reverse_alias and contact_email:
            random_length = random.randint(5, 10)
            reply_email = (
                # do not use the ra+ anymore
                # f"ra+{contact_email}+{random_string(random_length)}@{EMAIL_DOMAIN}"
                f"{contact_email}_{random_string(random_length)}@{EMAIL_DOMAIN}"
            )
        else:
            random_length = random.randint(20, 50)
            # do not use the ra+ anymore
            # reply_email = f"ra+{random_string(random_length)}@{EMAIL_DOMAIN}"
            reply_email = f"{random_string(random_length)}@{EMAIL_DOMAIN}"

        if not Contact.get_by(reply_email=reply_email):
            return reply_email

    raise Exception("Cannot generate reply email")


def is_reverse_alias(address: str) -> bool:
    # to take into account the new reverse-alias that doesn't start with "ra+"
    if Contact.get_by(reply_email=address):
        return True

    return address.endswith(f"@{EMAIL_DOMAIN}") and (
        address.startswith("reply+") or address.startswith("ra+")
    )


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


def should_disable(alias: Alias) -> (bool, str):
    """
    Return whether an alias should be disabled and if yes, the reason why
    """
    # Bypass the bounce rule
    if alias.cannot_be_disabled:
        LOG.w("%s cannot be disabled", alias)
        return False, ""

    if not ALIAS_AUTOMATIC_DISABLE:
        return False, ""

    yesterday = arrow.now().shift(days=-1)
    nb_bounced_last_24h = (
        Session.query(EmailLog)
        .filter(
            EmailLog.bounced.is_(True),
            EmailLog.is_reply.is_(False),
            EmailLog.created_at > yesterday,
        )
        .filter(EmailLog.alias_id == alias.id)
        .count()
    )
    # if more than 12 bounces in 24h -> disable alias
    if nb_bounced_last_24h > 12:
        return True, "+12 bounces in the last 24h"

    # if more than 5 bounces but has +10 bounces last week -> disable alias
    elif nb_bounced_last_24h > 5:
        one_week_ago = arrow.now().shift(days=-7)
        nb_bounced_7d_1d = (
            Session.query(EmailLog)
            .filter(
                EmailLog.bounced.is_(True),
                EmailLog.is_reply.is_(False),
                EmailLog.created_at > one_week_ago,
                EmailLog.created_at < yesterday,
            )
            .filter(EmailLog.alias_id == alias.id)
            .count()
        )
        if nb_bounced_7d_1d > 10:
            return (
                True,
                "+5 bounces in the last 24h and +10 bounces in the last 7 days",
            )
    else:
        # alias level
        # if bounces happen for at least 9 days in the last 10 days -> disable alias
        query = (
            Session.query(
                func.date(EmailLog.created_at).label("date"),
                func.count(EmailLog.id).label("count"),
            )
            .filter(EmailLog.alias_id == alias.id)
            .filter(
                EmailLog.created_at > arrow.now().shift(days=-10),
                EmailLog.bounced.is_(True),
                EmailLog.is_reply.is_(False),
            )
            .group_by("date")
        )

        if query.count() >= 9:
            return True, "Bounces every day for at least 9 days in the last 10 days"

        # account level
        query = (
            Session.query(
                func.date(EmailLog.created_at).label("date"),
                func.count(EmailLog.id).label("count"),
            )
            .filter(EmailLog.user_id == alias.user_id)
            .filter(
                EmailLog.created_at > arrow.now().shift(days=-10),
                EmailLog.bounced.is_(True),
                EmailLog.is_reply.is_(False),
            )
            .group_by("date")
        )

        # if an account has more than 10 bounces every day for at least 4 days in the last 10 days, disable alias
        date_bounces: List[Tuple[arrow.Arrow, int]] = list(query)
        more_than_10_bounces = [
            (d, nb_bounce) for d, nb_bounce in date_bounces if nb_bounce > 10
        ]
        if len(more_than_10_bounces) > 4:
            return True, "+10 bounces for +4 days in the last 10 days"

    return False, ""


def parse_id_from_bounce(email_address: str) -> int:
    return int(email_address[email_address.find("+") : email_address.rfind("+")])


def spf_pass(
    envelope,
    mailbox: Mailbox,
    user: User,
    alias: Alias,
    contact_email: str,
    msg: Message,
) -> bool:
    ip = msg[headers.SL_CLIENT_IP]
    if ip:
        LOG.d("Enforce SPF on %s %s", ip, envelope.mail_from)
        try:
            r = spf.check2(i=ip, s=envelope.mail_from, h=None)
        except Exception:
            LOG.e("SPF error, mailbox %s, ip %s", mailbox.email, ip)
        else:
            # TODO: Handle temperr case (e.g. dns timeout)
            # only an absolute pass, or no SPF policy at all is 'valid'
            if r[0] not in ["pass", "none"]:
                LOG.w(
                    "SPF fail for mailbox %s, reason %s, failed IP %s",
                    mailbox.email,
                    r[0],
                    ip,
                )
                subject = get_header_unicode(msg[headers.SUBJECT])
                send_email_with_rate_control(
                    user,
                    ALERT_SPF,
                    mailbox.email,
                    f"SimpleLogin Alert: attempt to send emails from your alias {alias.email} from unknown IP Address",
                    render(
                        "transactional/spf-fail.txt",
                        alias=alias.email,
                        ip=ip,
                        mailbox_url=URL + f"/dashboard/mailbox/{mailbox.id}#spf",
                        to_email=contact_email,
                        subject=subject,
                        time=arrow.now(),
                    ),
                    render(
                        "transactional/spf-fail.html",
                        ip=ip,
                        mailbox_url=URL + f"/dashboard/mailbox/{mailbox.id}#spf",
                        to_email=contact_email,
                        subject=subject,
                        time=arrow.now(),
                    ),
                )
                return False

    else:
        LOG.w(
            "Could not find %s header %s -> %s",
            headers.SL_CLIENT_IP,
            mailbox.email,
            contact_email,
        )

    return True


# cache the smtp server for 20 seconds
@cached(cache=TTLCache(maxsize=2, ttl=20))
def get_smtp_server():
    LOG.d("get a smtp server")
    if POSTFIX_SUBMISSION_TLS:
        smtp = SMTP(POSTFIX_SERVER, 587)
        smtp.starttls()
    else:
        smtp = SMTP(POSTFIX_SERVER, POSTFIX_PORT)

    return smtp


def get_queue_id(msg: Message) -> Optional[str]:
    """Get the Postfix queue-id from a message"""
    header_values = msg.get_all(headers.RSPAMD_QUEUE_ID)
    if header_values:
        # Get last in case somebody tries to inject a header
        return header_values[-1]

    received_header = str(msg[headers.RECEIVED])
    if not received_header:
        return

    # received_header looks like 'from mail-wr1-x434.google.com (mail-wr1-x434.google.com [IPv6:2a00:1450:4864:20::434])\r\n\t(using TLSv1.3 with cipher TLS_AES_128_GCM_SHA256 (128/128 bits))\r\n\t(No client certificate requested)\r\n\tby mx1.simplelogin.co (Postfix) with ESMTPS id 4FxQmw1DXdz2vK2\r\n\tfor <jglfdjgld@alias.com>; Fri,  4 Jun 2021 14:55:43 +0000 (UTC)'
    search_result = re.search("with ESMTPS id [0-9a-zA-Z]{1,}", received_header)
    if not search_result:
        return

    # the "with ESMTPS id 4FxQmw1DXdz2vK2" part
    with_esmtps = received_header[search_result.start() : search_result.end()]

    return with_esmtps[len("with ESMTPS id ") :]


def should_ignore_bounce(mail_from: str) -> bool:
    if IgnoreBounceSender.get_by(mail_from=mail_from):
        LOG.w("do not send back bounce report to %s", mail_from)
        return True

    return False


def parse_address_list(address_list: str) -> List[Tuple[str, str]]:
    """
    Parse a list of email addresses from a header in the form "ab <ab@sd.com>, cd <cd@cd.com>"
    and return a list [("ab", "ab@sd.com"),("cd", "cd@cd.com")]
    """
    processed_addresses = []
    for split_address in address_list.split(","):
        split_address = split_address.strip()
        if not split_address:
            continue
        processed_addresses.append(parse_full_address(split_address))
    return processed_addresses


def parse_full_address(full_address) -> (str, str):
    """
    parse the email address full format and return the display name and address
    For ex: ab <cd@xy.com> -> (ab, cd@xy.com)
    '=?UTF-8?B?TmjGoW4gTmd1eeG7hW4=?= <abcd@gmail.com>' -> ('Nhơn Nguyễn', "abcd@gmail.com")

    If the parsing fails, raise ValueError
    """
    full_address: EmailAddress = address.parse(full_address)
    if full_address is None:
        raise ValueError

    # address.parse can also parse a URL and return UrlAddress
    if type(full_address) is not EmailAddress:
        raise ValueError

    return full_address.display_name, full_address.address


def save_email_for_debugging(msg: Message, file_name_prefix=None) -> str:
    """Save email for debugging to temporary location
    Return the file path
    """
    if TEMP_DIR:
        file_name = str(uuid.uuid4()) + ".eml"
        if file_name_prefix:
            file_name = "{}-{}".format(file_name_prefix, file_name)

        with open(os.path.join(TEMP_DIR, file_name), "wb") as f:
            f.write(msg.as_bytes())

        LOG.d("email saved to %s", file_name)
        return file_name

    return ""


def save_envelope_for_debugging(envelope: Envelope, file_name_prefix=None) -> str:
    """Save envelope for debugging to temporary location
    Return the file path
    """
    if TEMP_DIR:
        file_name = str(uuid.uuid4()) + ".eml"
        if file_name_prefix:
            file_name = "{}-{}".format(file_name_prefix, file_name)

        with open(os.path.join(TEMP_DIR, file_name), "wb") as f:
            f.write(envelope.original_content)

        LOG.d("envelope saved to %s", file_name)
        return file_name

    return ""


def generate_verp_email(
    verp_type: VerpType, object_id: int, sender_domain: Optional[str] = None
) -> str:
    """Generates an email address with the verp type, object_id and domain encoded in the address
    and signed with hmac to prevent tampering
    """
    # Encoded as a list to minimize size of email address
    # Time is in minutes granularity and start counting on 2022-01-01 to reduce bytes to represent time
    data = [
        verp_type.value,
        object_id,
        int((time.time() - VERP_TIME_START) / 60),
    ]
    json_payload = json.dumps(data).encode("utf-8")
    # Signing without itsdangereous because it uses base64 that includes +/= symbols and lower and upper case letters.
    # We need to encode in base32
    payload_hmac = hmac.new(
        VERP_EMAIL_SECRET.encode("utf-8"), json_payload, VERP_HMAC_ALGO
    ).digest()[:8]
    encoded_payload = base64.b32encode(json_payload).rstrip(b"=").decode("utf-8")
    encoded_signature = base64.b32encode(payload_hmac).rstrip(b"=").decode("utf-8")
    return "{}.{}.{}@{}".format(
        VERP_PREFIX, encoded_payload, encoded_signature, sender_domain or EMAIL_DOMAIN
    ).lower()


def get_verp_info_from_email(email: str) -> Optional[Tuple[VerpType, int]]:
    """This method processes the email address, checks if it's a signed verp email generated by us to receive bounces
    and extracts the type of verp email and associated email log id/transactional email id stored as object_id
    """
    idx = email.find("@")
    if idx == -1:
        return None
    username = email[:idx]
    fields = username.split(".")
    if len(fields) != 3 or fields[0] != VERP_PREFIX:
        return None
    try:
        padding = (8 - (len(fields[1]) % 8)) % 8
        payload = base64.b32decode(fields[1].encode("utf-8").upper() + (b"=" * padding))
        padding = (8 - (len(fields[2]) % 8)) % 8
        signature = base64.b32decode(
            fields[2].encode("utf-8").upper() + (b"=" * padding)
        )
    except binascii.Error:
        return None
    expected_signature = hmac.new(
        VERP_EMAIL_SECRET.encode("utf-8"), payload, VERP_HMAC_ALGO
    ).digest()[:8]
    if expected_signature != signature:
        return None
    data = json.loads(payload)
    # verp type, object_id, time
    if len(data) != 3:
        return None
    if data[2] > (time.time() + VERP_MESSAGE_LIFETIME - VERP_TIME_START) / 60:
        return None
    return VerpType(data[0]), data[1]


def sl_formataddr(name_address_tuple: Tuple[str, str]):
    """Same as formataddr but use utf-8 encoding by default and always return str (and never Header)"""
    name, addr = name_address_tuple
    # formataddr can return Header, make sure to convert to str
    return str(formataddr((name, Header(addr, "utf-8"))))
