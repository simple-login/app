import arrow

from app.db import Session
from app.models import CoinbaseSubscription
from server import handle_coinbase_event
from tests.utils import create_new_user


def test_redirect_login_page(flask_client):
    """Start with a blank database."""

    rv = flask_client.get("/")
    assert rv.status_code == 302
    assert rv.location == "http://sl.test/auth/login"


def test_coinbase_webhook(flask_client):
    r = flask_client.post("/coinbase")
    assert r.status_code == 400


def test_handle_coinbase_event_new_subscription(flask_client):
    user = create_new_user()
    handle_coinbase_event(
        {"data": {"code": "AAAAAA", "metadata": {"user_id": str(user.id)}}}
    )

    assert user.is_paid()
    assert user.is_premium()

    assert CoinbaseSubscription.get_by(user_id=user.id) is not None


def test_handle_coinbase_event_extend_subscription(flask_client):
    user = create_new_user()
    user.trial_end = None
    Session.commit()

    cb = CoinbaseSubscription.create(
        user_id=user.id, end_at=arrow.now().shift(days=-400), commit=True
    )
    assert not cb.is_active()

    assert not user.is_paid()
    assert not user.is_premium()

    handle_coinbase_event(
        {"data": {"code": "AAAAAA", "metadata": {"user_id": str(user.id)}}}
    )

    assert user.is_paid()
    assert user.is_premium()

    assert CoinbaseSubscription.get_by(user_id=user.id) is not None
