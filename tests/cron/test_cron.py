import arrow

import cron
from app.db import Session
from app.models import CoinbaseSubscription, ApiToCookieToken, ApiKey, User
from tests.utils import create_new_user


def test_notify_manual_sub_end(flask_client):
    user = create_new_user()
    CoinbaseSubscription.create(
        user_id=user.id, end_at=arrow.now().shift(days=13, hours=2), commit=True
    )
    cron.notify_manual_sub_end()


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
    cron.delete_expired_tokens()
    assert ApiToCookieToken.get(id_to_clean) is None
    assert ApiToCookieToken.get(id_to_keep) is not None


def test_cleanup_users():
    u_delete_none_id = create_new_user().id
    u_delete_grace_has_expired = create_new_user()
    u_delete_grace_has_expired_id = u_delete_grace_has_expired.id
    u_delete_grace_has_not_expired = create_new_user()
    u_delete_grace_has_not_expired_id = u_delete_grace_has_not_expired.id
    now = arrow.now()
    u_delete_grace_has_expired.delete_on = now.shift(days=-(cron.DELETE_GRACE_DAYS + 1))
    u_delete_grace_has_not_expired.delete_on = now.shift(
        days=-(cron.DELETE_GRACE_DAYS - 1)
    )
    Session.flush()
    cron.clear_users_scheduled_to_be_deleted()
    assert User.get(u_delete_none_id) is not None
    assert User.get(u_delete_grace_has_not_expired_id) is not None
    assert User.get(u_delete_grace_has_expired_id) is None
