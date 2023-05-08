from app import config
from app.mail_sender import mail_sender
from app.mailbox_utils import create_mailbox_and_send_verification
from tests.utils import create_new_user, random_email


def setup_module():
    config.SKIP_MX_LOOKUP_ON_CHECK = True


def teardown_module():
    config.SKIP_MX_LOOKUP_ON_CHECK = False


@mail_sender.store_emails_test_decorator
def test_mailbox_creation_sends_link_verification():
    user = create_new_user()
    email = random_email()
    mailbox, errorMsg = create_mailbox_and_send_verification(user, email)
    assert errorMsg is None
    assert mailbox is not None
    assert mailbox.validation_code is None
    assert mailbox.validation_expiration is None
    assert mailbox.validation_tries == 0
    mails = mail_sender.get_stored_emails()
    assert len(mails) == 1
    assert "link" in str(mails[0].msg)


@mail_sender.store_emails_test_decorator
def test_mailbox_creation_sends_code_verification():
    user = create_new_user()
    email = random_email()
    mailbox, errorMsg = create_mailbox_and_send_verification(user, email, True)
    assert errorMsg is None
    assert mailbox is not None
    assert mailbox.validation_code is not None
    assert mailbox.validation_expiration is not None
    assert mailbox.validation_tries == 0
    mails = mail_sender.get_stored_emails()
    assert len(mails) == 1
    assert mailbox.validation_code in str(mails[0].msg)
