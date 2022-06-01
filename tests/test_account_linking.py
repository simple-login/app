import pytest
from arrow import Arrow

from app.account_linking import (
    process_link_case,
    get_login_strategy,
    UnexistantSlClientStrategy,
    ExistingSlClientStrategy,
    AlreadyLinkedUserStrategy,
    ExistingSlUserLinkedWithDifferentPartnerStrategy,
    SLPlan,
    SLPlanType,
    PartnerUserDto,
    ClientMergeStrategy,
)
from app.proton.proton_callback_handler import get_proton_partner
from app.db import Session
from app.models import PartnerUser, User
from app.utils import random_string

from tests.utils import random_email


def random_partner_user(
    user_id: str = None,
    name: str = None,
    email: str = None,
    plan: SLPlan = None,
) -> PartnerUserDto:
    user_id = user_id if user_id is not None else random_string()
    name = name if name is not None else random_string()
    email = email if email is not None else random_email()
    plan = plan if plan is not None else SLPlanType.Free
    return PartnerUserDto(
        name=name,
        email=email,
        partner_user_id=user_id,
        plan=SLPlan(type=plan, expiration=Arrow.utcnow().shift(hours=2)),
    )


def create_user(email: str = None) -> User:
    email = email if email is not None else random_email()
    user = User.create(email=email)
    Session.commit()
    return user


def create_user_for_partner(partner_user_id: str, email: str = None) -> User:
    email = email if email is not None else random_email()
    user = User.create(email=email)
    user.partner_id = get_proton_partner().id
    user.partner_user_id = partner_user_id

    PartnerUser.create(
        user_id=user.id, partner_id=get_proton_partner().id, partner_email=email
    )
    Session.commit()
    return user


def test_get_strategy_unexistant_sl_user():
    strategy = get_login_strategy(
        partner_user=random_partner_user(),
        sl_user=None,
        partner=get_proton_partner(),
    )
    assert isinstance(strategy, UnexistantSlClientStrategy)


def test_get_strategy_existing_sl_user():
    email = random_email()
    sl_user = User.create(email, commit=True)
    strategy = get_login_strategy(
        partner_user=random_partner_user(email=email),
        sl_user=sl_user,
        partner=get_proton_partner(),
    )
    assert isinstance(strategy, ExistingSlClientStrategy)


def test_get_strategy_already_linked_user():
    email = random_email()
    proton_user_id = random_string()
    sl_user = create_user_for_partner(proton_user_id, email=email)
    strategy = get_login_strategy(
        partner_user=random_partner_user(user_id=proton_user_id, email=email),
        sl_user=sl_user,
        partner=get_proton_partner(),
    )
    assert isinstance(strategy, AlreadyLinkedUserStrategy)


def test_get_strategy_existing_sl_user_linked_with_different_proton_account():
    # In this scenario we have
    # - PartnerUser1 (ID1, email1@proton)
    # - PartnerUser2 (ID2, email2@proton)
    # - SimpleLoginUser1 registered with email1@proton, but linked to account ID2
    # We will try to log in with email1@proton
    email1 = random_email()
    email2 = random_email()
    partner_user_id_1 = random_string()
    partner_user_id_2 = random_string()

    partner_user_1 = random_partner_user(user_id=partner_user_id_1, email=email1)
    partner_user_2 = random_partner_user(user_id=partner_user_id_2, email=email2)

    sl_user = create_user_for_partner(
        partner_user_2.partner_user_id, email=partner_user_1.email
    )
    strategy = get_login_strategy(
        partner_user=partner_user_1,
        sl_user=sl_user,
        partner=get_proton_partner(),
    )
    assert isinstance(strategy, ExistingSlUserLinkedWithDifferentPartnerStrategy)


##
# LINK


def test_link_account_with_proton_account_same_address(flask_client):
    # This is the most basic scenario
    # In this scenario we have:
    # - PartnerUser (email1@partner)
    # - SimpleLoginUser registered with email1@proton
    # We will try to link both accounts

    email = random_email()
    partner_user_id = random_string()
    partner_user = random_partner_user(user_id=partner_user_id, email=email)
    sl_user = create_user(email)

    res = process_link_case(partner_user, sl_user, get_proton_partner())
    assert res is not None
    assert res.user is not None
    assert res.user.id == sl_user.id
    assert res.user.partner_user_id == partner_user_id
    assert res.user.email == email
    assert res.strategy == "Link"

    updated_user = User.get(sl_user.id)
    assert updated_user.partner_id == get_proton_partner().id
    assert updated_user.partner_user_id == partner_user_id


def test_link_account_with_proton_account_different_address(flask_client):
    # In this scenario we have:
    # - ProtonUser (foo@proton)
    # - SimpleLoginUser (bar@somethingelse)
    # We will try to link both accounts
    partner_user_id = random_string()
    partner_user = random_partner_user(user_id=partner_user_id, email=random_email())
    sl_user = create_user()

    res = process_link_case(partner_user, sl_user, get_proton_partner())
    assert res.user.partner_user_id == partner_user_id
    assert res.user.id == sl_user.id
    assert res.user.email == sl_user.email
    assert res.strategy == "Link"

    updated_user = User.get(sl_user.id)
    assert updated_user.partner_id == get_proton_partner().id
    assert updated_user.partner_user_id == partner_user_id


def test_link_account_with_proton_account_same_address_but_linked_to_other_user(
    flask_client,
):
    # In this scenario we have:
    # - PartnerUser (foo@partner)
    # - SimpleLoginUser1 (foo@partner)
    # - SimpleLoginUser2 (other@somethingelse) linked with foo@partner
    # We will unlink SimpleLoginUser2 and link SimpleLoginUser1 with foo@partner
    partner_user_id = random_string()
    partner_email = random_email()
    partner_user = random_partner_user(user_id=partner_user_id, email=partner_email)
    sl_user_1 = create_user(partner_email)
    sl_user_2 = create_user_for_partner(
        partner_user_id, email=random_email()
    )  # User already linked with the proton account

    res = process_link_case(partner_user, sl_user_1, get_proton_partner())
    assert res.user.partner_user_id == partner_user_id
    assert res.user.id == sl_user_1.id
    assert res.user.email == partner_email
    assert res.strategy == "Link"

    updated_user_1 = User.get(sl_user_1.id)
    assert updated_user_1.partner_id == get_proton_partner().id
    assert updated_user_1.partner_user_id == partner_user_id

    updated_user_2 = User.get(sl_user_2.id)
    assert updated_user_2.partner_id is None
    assert updated_user_2.partner_user_id is None


def test_link_account_with_proton_account_different_address_and_linked_to_other_user(
    flask_client,
):
    # In this scenario we have:
    # - PartnerUser (foo@partner)
    # - SimpleLoginUser1 (bar@somethingelse)
    # - SimpleLoginUser2 (other@somethingelse) linked with foo@partner
    # We will unlink SimpleLoginUser2 and link SimpleLoginUser1 with foo@partner
    partner_user_id = random_string()
    partner_user = random_partner_user(user_id=partner_user_id, email=random_email())
    sl_user_1 = create_user(random_email())
    sl_user_2 = create_user_for_partner(
        partner_user_id, email=random_email()
    )  # User already linked with the proton account

    res = process_link_case(partner_user, sl_user_1, get_proton_partner())
    assert res.user.partner_user_id == partner_user_id
    assert res.user.id == sl_user_1.id
    assert res.user.email == sl_user_1.email
    assert res.strategy == "Link"

    updated_user_1 = User.get(sl_user_1.id)
    assert updated_user_1.partner_id == get_proton_partner().id
    assert updated_user_1.partner_user_id == partner_user_id
    partner_user_1 = PartnerUser.get_by(
        user_id=sl_user_1.id, partner_id=get_proton_partner().id
    )
    assert partner_user_1 is not None
    assert partner_user_1.partner_email == partner_user.email

    updated_user_2 = User.get(sl_user_2.id)
    assert updated_user_2.partner_id is None
    assert updated_user_2.partner_user_id is None
    partner_user_2 = PartnerUser.get_by(
        user_id=sl_user_2.id, partner_id=get_proton_partner().id
    )
    assert partner_user_2 is None


def test_cannot_create_instance_of_base_strategy():
    with pytest.raises(Exception):
        ClientMergeStrategy(random_partner_user(), None, get_proton_partner())
