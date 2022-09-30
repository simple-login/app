import arrow

from app import paddle_callback
from app.db import Session
from app.mail_sender import mail_sender
from app.models import Subscription, PlanEnum
from tests.utils import create_new_user, random_token


@mail_sender.store_emails_test_decorator
def test_failed_payments():
    user = create_new_user()
    paddle_sub_id = random_token()
    sub = Subscription.create(
        user_id=user.id,
        cancel_url="https://checkout.paddle.com/subscription/cancel?user=1234",
        update_url="https://checkout.paddle.com/subscription/update?user=1234",
        subscription_id=paddle_sub_id,
        event_time=arrow.now(),
        next_bill_date=arrow.now().shift(days=10).date(),
        plan=PlanEnum.monthly,
        commit=True,
    )
    Session.commit()

    paddle_callback.failed_payment(sub, paddle_sub_id)

    sub = Subscription.get_by(subscription_id=paddle_sub_id)
    assert sub.cancelled

    assert 1 == len(mail_sender.get_stored_emails())
    mail_sent = mail_sender.get_stored_emails()[0]
    assert mail_sent.envelope_to == user.email
