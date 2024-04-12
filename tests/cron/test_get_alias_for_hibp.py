import arrow
import pytest

import cron
from app.db import Session
from app.models import (
    Alias,
    AppleSubscription,
    PlanEnum,
    CoinbaseSubscription,
    ManualSubscription,
    Subscription,
    PartnerUser,
    PartnerSubscription,
    User,
)
from app.proton.utils import get_proton_partner
from tests.utils import create_new_user, random_token


def test_get_alias_for_free_user_has_no_alias():
    user = create_new_user()
    alias_id = Alias.create_new_random(user).id
    Session.commit()
    aliases = list(
        cron.get_alias_to_check_hibp(arrow.now(), [], alias_id, alias_id + 1)
    )
    assert len(aliases) == 0


def test_get_alias_for_lifetime_with_null_hibp_date():
    user = create_new_user()
    user.lifetime = True
    user.enable_data_breach_check = True
    alias_id = Alias.create_new_random(user).id
    Session.commit()
    aliases = list(
        cron.get_alias_to_check_hibp(arrow.now(), [], alias_id, alias_id + 1)
    )
    assert alias_id == aliases[0].id


def test_get_alias_for_lifetime_with_old_hibp_date():
    user = create_new_user()
    user.lifetime = True
    user.enable_data_breach_check = True
    alias = Alias.create_new_random(user)
    alias.hibp_last_check = arrow.now().shift(days=-1)
    alias_id = alias.id
    Session.commit()
    aliases = list(
        cron.get_alias_to_check_hibp(arrow.now(), [], alias_id, alias_id + 1)
    )
    assert alias_id == aliases[0].id


def create_partner_sub(user: User):
    pu = PartnerUser.create(
        partner_id=get_proton_partner().id,
        partner_email=user.email,
        external_user_id=random_token(10),
        user_id=user.id,
        flush=True,
    )
    PartnerSubscription.create(
        partner_user_id=pu.id, end_at=arrow.utcnow().shift(days=15)
    )


sub_generator_list = [
    lambda u: AppleSubscription.create(
        user_id=u.id,
        expires_date=arrow.now().shift(days=15),
        original_transaction_id=random_token(10),
        receipt_data=random_token(10),
        plan=PlanEnum.monthly,
    ),
    lambda u: CoinbaseSubscription.create(
        user_id=u.id,
        end_at=arrow.now().shift(days=15),
    ),
    lambda u: ManualSubscription.create(
        user_id=u.id,
        end_at=arrow.now().shift(days=15),
    ),
    lambda u: Subscription.create(
        user_id=u.id,
        cancel_url="",
        update_url="",
        subscription_id=random_token(10),
        event_time=arrow.now(),
        next_bill_date=arrow.now().shift(days=15).date(),
        plan=PlanEnum.monthly,
    ),
    create_partner_sub,
]


@pytest.mark.parametrize("sub_generator", sub_generator_list)
def test_get_alias_for_sub(sub_generator):
    user = create_new_user()
    user.enable_data_breach_check = True
    sub_generator(user)
    alias_id = Alias.create_new_random(user).id
    Session.commit()
    aliases = list(
        cron.get_alias_to_check_hibp(arrow.now(), [], alias_id, alias_id + 1)
    )
    assert alias_id == aliases[0].id


def test_disabled_user_is_not_checked():
    user = create_new_user()
    user.lifetime = True
    user.disabled = True
    alias_id = Alias.create_new_random(user).id
    Session.commit()
    aliases = list(
        cron.get_alias_to_check_hibp(arrow.now(), [], alias_id, alias_id + 1)
    )
    assert len(aliases) == 0


def test_skipped_user_is_not_checked():
    user = create_new_user()
    user.lifetime = True
    alias_id = Alias.create_new_random(user).id
    Session.commit()
    aliases = list(
        cron.get_alias_to_check_hibp(arrow.now(), [user.id], alias_id, alias_id + 1)
    )
    assert len(aliases) == 0


def test_already_checked_is_not_checked():
    user = create_new_user()
    user.lifetime = True
    alias = Alias.create_new_random(user)
    alias.hibp_last_check = arrow.now().shift(days=1)
    alias_id = alias.id
    Session.commit()
    aliases = list(
        cron.get_alias_to_check_hibp(arrow.now(), [user.id], alias_id, alias_id + 1)
    )
    assert len(aliases) == 0


def test_outed_in_user_is_checked():
    user = create_new_user()
    user.lifetime = True
    user.enable_data_breach_check = True
    alias_id = Alias.create_new_random(user).id
    Session.commit()
    aliases = list(
        cron.get_alias_to_check_hibp(arrow.now(), [], alias_id, alias_id + 1)
    )
    assert len(aliases) == 1


def test_outed_out_user_is_not_checked():
    user = create_new_user()
    user.lifetime = True
    alias_id = Alias.create_new_random(user).id
    Session.commit()
    aliases = list(
        cron.get_alias_to_check_hibp(arrow.now(), [], alias_id, alias_id + 1)
    )
    assert len(aliases) == 0
