import arrow

from app.models import CoinbaseSubscription, ApiToCookieToken, ApiKey
from cron import notify_manual_sub_end, delete_expired_tokens
from tests.utils import create_new_user


def test_notify_manual_sub_end(flask_client):
    user = create_new_user()

    CoinbaseSubscription.create(
        user_id=user.id, end_at=arrow.now().shift(days=13, hours=2), commit=True
    )

    notify_manual_sub_end()


def test_cleanup_tokens(flask_client):
    user = create_new_user()
    api_key = ApiKey.create(
        user_id=user.id,
        commit=True,
    )
    id_to_clean = ApiToCookieToken.create(
        user_id=user.id,
        api_key_id=api_key.id,
        commit=True,
        created_at=arrow.now().shift(days=-1),
    ).id

    id_to_keep = ApiToCookieToken.create(
        user_id=user.id,
        api_key_id=api_key.id,
        commit=True,
    ).id
    delete_expired_tokens()
    assert ApiToCookieToken.get(id_to_clean) is None
    assert ApiToCookieToken.get(id_to_keep) is not None
