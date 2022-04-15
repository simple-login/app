import arrow

from app.models import CoinbaseSubscription
from cron import notify_manual_sub_end
from tests.utils import create_new_user


def test_notify_manual_sub_end(flask_client):
    user = create_new_user()

    CoinbaseSubscription.create(
        user_id=user.id, end_at=arrow.now().shift(days=13, hours=2), commit=True
    )

    notify_manual_sub_end()
