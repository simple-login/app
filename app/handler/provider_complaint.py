import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from io import BytesIO
from mailbox import Message
from typing import Optional, Union

from app import s3
from app.config import (
    ALERT_COMPLAINT_REPLY_PHASE,
    ALERT_COMPLAINT_TRANSACTIONAL_PHASE,
    ALERT_COMPLAINT_FORWARD_PHASE,
)
from app.email import headers
from app.email_utils import (
    parse_full_address,
    save_email_for_debugging,
    to_bytes,
    render,
    send_email_with_rate_control,
    parse_address_list,
    get_header_unicode,
    get_verp_info_from_email,
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
    VerpType,
    EmailLog,
    Mailbox,
)


@dataclass
class OriginalMessageInformation:
    sender_address: str
    rcpt_address: str
    mailbox_address: Optional[str]


class ProviderComplaintOrigin(ABC):
    @classmethod
    @abstractmethod
    def get_original_addresses(
        cls, message: Message
    ) -> Optional[OriginalMessageInformation]:
        pass

    @classmethod
    def _get_mailbox_id(cls, return_path: Optional[str]) -> Optional[Mailbox]:
        if not return_path:
            return None
        _, return_path = parse_full_address(get_header_unicode(return_path))
        verp_data = get_verp_info_from_email(return_path)
        if not verp_data:
            return None
        verp_type, email_log_id = verp_data
        if verp_type == VerpType.transactional:
            return None
        email_log = EmailLog.get_by(id=email_log_id)
        if email_log:
            return email_log.mailbox.email
        return None

    @classmethod
    def sanitize_addresses_and_extract_mailbox_id(
        cls, rcpt_header: Optional[str], message: Message
    ) -> Optional[OriginalMessageInformation]:
        """
        If the rcpt_header is not None, use it as the valid rcpt address, otherwise try to extract it from the To header
        of the original message, since in the original message there can be more than one recipients.
        There can only be one sender so that one can safely be extracted from the message headers.
        """
        try:
            if not rcpt_header:
                rcpt_header = message[headers.TO]
            rcpt_list = parse_address_list(get_header_unicode(rcpt_header))
            if not rcpt_list:
                saved_file = save_email_for_debugging(message, "NoRecipientComplaint")
                LOG.w(f"Cannot find rcpt. Saved to {saved_file or 'nowhere'}")
                return None
            rcpt_address = rcpt_list[0][1]
            _, sender_address = parse_full_address(
                get_header_unicode(message[headers.FROM])
            )

            return OriginalMessageInformation(
                sender_address,
                rcpt_address,
                cls._get_mailbox_id(message[headers.RETURN_PATH]),
            )
        except ValueError:
            saved_file = save_email_for_debugging(message, "ComplaintOriginalAddress")
            LOG.w(f"Cannot parse from header. Saved to {saved_file or 'nowhere'}")
            return None

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
        """
        Find a report that yahoo embeds in the complaint. It has content type 'message/feedback-report'
        """
        for part in message.walk():
            if part["content-type"] == "message/feedback-report":
                content = part.get_payload()
                if not content:
                    continue
                return content[0]
        return None

    @classmethod
    def get_original_addresses(
        cls, message: Message
    ) -> Optional[OriginalMessageInformation]:
        """
        Try to get the proper recipient from the report that yahoo adds as a port of the complaint. If we cannot find
        the rcpt in the report or we can't find the report, use the first address in the original message from
        """
        report = cls.get_feedback_report(message)
        original = cls.get_original_message(message)
        rcpt_header = report[headers.YAHOO_ORIGINAL_RECIPIENT]
        return cls.sanitize_addresses_and_extract_mailbox_id(rcpt_header, original)

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
    def get_original_addresses(
        cls, message: Message
    ) -> Optional[OriginalMessageInformation]:
        """
        Try to get the proper recipient from original x-simplelogin-envelope-to header we add on delivery.
        If we can't find the header, use the first address in the original message from"""
        original = cls.get_original_message(message)
        rcpt_header = original[headers.SL_ENVELOPE_TO]
        return cls.sanitize_addresses_and_extract_mailbox_id(rcpt_header, original)

    @classmethod
    def name(cls):
        return "hotmail"


def handle_hotmail_complaint(message: Message) -> bool:
    return handle_complaint(message, ProviderComplaintHotmail())


def handle_yahoo_complaint(message: Message) -> bool:
    return handle_complaint(message, ProviderComplaintYahoo())


def find_alias_with_address(address: str) -> Optional[Union[Alias, DomainDeletedAlias]]:
    return Alias.get_by(email=address) or DomainDeletedAlias.get_by(email=address)


def is_deleted_alias(address: str) -> bool:
    return DeletedAlias.get_by(email=address) is not None


def handle_complaint(message: Message, origin: ProviderComplaintOrigin) -> bool:
    msg_info = origin.get_original_addresses(message)
    if not msg_info:
        return False

    user = User.get_by(email=msg_info.rcpt_address)
    if user:
        LOG.d(f"Handle provider {origin.name()} complaint for {user}")
        report_complaint_to_user_in_transactional_phase(user, origin, msg_info)
        return True

    alias = find_alias_with_address(msg_info.sender_address)
    # the email is during a reply phase, from=alias and to=destination
    if alias:
        LOG.i(
            f"Complaint from {origin.name} during reply phase {alias} -> {msg_info.rcpt_address}, {user}"
        )
        report_complaint_to_user_in_reply_phase(
            alias, msg_info.rcpt_address, origin, msg_info
        )
        store_provider_complaint(alias, message)
        return True

    if is_deleted_alias(msg_info.sender_address):
        LOG.i(f"Complaint is for deleted alias. Do nothing")
        return True

    contact = Contact.get_by(reply_email=msg_info.sender_address)
    if contact:
        alias = contact.alias
    else:
        alias = find_alias_with_address(msg_info.rcpt_address)

    if is_deleted_alias(msg_info.rcpt_address):
        LOG.i(f"Complaint is for deleted alias. Do nothing")
        return True

    if not alias:
        LOG.e(
            f"Cannot find alias for address {msg_info.rcpt_address} or contact with reply {msg_info.sender_address}"
        )
        return False

    report_complaint_to_user_in_forward_phase(alias, origin, msg_info)
    return True


def report_complaint_to_user_in_reply_phase(
    alias: Union[Alias, DomainDeletedAlias],
    to_address: str,
    origin: ProviderComplaintOrigin,
    msg_info: OriginalMessageInformation,
):
    capitalized_name = origin.name().capitalize()
    mailbox_email = msg_info.mailbox_address
    if not mailbox_email:
        if type(alias) is Alias:
            mailbox_email = alias.mailbox.email
        else:
            mailbox_email = alias.domain.mailboxes[0].email
    send_email_with_rate_control(
        alias.user,
        f"{ALERT_COMPLAINT_REPLY_PHASE}_{origin.name()}",
        mailbox_email,
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
    user: User, origin: ProviderComplaintOrigin, msg_info: OriginalMessageInformation
):
    capitalized_name = origin.name().capitalize()
    send_email_with_rate_control(
        user,
        f"{ALERT_COMPLAINT_TRANSACTIONAL_PHASE}_{origin.name()}",
        msg_info.mailbox_address or user.email,
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
    alias: Union[Alias, DomainDeletedAlias],
    origin: ProviderComplaintOrigin,
    msg_info: OriginalMessageInformation,
):
    capitalized_name = origin.name().capitalize()
    user = alias.user

    mailbox_email = msg_info.mailbox_address
    if not mailbox_email:
        if type(alias) is Alias:
            mailbox_email = alias.mailbox.email
        else:
            mailbox_email = alias.domain.mailboxes[0].email
    send_email_with_rate_control(
        user,
        f"{ALERT_COMPLAINT_FORWARD_PHASE}_{origin.name()}",
        mailbox_email,
        f"Abuse report from {capitalized_name}",
        render(
            "transactional/provider-complaint-forward-phase.txt.jinja2",
            email=mailbox_email,
            provider=capitalized_name,
        ),
        render(
            "transactional/provider-complaint-forward-phase.html",
            email=mailbox_email,
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
