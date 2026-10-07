import arrow

import cron
from app.db import Session
from app.mail_sender import mail_sender
from app.models import (
    CoinbaseSubscription,
    ApiToCookieToken,
    ApiKey,
    ManualSubscription,
    PartnerSubscription,
    Subscription,
    User,
    PlanEnum,
)
from tests.utils import create_new_user, create_partner_linked_user, random_token


def _stored_emails_for(user: User) -> list:
    return [e for e in mail_sender.get_stored_emails() if e.envelope_to == user.email]


def _create_partner_subscription(user, partner_user, end_at=None, lifetime=False):
    return PartnerSubscription.create(
        partner_user_id=partner_user.id,
        end_at=end_at,
        lifetime=lifetime,
        commit=True,
    )


def _create_cancelled_paddle_sub(user):
    Subscription.create(
        user_id=user.id,
        cancel_url="cancel_url",
        update_url="update_url",
        subscription_id=random_token(10),
        event_time=arrow.now(),
        next_bill_date=arrow.now().shift(days=2).date(),
        cancelled=True,
        plan=PlanEnum.yearly,
        commit=True,
    )


@mail_sender.store_emails_test_decorator
def test_notify_premium_end_sends_without_partner_sub(flask_client):
    """control: cancelled Paddle sub ending in 2 days -> 1 reminder"""
    user = create_new_user()
    _create_cancelled_paddle_sub(user)
    cron.notify_premium_end()
    assert len(_stored_emails_for(user)) == 1


@mail_sender.store_emails_test_decorator
def test_notify_premium_end_suppressed_by_active_partner_sub(flask_client):
    user, partner_user = create_partner_linked_user()
    _create_partner_subscription(user, partner_user, end_at=arrow.now().shift(days=30))
    _create_cancelled_paddle_sub(user)
    cron.notify_premium_end()
    assert len(_stored_emails_for(user)) == 0


@mail_sender.store_emails_test_decorator
def test_notify_premium_end_not_suppressed_by_expired_partner_sub(flask_client):
    """partner sub expired past the 14-day grace period does not suppress"""
    user, partner_user = create_partner_linked_user()
    _create_partner_subscription(user, partner_user, end_at=arrow.now().shift(days=-30))
    _create_cancelled_paddle_sub(user)
    cron.notify_premium_end()
    assert len(_stored_emails_for(user)) == 1


@mail_sender.store_emails_test_decorator
def test_notify_manual_sub_end_sends_without_partner_sub(flask_client):
    user = create_new_user()
    ManualSubscription.create(
        user_id=user.id,
        end_at=arrow.now().shift(days=13, hours=12),
        commit=True,
    )
    cron.notify_manual_sub_end()
    assert len(_stored_emails_for(user)) == 1


@mail_sender.store_emails_test_decorator
def test_notify_manual_sub_end_suppressed_by_active_partner_sub(flask_client):
    user, partner_user = create_partner_linked_user()
    _create_partner_subscription(user, partner_user, end_at=arrow.now().shift(days=30))
    ManualSubscription.create(
        user_id=user.id,
        end_at=arrow.now().shift(days=13, hours=12),
        commit=True,
    )
    cron.notify_manual_sub_end()
    assert len(_stored_emails_for(user)) == 0


@mail_sender.store_emails_test_decorator
def test_notify_manual_sub_end_suppressed_by_lifetime_partner_sub(flask_client):
    user, partner_user = create_partner_linked_user()
    _create_partner_subscription(user, partner_user, end_at=None, lifetime=True)
    ManualSubscription.create(
        user_id=user.id,
        end_at=arrow.now().shift(days=3, hours=12),
        commit=True,
    )
    cron.notify_manual_sub_end()
    assert len(_stored_emails_for(user)) == 0


@mail_sender.store_emails_test_decorator
def test_notify_manual_sub_end_not_suppressed_by_expired_partner_sub(flask_client):
    user, partner_user = create_partner_linked_user()
    _create_partner_subscription(user, partner_user, end_at=arrow.now().shift(days=-30))
    ManualSubscription.create(
        user_id=user.id,
        end_at=arrow.now().shift(days=13, hours=12),
        commit=True,
    )
    cron.notify_manual_sub_end()
    assert len(_stored_emails_for(user)) == 1


@mail_sender.store_emails_test_decorator
def test_notify_manual_sub_end_control_no_assertion_free(flask_client):
    """real assertions for the previous assertion-free test setup"""
    user = create_new_user()
    CoinbaseSubscription.create(
        user_id=user.id, end_at=arrow.now().shift(days=13, hours=12), commit=True
    )
    cron.notify_manual_sub_end()
    assert len(_stored_emails_for(user)) == 1


@mail_sender.store_emails_test_decorator
def test_notify_coinbase_sub_end_suppressed_by_active_partner_sub(flask_client):
    user, partner_user = create_partner_linked_user()
    _create_partner_subscription(user, partner_user, end_at=arrow.now().shift(days=30))
    CoinbaseSubscription.create(
        user_id=user.id, end_at=arrow.now().shift(days=13, hours=12), commit=True
    )
    cron.notify_manual_sub_end()
    assert len(_stored_emails_for(user)) == 0


@mail_sender.store_emails_test_decorator
def test_notify_coinbase_sub_end_not_suppressed_by_expired_partner_sub(flask_client):
    user, partner_user = create_partner_linked_user()
    _create_partner_subscription(user, partner_user, end_at=arrow.now().shift(days=-30))
    CoinbaseSubscription.create(
        user_id=user.id, end_at=arrow.now().shift(days=3, hours=12), commit=True
    )
    cron.notify_manual_sub_end()
    assert len(_stored_emails_for(user)) == 1


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
