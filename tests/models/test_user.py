import arrow

from app.alias_delete import move_alias_to_trash
from app.constants import JobType
from app.db import Session
from app.models import (
    User,
    Job,
    PartnerSubscription,
    PartnerUser,
    ManualSubscription,
    UserAliasDeleteAction,
    Alias,
)
from app.proton.proton_partner import get_proton_partner
from tests.utils import random_email, random_token, create_new_user


def test_create_from_partner(flask_client):
    user = User.create(email=random_email(), from_partner=True)
    assert User.FLAG_CREATED_FROM_PARTNER == (
        user.flags & User.FLAG_CREATED_FROM_PARTNER
    )
    assert user.notification is False
    assert user.trial_end is None
    assert user.newsletter_alias_id is None
    job = Session.query(Job).order_by(Job.id.desc()).first()
    assert job is not None
    assert job.name == JobType.SEND_PROTON_WELCOME_1.value
    assert job.payload.get("user_id") == user.id


def test_user_created_by_partner(flask_client):
    user_from_partner = User.create(email=random_email(), from_partner=True)
    assert user_from_partner.created_by_partner is True

    regular_user = User.create(email=random_email())
    assert regular_user.created_by_partner is False


def test_user_is_premium(flask_client):
    user = User.create(email=random_email(), from_partner=True)
    assert not user.is_premium()
    partner_user = PartnerUser.create(
        user_id=user.id,
        partner_id=get_proton_partner().id,
        partner_email=user.email,
        external_user_id=random_token(),
        flush=True,
    )
    ps = PartnerSubscription.create(
        partner_user_id=partner_user.id, end_at=arrow.now().shift(years=1), flush=True
    )
    assert user.is_premium()
    assert not user.is_premium(include_partner_subscription=False)
    ManualSubscription.create(user_id=user.id, end_at=ps.end_at)
    assert user.is_premium()
    assert user.is_premium(include_partner_subscription=False)


def test_user_can_create_alias_does_not_count_trashed_ones():
    user = create_new_user(alias_delete_action=UserAliasDeleteAction.MoveToTrash)

    aliases = []
    while user.can_create_new_alias():
        aliases.append(Alias.create_new_random(user))

    assert user.can_create_new_alias() is False

    move_alias_to_trash(aliases[0], user, commit=True)
    assert user.can_create_new_alias() is True
