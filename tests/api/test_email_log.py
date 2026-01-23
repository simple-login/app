from app.models import EmailLog, Alias, Contact
from tests.utils import create_new_user


def test_email_log_message_id_cap(flask_client):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    c0 = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email="c0@example.com",
        reply_email="re0@SL",
        flush=True,
    )
    crap = "a" * 300
    e = EmailLog.create(
        user_id=user.id,
        message_id=crap,
        alias_id=alias.id,
        contact_id=c0.id,
        flush=True,
    )
    assert e.message_id == crap[:250]
