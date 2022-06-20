from app.mail_sender import mail_sender
from job_runner import welcome_proton
from tests.utils import create_new_user


@mail_sender.store_emails_test_decorator
def test_send_welcome_proton_email():
    user = create_new_user()
    welcome_proton(user)
    sent_mails = mail_sender.get_stored_emails()
    assert len(sent_mails) == 1
    sent_mail = sent_mails[0]
    to_email, _, _ = user.get_communication_email()
    sent_mail.envelope_to = to_email
