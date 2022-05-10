import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from io import BytesIO
from mailbox import Message
from typing import Optional, List

from app import s3
from app.config import (
    ALERT_COMPLAINT_REPLY_PHASE,
    ALERT_COMPLAINT_TRANSACTIONAL_PHASE,
    ALERT_COMPLAINT_FORWARD_PHASE,
)
from app.email import headers
from app.email_utils import (
    get_header_unicode,
    parse_full_address,
    save_email_for_debugging,
    to_bytes,
    render,
    send_email_with_rate_control,
    parse_address_list,
)
from app.log import LOG
from app.models import (
    User,
    Alias,
    DeletedAlias,
    DomainDeletedAlias,
    Contact,
    ProviderComplaint,
    Phase,
    ProviderComplaintState,
    RefusedEmail,
)


@dataclass
class OriginalAddresses:
    sender: str
    recipient: str


class ProviderComplaintOrigin(ABC):
    @classmethod
    @abstractmethod
    def get_original_message(cls, message: Message) -> Optional[Message]:
        pass

    @classmethod
    @abstractmethod
    def get_original_addresses(cls, message: Message) -> Optional[OriginalAddresses]:
        pass

    @classmethod
    @abstractmethod
    def name(cls):
        pass


class ProviderComplaintYahoo(ProviderComplaintOrigin):
    @classmethod
    def get_original_message(cls, message: Message) -> Optional[Message]:
        # 1st part is the container
        # 2nd has empty body
        # 6th is the original message
        current_part = 0
        for part in message.walk():
            current_part += 1
            if current_part == 6:
                return part
        return None

    @classmethod
    def get_feedback_report(cls, message: Message) -> Optional[Message]:
        for part in message.walk():
            if part["content-type"] == "message/feedback-report":
                content = part.get_payload()
                if not content:
                    continue
                return content[0]
        return None

    @classmethod
    def get_original_addresses(cls, message: Message) -> Optional[OriginalAddresses]:
        report = cls.get_feedback_report(message)
        original = cls.get_original_message(message)
        rcpt_address = report["original-rcpt-to"]
        try:
            if rcpt_address:
                _, rcpt_address = parse_full_address(rcpt_address)
            else:
                rcpt_address = parse_address_list(original[headers.TO])[0]
            _, sender_address = parse_full_address(original[headers.FROM])
            return OriginalAddresses(sender_address, rcpt_address)
        except ValueError:
            saved_file = save_email_for_debugging(message, "ComplaintOriginalAddress")
            LOG.w(f"Cannot parse from header. Saved to {saved_file or 'nowhere'}")
            return False

    @classmethod
    def name(cls):
        return "yahoo"


class ProviderComplaintHotmail(ProviderComplaintOrigin):
    @classmethod
    def get_original_message(cls, message: Message) -> Optional[Message]:
        # 1st part is the container
        # 2nd has empty body
        # 3rd is the original message
        current_part = 0
        for part in message.walk():
            current_part += 1
            if current_part == 3:
                return part
        return None

    @classmethod
    def get_original_addresses(cls, message: Message) -> Optional[OriginalAddresses]:
        try:
            part = cls.get_original_message(message)
            rcpt_address = part["x-simplelogin-envelope-to"]
            if rcpt_address:
                _, rcpt_address = parse_full_address(rcpt_address)
            else:
                rcpt_address = parse_address_list(part[headers.TO])[0]
            _, sender_address = parse_full_address(part[headers.FROM])
            return OriginalAddresses(sender_address, rcpt_address)
        except ValueError:
            saved_file = save_email_for_debugging(message, "ComplaintOriginalAddress")
            LOG.w(f"Cannot parse from header. Saved to {saved_file or 'nowhere'}")
            return False

    @classmethod
    def name(cls):
        return "hotmail"


def handle_hotmail_complaint(message: Message) -> bool:
    return handle_complaint(message, ProviderComplaintHotmail())


def handle_yahoo_complaint(message: Message) -> bool:
    return handle_complaint(message, ProviderComplaintYahoo())


def find_alias_with_address(address: str) -> Optional[Alias]:
    return (
        Alias.get_by(email=address)
        or DeletedAlias.get_by(email=address)
        or DomainDeletedAlias.get_by(email=address)
    )


def handle_complaint(message: Message, origin: ProviderComplaintOrigin) -> bool:
    addresses = origin.get_original_addresses(message)
    if not addresses:
        return False

    user = User.get_by(email=addresses.recipient)
    if user:
        LOG.d(f"Handle provider {origin.name()} complaint for {user}")
        report_complaint_to_user_in_transactional_phase(user, origin)
        return True

    alias = find_alias_with_address(addresses.sender)
    # the email is during a reply phase, from=alias and to=destination
    if alias:
        LOG.i(
            f"Complaint from {origin.name} during reply phase {alias} -> {addresses.recipient}, {user}"
        )
        report_complaint_to_user_in_reply_phase(alias, addresses.recipient, origin)
        store_provider_complaint(alias, message)
        return True

    contact = Contact.get_by(reply_email=addresses.sender)
    if contact:
        alias = contact.alias
    else:
        alias = find_alias_with_address(addresses.recipient)

    if not alias:
        LOG.e(
            f"Cannot find alias for address {addresses.recipient} or contact with reply {addresses.sender}"
        )
        return False

    report_complaint_to_user_in_forward_phase(alias, origin)
    return True


def report_complaint_to_user_in_reply_phase(
    alias: Alias, to_address: str, origin: ProviderComplaintOrigin
):
    capitalized_name = origin.name().capitalize()
    send_email_with_rate_control(
        alias.user,
        f"{ALERT_COMPLAINT_REPLY_PHASE}_{origin.name()}",
        alias.user.email,
        f"Abuse report from {capitalized_name}",
        render(
            "transactional/provider-complaint-reply-phase.txt.jinja2",
            user=alias.user,
            alias=alias,
            destination=to_address,
            provider=capitalized_name,
        ),
        max_nb_alert=1,
        nb_day=7,
    )


def report_complaint_to_user_in_transactional_phase(
    user: User, origin: ProviderComplaintOrigin
):
    capitalized_name = origin.name().capitalize()
    send_email_with_rate_control(
        user,
        f"{ALERT_COMPLAINT_TRANSACTIONAL_PHASE}_{origin.name()}",
        user.email,
        f"Abuse report from {capitalized_name}",
        render(
            "transactional/provider-complaint-to-user.txt.jinja2",
            user=user,
            provider=capitalized_name,
        ),
        render(
            "transactional/provider-complaint-to-user.html",
            user=user,
            provider=capitalized_name,
        ),
        max_nb_alert=1,
        nb_day=7,
    )


def report_complaint_to_user_in_forward_phase(
    alias: Alias, origin: ProviderComplaintOrigin
):
    capitalized_name = origin.name().capitalize()
    user = alias.user
    send_email_with_rate_control(
        user,
        f"{ALERT_COMPLAINT_FORWARD_PHASE}_{origin.name()}",
        user.email,
        f"Abuse report from {capitalized_name}",
        render(
            "transactional/provider-complaint-forward-phase.txt.jinja2",
            user=user,
            provider=capitalized_name,
        ),
        render(
            "transactional/provider-complaint-forward-phase.html",
            user=user,
            provider=capitalized_name,
        ),
        max_nb_alert=1,
        nb_day=7,
    )


def store_provider_complaint(alias, message):
    email_name = f"reply-{uuid.uuid4().hex}.eml"
    full_report_path = f"provider_complaint/{email_name}"
    s3.upload_email_from_bytesio(
        full_report_path, BytesIO(to_bytes(message)), email_name
    )
    refused_email = RefusedEmail.create(
        full_report_path=full_report_path,
        user_id=alias.user_id,
        path=email_name,
        commit=True,
    )
    ProviderComplaint.create(
        user_id=alias.user_id,
        state=ProviderComplaintState.new.value,
        phase=Phase.reply.value,
        refused_email_id=refused_email.id,
        commit=True,
    )
