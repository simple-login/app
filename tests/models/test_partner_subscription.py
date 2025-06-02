from arrow import Arrow
from app.models import Partner, PartnerUser, PartnerSubscription
from app.utils import random_string
from tests.utils import create_new_user, random_email


def test_generate_partner_subscription(flask_client):
    external_user_id = random_string()
    partner = Partner.create(
        name=random_string(10),
        contact_email=random_email(),
        commit=True,
    )
    user = create_new_user()
    partner_user = PartnerUser.create(
        user_id=user.id,
        partner_id=partner.id,
        partner_email=random_email(),
        external_user_id=external_user_id,
        commit=True,
    )

    subs = PartnerSubscription.create(
        partner_user_id=partner_user.id,
        end_at=Arrow.utcnow().shift(hours=1),
        commit=True,
    )

    retrieved_subscription = PartnerSubscription.find_by_user_id(user.id)

    assert retrieved_subscription is not None
    assert retrieved_subscription.id == subs.id

    assert user.lifetime_or_active_subscription() is True


def test_partner_subscription_for_not_partner_subscription_user(flask_client):
    unexistant_subscription = PartnerSubscription.find_by_user_id(999999)
    assert unexistant_subscription is None
