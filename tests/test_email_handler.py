from app.models import User, Alias, AuthorizedAddress
from email_handler import get_mailbox_from_mail_from


def test_get_mailbox_from_mail_from(flask_client):
    user = User.create(
        email="a@b.c",
        password="password",
        name="Test User",
        activated=True,
        commit=True,
    )
    alias = Alias.create(
        user_id=user.id,
        email="first@d1.test",
        mailbox_id=user.default_mailbox_id,
        commit=True,
    )

    mb = get_mailbox_from_mail_from("a@b.c", alias)
    assert mb.email == "a@b.c"

    mb = get_mailbox_from_mail_from("unauthorized@gmail.com", alias)
    assert mb is None

    # authorized address
    AuthorizedAddress.create(
        user_id=user.id,
        mailbox_id=user.default_mailbox_id,
        email="unauthorized@gmail.com",
        commit=True,
    )
    mb = get_mailbox_from_mail_from("unauthorized@gmail.com", alias)
    assert mb.email == "a@b.c"
