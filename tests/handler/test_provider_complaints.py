from email.message import Message

import pytest
from app.config import (
    ALERT_COMPLAINT_FORWARD_PHASE,
    ALERT_COMPLAINT_REPLY_PHASE,
    ALERT_COMPLAINT_TRANSACTIONAL_PHASE,
    POSTMASTER,
)
from app.db import Session
from app.email import headers, status
from app.handler.provider_complaint import (
    handle_hotmail_complaint,
    handle_yahoo_complaint,
)
from app.models import Alias, ProviderComplaint, SentAlert
from tests.utils import create_new_user, load_eml_file

origins = [
    [handle_yahoo_complaint, "yahoo"],
    [handle_hotmail_complaint, "hotmail"],
]


def prepare_complaint(
    provider_name: str, rcpt_address: str, sender_address: str
) -> Message:
    return load_eml_file(
        f"{provider_name}_complaint.eml",
        {
            "postmaster": POSTMASTER,
            "return_path": "sl.something.other@simplelogin.co",
            "rcpt": rcpt_address,
            "sender": sender_address,
            "rcpt_comma_list": f"{rcpt_address},other_rcpt@somwhere.net",
        },
    )


@pytest.mark.parametrize("handle_ftor,provider", origins)
def test_provider_to_user(flask_client, handle_ftor, provider):
    user = create_new_user()
    complaint = prepare_complaint(provider, user.email, "nobody@nowhere.net")
    assert handle_ftor(complaint)
    found = ProviderComplaint.filter_by(user_id=user.id).all()
    assert len(found) == 0
    alerts = SentAlert.filter_by(user_id=user.id).all()
    assert len(alerts) == 1
    assert alerts[0].alert_type == f"{ALERT_COMPLAINT_TRANSACTIONAL_PHASE}_{provider}"


@pytest.mark.parametrize("handle_ftor,provider", origins)
def test_provider_forward_phase(flask_client, handle_ftor, provider):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    Session.commit()
    complaint = prepare_complaint(provider, "nobody@nowhere.net", alias.email)
    assert handle_ftor(complaint)
    found = ProviderComplaint.filter_by(user_id=user.id).all()
    assert len(found) == 1
    alerts = SentAlert.filter_by(user_id=user.id).all()
    assert len(alerts) == 1
    assert alerts[0].alert_type == f"{ALERT_COMPLAINT_REPLY_PHASE}_{provider}"


@pytest.mark.parametrize("handle_ftor,provider", origins)
def test_provider_reply_phase(flask_client, handle_ftor, provider):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    Session.commit()
    original_message = Message()
    original_message[headers.TO] = alias.email
    original_message[headers.FROM] = "no@no.no"
    original_message.set_payload("Contents")

    complaint = prepare_complaint(provider, alias.email, "no@no.no")
    assert handle_ftor(complaint)
    found = ProviderComplaint.filter_by(user_id=user.id).all()
    assert len(found) == 0
    alerts = SentAlert.filter_by(user_id=user.id).all()
    assert len(alerts) == 1
    assert alerts[0].alert_type == f"{ALERT_COMPLAINT_FORWARD_PHASE}_{provider}"
