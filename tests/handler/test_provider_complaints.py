import random
from email.message import Message

import pytest
from app.config import (
    ALERT_COMPLAINT_FORWARD_PHASE,
    ALERT_COMPLAINT_REPLY_PHASE,
    ALERT_COMPLAINT_TRANSACTIONAL_PHASE,
    POSTMASTER,
)
from app.db import Session
from app.email_utils import generate_verp_email
from app.handler.provider_complaint import (
    handle_hotmail_complaint,
    handle_yahoo_complaint,
)
from app.mail_sender import mail_sender
from app.models import (
    Alias,
    ProviderComplaint,
    SentAlert,
    EmailLog,
    VerpType,
    Contact,
)
from tests.utils import create_new_user, load_eml_file

origins = [
    [handle_yahoo_complaint, "yahoo"],
    [handle_hotmail_complaint, "hotmail"],
]


def prepare_complaint(
    provider_name: str, alias: Alias, rcpt_address: str, sender_address: str
) -> Message:
    contact = Contact.create(
        user_id=alias.user.id,
        alias_id=alias.id,
        website_email=f"contact{random.random()}@mailbox.test",
        reply_email="d@e.f",
        commit=True,
    )
    elog = EmailLog.create(
        user_id=alias.user.id,
        mailbox_id=alias.user.default_mailbox_id,
        contact_id=contact.id,
        commit=True,
        bounced=True,
    )
    return_path = generate_verp_email(VerpType.bounce_forward, elog.id)
    return load_eml_file(
        f"{provider_name}_complaint.eml",
        {
            "postmaster": POSTMASTER,
            "return_path": return_path,
            "rcpt": rcpt_address,
            "sender": sender_address,
            "rcpt_comma_list": f"{rcpt_address},other_rcpt@somwhere.net",
        },
    )


@mail_sender.store_emails_test_decorator
@pytest.mark.parametrize("handle_ftor,provider", origins)
def test_provider_to_user(flask_client, handle_ftor, provider):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    Session.commit()
    complaint = prepare_complaint(provider, alias, user.email, "nobody@nowhere.net")
    assert handle_ftor(complaint)
    found = ProviderComplaint.filter_by(user_id=user.id).all()
    assert len(found) == 0
    alerts = SentAlert.filter_by(user_id=user.id).all()
    assert len(alerts) == 1
    sent_mails = mail_sender.get_stored_emails()
    assert len(sent_mails) == 1
    assert alerts[0].alert_type == f"{ALERT_COMPLAINT_TRANSACTIONAL_PHASE}_{provider}"


@pytest.mark.parametrize("handle_ftor,provider", origins)
def test_provider_forward_phase(flask_client, handle_ftor, provider):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    Session.commit()
    complaint = prepare_complaint(provider, alias, "nobody@nowhere.net", alias.email)
    assert handle_ftor(complaint)
    found = ProviderComplaint.filter_by(user_id=user.id).all()
    assert len(found) == 1
    alerts = SentAlert.filter_by(user_id=user.id).all()
    assert len(alerts) == 1
    assert alerts[0].alert_type == f"{ALERT_COMPLAINT_REPLY_PHASE}_{provider}"


@mail_sender.store_emails_test_decorator
@pytest.mark.parametrize("handle_ftor,provider", origins)
def test_provider_reply_phase(flask_client, handle_ftor, provider):
    mail_sender.store_emails_instead_of_sending()
    mail_sender.purge_stored_emails()
    user = create_new_user()
    alias = Alias.create_new_random(user)
    Session.commit()
    complaint = prepare_complaint(provider, alias, alias.email, "no@no.no")
    assert handle_ftor(complaint)
    found = ProviderComplaint.filter_by(user_id=user.id).all()
    assert len(found) == 0
    alerts = SentAlert.filter_by(user_id=user.id).all()
    assert len(alerts) == 1
    sent_mails = mail_sender.get_stored_emails()
    assert len(sent_mails) == 1
    assert alerts[0].alert_type == f"{ALERT_COMPLAINT_FORWARD_PHASE}_{provider}"
