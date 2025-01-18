import arrow

from app.account_linking import (
    SLPlan,
    SLPlanType,
    set_plan_for_partner_user,
)
from app.db import Session
from app.models import User, PartnerUser, PartnerSubscription
from app.proton.utils import get_proton_partner
from app.utils import random_string
from tests.utils import random_email

partner_user_id: int = 0


def setup_module():
    global partner_user_id
    email = random_email()
    external_id = random_string()
    sl_user = User.create(email, commit=True)
    partner_user_id = PartnerUser.create(
        user_id=sl_user.id,
        partner_id=get_proton_partner().id,
        external_user_id=external_id,
        partner_email=email,
        commit=True,
    ).id


def setup_function(func):
    Session.query(PartnerSubscription).delete()


def test_free_plan_removes_sub():
    pu = PartnerUser.get(partner_user_id)
    sub_id = PartnerSubscription.create(
        partner_user_id=partner_user_id,
        end_at=arrow.utcnow(),
        lifetime=False,
        commit=True,
    ).id
    set_plan_for_partner_user(pu, plan=SLPlan(type=SLPlanType.Free, expiration=None))
    assert PartnerSubscription.get(sub_id) is None


def test_premium_plan_updates_expiration():
    pu = PartnerUser.get(partner_user_id)
    sub_id = PartnerSubscription.create(
        partner_user_id=partner_user_id,
        end_at=arrow.utcnow(),
        lifetime=False,
        commit=True,
    ).id
    new_expiration = arrow.utcnow().shift(days=+10)
    set_plan_for_partner_user(
        pu, plan=SLPlan(type=SLPlanType.Premium, expiration=new_expiration)
    )
    assert PartnerSubscription.get(sub_id).end_at == new_expiration


def test_premium_plan_creates_sub():
    pu = PartnerUser.get(partner_user_id)
    new_expiration = arrow.utcnow().shift(days=+10)
    set_plan_for_partner_user(
        pu, plan=SLPlan(type=SLPlanType.Premium, expiration=new_expiration)
    )
    assert (
        PartnerSubscription.get_by(partner_user_id=partner_user_id).end_at
        == new_expiration
    )


def test_lifetime_creates_sub():
    pu = PartnerUser.get(partner_user_id)
    new_expiration = arrow.utcnow().shift(days=+10)
    set_plan_for_partner_user(
        pu, plan=SLPlan(type=SLPlanType.PremiumLifetime, expiration=new_expiration)
    )
    sub = PartnerSubscription.get_by(partner_user_id=partner_user_id)
    assert sub is not None
    assert sub.end_at is None
    assert sub.lifetime


def test_lifetime_updates_sub():
    pu = PartnerUser.get(partner_user_id)
    sub_id = PartnerSubscription.create(
        partner_user_id=partner_user_id,
        end_at=arrow.utcnow(),
        lifetime=False,
        commit=True,
    ).id
    set_plan_for_partner_user(
        pu, plan=SLPlan(type=SLPlanType.PremiumLifetime, expiration=arrow.utcnow())
    )
    sub = PartnerSubscription.get(sub_id)
    assert sub is not None
    assert sub.end_at is None
    assert sub.lifetime
