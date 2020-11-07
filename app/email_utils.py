import email
import os
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
)
from app.dns_utils import get_mx_domains
from app.extensions import db
from app.log import LOG
from app.models import Mailbox, User, SentAlert, CustomDomain, SLDomain


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
        f"Welcome to SimpleLogin {user.name}",
        render("com/welcome.txt", name=user.name, user=user, alias=alias),
        render("com/welcome.html", name=user.name, user=user, alias=alias),
        unsubscribe_link,
        via_email,
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
    msg.attach(MIMEText(plaintext, "text"))

    if not html:
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

    msg_raw = msg.as_bytes()
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
    to_email = to_email.lower().strip()
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
    to_email = to_email.lower().strip()
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
    return address[address.find("@") + 1 :].strip().lower()


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


def get_addrs_from_header(msg: Message, header) -> [str]:
    """Get all addresses contained in `header`
    Used for To or CC header.
    """
    ret = []
    header_content = msg.get_all(header)
    if not header_content:
        return ret

    for addrs in header_content:
        # force convert header to string, sometimes addrs is Header object
        addrs = str(addrs)
        for addr in addrs.split(","):
            ret.append(addr.strip())

    # do not return empty string
    return [r for r in ret if r]


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
        else:
            name = decoded_string

    if type(name) == bytes:
        name = name.decode()
    return name, email


def copy(msg: Message) -> Message:
    """return a copy of message"""
    return email.message_from_bytes(msg.as_bytes())


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
            return msg.as_bytes(policy=email.policy.SMTPUTF8)


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


def add_header(msg: Message, text_header, html_header) -> Message:
    if msg.get_content_type() == "text/plain":
        payload = msg.get_payload()
        if type(payload) is str:
            clone_msg = copy(msg)
            payload = f"{text_header}\n---\n{payload}"
            clone_msg.set_payload(payload)
            return clone_msg
    elif msg.get_content_type() == "text/html":
        payload = msg.get_payload()
        if type(payload) is str:

            new_payload = f"""
<table width="100%" style="width: 100%; -premailer-width: 100%; -premailer-cellpadding: 0; -premailer-cellspacing: 0; margin: 0; padding: 0;">
    <tr>
        <td style="border-bottom:1px dashed #5675E2; padding: 10px 0px">{html_header}</td>
    </tr>
    <tr>
        <td>{payload}</td>
    </tr>
</table>
            """
            clone_msg = copy(msg)
            clone_msg.set_payload(new_payload)
            return clone_msg
    elif msg.get_content_type() in ("multipart/alternative", "multipart/related"):
        new_parts = []
        for part in msg.get_payload():
            new_parts.append(add_header(part, text_header, html_header))
        clone_msg = copy(msg)
        clone_msg.set_payload(new_parts)
        return clone_msg

    LOG.d("No header added for %s", msg.get_content_type())
    return msg
