from aiosmtpd.smtp import Envelope

import email_handler
from app.email import status, headers
from app.email_utils import get_header_unicode, parse_full_address

from app.mail_sender import mail_sender
from app.models import Alias, Contact
from tests.utils import create_new_user, load_eml_file


@mail_sender.store_emails_test_decorator
def test_multi_reply_to():
    user = create_new_user()
    alias = Alias.create_new_random(user)
    envelope = Envelope()
    envelope.mail_from = "env.somewhere"
    envelope.rcpt_tos = [alias.email]
    msg = load_eml_file("multi_reply_to.eml", {"alias_email": alias.email})
    alias_id = alias.id
    result = email_handler.MailHandler()._handle(envelope, msg)
    assert result == status.E200
    sent_emails = mail_sender.get_stored_emails()
    assert 1 == len(sent_emails)
    msg = sent_emails[0].msg
    reply_to = get_header_unicode(msg[headers.REPLY_TO])
    entries = reply_to.split(",")
    assert 4 == len(entries)
    for entry in entries:
        dummy, email = parse_full_address(entry)
        contact = Contact.get_by(reply_email=email)
        assert contact is not None
        assert contact.alias_id == alias_id
