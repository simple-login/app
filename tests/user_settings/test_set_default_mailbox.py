from typing import Optional
import pytest

from app import mailbox_utils, user_settings, config
from app.db import Session
from app.models import User
from tests.utils import random_email, create_new_user


user: Optional[User] = None


def setup_module():
    global user
    config.SKIP_MX_LOOKUP_ON_CHECK = True
    user = create_new_user()
    user.trial_end = None
    user.lifetime = True
    Session.commit()


def teardown_module():
    config.SKIP_MX_LOOKUP_ON_CHECK = False  # noqa: F821


def test_set_default_mailbox():
    other = create_new_user()
    mailbox = mailbox_utils.create_mailbox(
        other,
        random_email(),
        use_digit_codes=True,
        send_link=False,
    )
    mailbox.verified = True
    Session.commit()
    user_settings.set_default_mailbox(other, mailbox.id)
    other = User.get(other.id)
    assert other.default_mailbox_id == mailbox.id


def test_cannot_set_unverified():
    mailbox = mailbox_utils.create_mailbox(
        user,
        random_email(),
        use_digit_codes=True,
        send_link=False,
    )
    with pytest.raises(user_settings.CannotSetMailbox):
        user_settings.set_default_mailbox(user, mailbox.id)


def test_cannot_default_other_user_mailbox():
    other = create_new_user()
    mailbox = mailbox_utils.create_mailbox(
        other,
        random_email(),
        use_digit_codes=True,
        send_link=False,
    )
    with pytest.raises(user_settings.CannotSetMailbox):
        user_settings.set_default_mailbox(user, mailbox.id)
