import arrow

from app.models import User, CoinbaseSubscription
from cron import notify_manual_sub_end


def test_notify_manual_sub_end(flask_client):
    user = User.create(
        email="a@b.c",
        password="password",
        name="Test User",
        activated=True,
    )

    CoinbaseSubscription.create(
        user_id=user.id, end_at=arrow.now().shift(days=13, hours=2), commit=True
    )

    notify_manual_sub_end()
