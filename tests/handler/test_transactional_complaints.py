import email
from email.message import Message
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pytest

from app.config import (
    ALERT_COMPLAINT_FORWARD_PHASE,
    ALERT_COMPLAINT_REPLY_PHASE,
    ALERT_COMPLAINT_TO_USER,
)
from app.db import Session
from app.email import headers
from app.handler.transactional_complaint import (
    handle_hotmail_complaint,
    handle_yahoo_complaint,
)
from app.models import Alias, TransactionalComplaint, SentAlert
from tests.utils import create_new_user

origins = [
    [handle_yahoo_complaint, "yahoo", 6],
    [handle_hotmail_complaint, "hotmail", 3],
]


def prepare_complaint(message: Message, part_num: int) -> Message:
    complaint = MIMEMultipart("related")
    # When walking, part 0 is the full message so we -1, and we want to be part N so -1 again
    for i in range(part_num - 2):
        document = MIMEText("text", "plain")
        document.set_payload(f"Part {i}")
        complaint.attach(document)
    complaint.attach(message)

    return email.message_from_bytes(complaint.as_bytes())


@pytest.mark.parametrize("handle_ftor,provider,part_num", origins)
def test_transactional_to_user(flask_client, handle_ftor, provider, part_num):
    user = create_new_user()
    original_message = Message()
    original_message[headers.TO] = user.email
    original_message[headers.FROM] = "nobody@nowhere.net"
    original_message.set_payload("Contents")

    complaint = prepare_complaint(original_message, part_num)
    assert handle_ftor(complaint)
    found = TransactionalComplaint.filter_by(user_id=user.id).all()
    assert len(found) == 0
    alerts = SentAlert.filter_by(user_id=user.id).all()
    assert len(alerts) == 1
    assert alerts[0].alert_type == f"{ALERT_COMPLAINT_TO_USER}_{provider}"


@pytest.mark.parametrize("handle_ftor,provider,part_num", origins)
def test_transactional_forward_phase(flask_client, handle_ftor, provider, part_num):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    Session.commit()
    original_message = Message()
    original_message[headers.TO] = "nobody@nowhere.net"
    original_message[headers.FROM] = alias.email
    original_message.set_payload("Contents")

    complaint = prepare_complaint(original_message, part_num)
    assert handle_ftor(complaint)
    found = TransactionalComplaint.filter_by(user_id=user.id).all()
    assert len(found) == 1
    alerts = SentAlert.filter_by(user_id=user.id).all()
    assert len(alerts) == 1
    assert alerts[0].alert_type == f"{ALERT_COMPLAINT_REPLY_PHASE}_{provider}"


@pytest.mark.parametrize("handle_ftor,provider,part_num", origins)
def test_transactional_reply_phase(flask_client, handle_ftor, provider, part_num):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    Session.commit()
    original_message = Message()
    original_message[headers.TO] = alias.email
    original_message[headers.FROM] = "no@no.no"
    original_message.set_payload("Contents")

    complaint = prepare_complaint(original_message, part_num)
    assert handle_ftor(complaint)
    found = TransactionalComplaint.filter_by(user_id=user.id).all()
    assert len(found) == 0
    alerts = SentAlert.filter_by(user_id=user.id).all()
    assert len(alerts) == 1
    assert alerts[0].alert_type == f"{ALERT_COMPLAINT_FORWARD_PHASE}_{provider}"
