import uuid
from abc import ABC, abstractmethod
from io import BytesIO
from mailbox import Message
from typing import Optional

from app import s3
from app.config import (
    ALERT_COMPLAINT_REPLY_PHASE,
    ALERT_COMPLAINT_TO_USER,
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
)
from app.log import LOG
from app.models import (
    User,
    Alias,
    DeletedAlias,
    DomainDeletedAlias,
    Contact,
    TransactionalComplaint,
    Phase,
    TransactionalComplaintState,
    RefusedEmail,
)


class TransactionalComplaintOrigin(ABC):
    @classmethod
    @abstractmethod
    def get_original_message(cls, message: Message) -> Optional[Message]:
        pass

    @classmethod
    @abstractmethod
    def name(cls):
        pass


class TransactionalYahooOrigin(TransactionalComplaintOrigin):
    @classmethod
    def get_original_message(cls, message: Message) -> Optional[Message]:
        wanted_part = 6
        for part in message.walk():
            wanted_part -= 1
            if wanted_part == 0:
                return part
        return None

    @classmethod
    def name(cls):
        return "yahoo"


class TransactionalHotmailOrigin(TransactionalComplaintOrigin):
    @classmethod
    def get_original_message(cls, message: Message) -> Optional[Message]:
        wanted_part = 3
        for part in message.walk():
            wanted_part -= 1
            if wanted_part == 0:
                return part
        return None

    @classmethod
    def name(cls):
        return "hotmail"


def handle_hotmail_complaint(message: Message) -> bool:
    return handle_complaint(message, TransactionalHotmailOrigin())


def handle_yahoo_complaint(message: Message) -> bool:
    return handle_complaint(message, TransactionalYahooOrigin())


def find_alias_with_address(address: str) -> Optional[Alias]:
    return (
        Alias.get_by(email=address)
        or DeletedAlias.get_by(email=address)
        or DomainDeletedAlias.get_by(email=address)
    )


def handle_complaint(message: Message, origin: TransactionalComplaintOrigin) -> bool:
    original_message = origin.get_original_message(message)

    try:
        _, to_address = parse_full_address(
            get_header_unicode(original_message[headers.TO])
        )
        _, from_address = parse_full_address(
            get_header_unicode(original_message[headers.FROM])
        )
    except ValueError:
        saved_file = save_email_for_debugging(message, "FromParseFailed")
        LOG.w("Cannot parse from header. Saved to {}".format(saved_file or "nowhere"))
        return True

    user = User.get_by(email=to_address)
    if user:
        LOG.d("Handle transactional {} complaint for {}".format(origin.name(), user))
        report_complaint_to_user(user, origin)
        return True

    alias = find_alias_with_address(from_address)
    # the email is during a reply phase, from=alias and to=destination
    if alias:
        LOG.i(
            "Complaint from {} during reply phase {} -> {}, {}".format(
                origin.name(), alias, to_address, user
            )
        )
        report_complaint_to_user_in_reply_phase(alias, to_address, origin)
        store_transactional_complaint(alias, message)
        return True

    contact = Contact.get_by(reply_email=from_address)
    if contact:
        alias = contact.alias
    else:
        alias = find_alias_with_address(to_address)

    if not alias:
        LOG.e(
            f"Cannot find alias from address {to_address} or contact with reply {from_address}"
        )
        return False

    report_complaint_to_user_in_forward_phase(alias, origin)
    return True


def report_complaint_to_user_in_reply_phase(
    alias: Alias, to_address: str, origin: TransactionalComplaintOrigin
):
    capitalized_name = origin.name().capitalize()
    send_email_with_rate_control(
        alias.user,
        f"{ALERT_COMPLAINT_REPLY_PHASE}_{origin.name()}",
        alias.user.email,
        f"Abuse report from {capitalized_name}",
        render(
            "transactional/transactional-complaint-reply-phase.txt.jinja2",
            user=alias.user,
            alias=alias,
            destination=to_address,
            provider=capitalized_name,
        ),
        max_nb_alert=1,
        nb_day=7,
    )


def report_complaint_to_user(user: User, origin: TransactionalComplaintOrigin):
    capitalized_name = origin.name().capitalize()
    send_email_with_rate_control(
        user,
        f"{ALERT_COMPLAINT_TO_USER}_{origin.name()}",
        user.email,
        f"Abuse report from {capitalized_name}",
        render(
            "transactional/transactional-complaint-to-user.txt.jinja2",
            user=user,
            provider=capitalized_name,
        ),
        render(
            "transactional/transactional-complaint-to-user.html",
            user=user,
            provider=capitalized_name,
        ),
        max_nb_alert=1,
        nb_day=7,
    )


def report_complaint_to_user_in_forward_phase(
    alias: Alias, origin: TransactionalComplaintOrigin
):
    capitalized_name = origin.name().capitalize()
    user = alias.user
    send_email_with_rate_control(
        user,
        f"{ALERT_COMPLAINT_FORWARD_PHASE}_{origin.name()}",
        user.email,
        f"Abuse report from {capitalized_name}",
        render(
            "transactional/transactional-complaint-forward-phase.txt.jinja2",
            user=user,
            provider=capitalized_name,
        ),
        render(
            "transactional/transactional-complaint-forward-phase.html",
            user=user,
            provider=capitalized_name,
        ),
        max_nb_alert=1,
        nb_day=7,
    )


def store_transactional_complaint(alias, message):
    email_name = f"reply-{uuid.uuid4().hex}.eml"
    full_report_path = f"transactional_complaint/{email_name}"
    s3.upload_email_from_bytesio(
        full_report_path, BytesIO(to_bytes(message)), email_name
    )
    refused_email = RefusedEmail.create(
        full_report_path=full_report_path,
        user_id=alias.user_id,
        path=email_name,
        commit=True,
    )
    TransactionalComplaint.create(
        user_id=alias.user_id,
        state=TransactionalComplaintState.new.value,
        phase=Phase.reply.value,
        refused_email_id=refused_email.id,
        commit=True,
    )
