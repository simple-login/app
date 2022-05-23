import pytest

from app.db import Session
from app.proton.proton_client import ProtonClient, UserInformation, ProtonPlan
from app.proton.proton_callback_handler import (
    ProtonCallbackHandler,
    get_proton_partner,
    get_login_strategy,
    process_link_case,
    ProtonUser,
    UnexistantSlClientStrategy,
    ExistingSlClientStrategy,
    AlreadyLinkedUserStrategy,
    ExistingSlUserLinkedWithDifferentProtonAccountStrategy,
    ClientMergeStrategy,
)
from app.models import User, PartnerUser
from app.utils import random_string


class MockProtonClient(ProtonClient):
    def __init__(self, user: UserInformation, plan: ProtonPlan, organization: dict):
        self.user = user
        self.plan = plan
        self.organization = organization

    def get_organization(self) -> dict:
        return self.organization

    def get_user(self) -> UserInformation:
        return self.user

    def get_plan(self) -> ProtonPlan:
        return self.plan


def random_email() -> str:
    return "{rand}@{rand}.com".format(rand=random_string(20))


def random_proton_user(
    user_id: str = None,
    name: str = None,
    email: str = None,
    plan: ProtonPlan = None,
) -> ProtonUser:
    user_id = user_id if user_id is not None else random_string()
    name = name if name is not None else random_string()
    email = (
        email
        if email is not None
        else "{rand}@{rand}.com".format(rand=random_string(20))
    )
    plan = plan if plan is not None else ProtonPlan.Free
    return ProtonUser(id=user_id, name=name, email=email, plan=plan)


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


def test_proton_callback_handler_unexistant_sl_user():
    email = random_email()
    name = random_string()
    external_id = random_string()
    user = UserInformation(email=email, name=name, id=external_id)
    mock_client = MockProtonClient(
        user=user, plan=ProtonPlan.Professional, organization={}
    )
    handler = ProtonCallbackHandler(mock_client)
    res = handler.handle_login(get_proton_partner())

    assert res.user is not None
    assert res.user.email == email
    assert res.user.name == name
    assert res.user.partner_user_id == external_id


def test_proton_callback_handler_existant_sl_user():
    email = random_email()
    sl_user = User.create(email, commit=True)

    external_id = random_string()
    user = UserInformation(email=email, name=random_string(), id=external_id)
    mock_client = MockProtonClient(
        user=user, plan=ProtonPlan.Professional, organization={}
    )
    handler = ProtonCallbackHandler(mock_client)
    res = handler.handle_login(get_proton_partner())

    assert res.user is not None
    assert res.user.id == sl_user.id

    sa = PartnerUser.get_by(user_id=sl_user.id, partner_id=get_proton_partner().id)
    assert sa is not None
    assert sa.partner_email == user.email


def test_get_strategy_unexistant_sl_user():
    strategy = get_login_strategy(
        proton_user=random_proton_user(),
        sl_user=None,
        partner=get_proton_partner(),
    )
    assert isinstance(strategy, UnexistantSlClientStrategy)


def test_get_strategy_existing_sl_user():
    email = random_email()
    sl_user = User.create(email, commit=True)
    strategy = get_login_strategy(
        proton_user=random_proton_user(email=email),
        sl_user=sl_user,
        partner=get_proton_partner(),
    )
    assert isinstance(strategy, ExistingSlClientStrategy)


def test_get_strategy_already_linked_user():
    email = random_email()
    proton_user_id = random_string()
    sl_user = create_user_for_partner(proton_user_id, email=email)
    strategy = get_login_strategy(
        proton_user=random_proton_user(user_id=proton_user_id, email=email),
        sl_user=sl_user,
        partner=get_proton_partner(),
    )
    assert isinstance(strategy, AlreadyLinkedUserStrategy)


def test_get_strategy_existing_sl_user_linked_with_different_proton_account():
    # In this scenario we have
    # - ProtonUser1 (ID1, email1@proton)
    # - ProtonUser2 (ID2, email2@proton)
    # - SimpleLoginUser1 registered with email1@proton, but linked to account ID2
    # We will try to log in with email1@proton
    email1 = random_email()
    email2 = random_email()
    proton_user_id_1 = random_string()
    proton_user_id_2 = random_string()

    proton_user_1 = random_proton_user(user_id=proton_user_id_1, email=email1)
    proton_user_2 = random_proton_user(user_id=proton_user_id_2, email=email2)

    sl_user = create_user_for_partner(proton_user_2.id, email=proton_user_1.email)
    strategy = get_login_strategy(
        proton_user=proton_user_1,
        sl_user=sl_user,
        partner=get_proton_partner(),
    )
    assert isinstance(strategy, ExistingSlUserLinkedWithDifferentProtonAccountStrategy)


##
# LINK


def test_link_account_with_proton_account_same_address(flask_client):
    # This is the most basic scenario
    # In this scenario we have:
    # - ProtonUser (email1@proton)
    # - SimpleLoginUser registered with email1@proton
    # We will try to link both accounts

    email = random_email()
    proton_user_id = random_string()
    proton_user = random_proton_user(user_id=proton_user_id, email=email)
    sl_user = create_user(email)

    res = process_link_case(proton_user, sl_user, get_proton_partner())
    assert res.redirect_to_login is False
    assert res.redirect is not None
    assert res.flash_category == "success"
    assert res.flash_message is not None

    updated_user = User.get(sl_user.id)
    assert updated_user.partner_id == get_proton_partner().id
    assert updated_user.partner_user_id == proton_user_id


def test_link_account_with_proton_account_different_address(flask_client):
    # In this scenario we have:
    # - ProtonUser (foo@proton)
    # - SimpleLoginUser (bar@somethingelse)
    # We will try to link both accounts
    proton_user_id = random_string()
    proton_user = random_proton_user(user_id=proton_user_id, email=random_email())
    sl_user = create_user()

    res = process_link_case(proton_user, sl_user, get_proton_partner())
    assert res.redirect_to_login is False
    assert res.redirect is not None
    assert res.flash_category == "success"
    assert res.flash_message is not None

    updated_user = User.get(sl_user.id)
    assert updated_user.partner_id == get_proton_partner().id
    assert updated_user.partner_user_id == proton_user_id


def test_link_account_with_proton_account_same_address_but_linked_to_other_user(
    flask_client,
):
    # In this scenario we have:
    # - ProtonUser (foo@proton)
    # - SimpleLoginUser1 (foo@proton)
    # - SimpleLoginUser2 (other@somethingelse) linked with foo@proton
    # We will unlink SimpleLoginUser2 and link SimpleLoginUser1 with foo@proton
    proton_user_id = random_string()
    proton_email = random_email()
    proton_user = random_proton_user(user_id=proton_user_id, email=proton_email)
    sl_user_1 = create_user(proton_email)
    sl_user_2 = create_user_for_partner(
        proton_user_id, email=random_email()
    )  # User already linked with the proton account

    res = process_link_case(proton_user, sl_user_1, get_proton_partner())
    assert res.redirect_to_login is False
    assert res.redirect is not None
    assert res.flash_category == "success"
    assert res.flash_message is not None

    updated_user_1 = User.get(sl_user_1.id)
    assert updated_user_1.partner_id == get_proton_partner().id
    assert updated_user_1.partner_user_id == proton_user_id

    updated_user_2 = User.get(sl_user_2.id)
    assert updated_user_2.partner_id is None
    assert updated_user_2.partner_user_id is None


def test_link_account_with_proton_account_different_address_and_linked_to_other_user(
    flask_client,
):
    # In this scenario we have:
    # - ProtonUser (foo@proton)
    # - SimpleLoginUser1 (bar@somethingelse)
    # - SimpleLoginUser2 (other@somethingelse) linked with foo@proton
    # We will unlink SimpleLoginUser2 and link SimpleLoginUser1 with foo@proton
    proton_user_id = random_string()
    proton_user = random_proton_user(user_id=proton_user_id, email=random_email())
    sl_user_1 = create_user(random_email())
    sl_user_2 = create_user_for_partner(
        proton_user_id, email=random_email()
    )  # User already linked with the proton account

    res = process_link_case(proton_user, sl_user_1, get_proton_partner())
    assert res.redirect_to_login is False
    assert res.redirect is not None
    assert res.flash_category == "success"
    assert res.flash_message is not None

    updated_user_1 = User.get(sl_user_1.id)
    assert updated_user_1.partner_id == get_proton_partner().id
    assert updated_user_1.partner_user_id == proton_user_id
    partner_user_1 = PartnerUser.get_by(
        user_id=sl_user_1.id, partner_id=get_proton_partner().id
    )
    assert partner_user_1 is not None
    assert partner_user_1.partner_email == proton_user.email

    updated_user_2 = User.get(sl_user_2.id)
    assert updated_user_2.partner_id is None
    assert updated_user_2.partner_user_id is None
    partner_user_2 = PartnerUser.get_by(
        user_id=sl_user_2.id, partner_id=get_proton_partner().id
    )
    assert partner_user_2 is None


def test_cannot_create_instance_of_base_strategy():
    with pytest.raises(Exception):
        ClientMergeStrategy(random_proton_user(), None, get_proton_partner())
