import pytest
from arrow import Arrow

from app.account_linking import (
    process_link_case,
    process_login_case,
    get_login_strategy,
    ensure_partner_user_exists_for_user,
    NewUserStrategy,
    ExistingUnlinkedUserStrategy,
    LinkedWithAnotherPartnerUserStrategy,
    SLPlan,
    SLPlanType,
    PartnerLinkRequest,
    ClientMergeStrategy,
)
from app.db import Session
from app.errors import AccountAlreadyLinkedToAnotherPartnerException
from app.models import Partner, PartnerUser, User
from app.proton.utils import get_proton_partner
from app.utils import random_string
from tests.utils import random_email


def random_link_request(
    external_user_id: str = None,
    name: str = None,
    email: str = None,
    plan: SLPlan = None,
    from_partner: bool = False,
) -> PartnerLinkRequest:
    external_user_id = (
        external_user_id if external_user_id is not None else random_string()
    )
    name = name if name is not None else random_string()
    email = email if email is not None else random_email()
    plan = plan if plan is not None else SLPlanType.Free
    return PartnerLinkRequest(
        name=name,
        email=email,
        external_user_id=external_user_id,
        plan=SLPlan(type=plan, expiration=Arrow.utcnow().shift(hours=2)),
        from_partner=from_partner,
    )


def create_user(email: str = None) -> User:
    email = email if email is not None else random_email()
    user = User.create(email=email)
    Session.commit()
    return user


def create_user_for_partner(external_user_id: str, email: str = None) -> User:
    email = email if email is not None else random_email()
    user = User.create(email=email)

    PartnerUser.create(
        user_id=user.id,
        partner_id=get_proton_partner().id,
        partner_email=email,
        external_user_id=external_user_id,
    )
    Session.commit()
    return user


def test_get_strategy_unexistant_sl_user():
    strategy = get_login_strategy(
        link_request=random_link_request(),
        user=None,
        partner=get_proton_partner(),
    )
    assert isinstance(strategy, NewUserStrategy)


def test_login_case_from_partner():
    partner = get_proton_partner()
    res = process_login_case(
        random_link_request(
            external_user_id=random_string(),
            from_partner=True,
        ),
        partner,
    )

    assert res.strategy == NewUserStrategy.__name__
    assert res.user is not None
    assert User.FLAG_CREATED_FROM_PARTNER == (
        res.user.flags & User.FLAG_CREATED_FROM_PARTNER
    )
    assert res.user.activated is True


def test_login_case_from_partner_with_uppercase_email():
    partner = get_proton_partner()
    link_request = random_link_request(
        external_user_id=random_string(),
        from_partner=True,
    )
    link_request.email = link_request.email.upper()
    res = process_login_case(link_request, partner)

    assert res.strategy == NewUserStrategy.__name__
    assert res.user is not None
    assert res.user.email == link_request.email.lower()
    assert User.FLAG_CREATED_FROM_PARTNER == (
        res.user.flags & User.FLAG_CREATED_FROM_PARTNER
    )
    assert res.user.activated is True


def test_login_case_from_web():
    partner = get_proton_partner()
    res = process_login_case(
        random_link_request(
            external_user_id=random_string(),
            from_partner=False,
        ),
        partner,
    )

    assert res.strategy == NewUserStrategy.__name__
    assert res.user is not None
    assert 0 == (res.user.flags & User.FLAG_CREATED_FROM_PARTNER)
    assert res.user.activated is True


def test_get_strategy_existing_sl_user():
    email = random_email()
    user = User.create(email, commit=True)
    strategy = get_login_strategy(
        link_request=random_link_request(email=email),
        user=user,
        partner=get_proton_partner(),
    )
    assert isinstance(strategy, ExistingUnlinkedUserStrategy)


def test_get_strategy_existing_sl_user_with_uppercase_email():
    email = random_email()
    user = User.create(email, commit=True)
    strategy = get_login_strategy(
        link_request=random_link_request(email=email.upper()),
        user=user,
        partner=get_proton_partner(),
    )
    assert isinstance(strategy, ExistingUnlinkedUserStrategy)


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

    link_request_1 = random_link_request(
        external_user_id=partner_user_id_1, email=email1
    )
    link_request_2 = random_link_request(
        external_user_id=partner_user_id_2, email=email2
    )

    user = create_user_for_partner(
        link_request_2.external_user_id, email=link_request_1.email
    )
    strategy = get_login_strategy(
        link_request=link_request_1,
        user=user,
        partner=get_proton_partner(),
    )
    assert isinstance(strategy, LinkedWithAnotherPartnerUserStrategy)


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
    link_request = random_link_request(external_user_id=partner_user_id, email=email)
    user = create_user(email)

    res = process_link_case(link_request, user, get_proton_partner())
    assert res is not None
    assert res.user is not None
    assert res.user.id == user.id
    assert res.user.email == email
    assert res.strategy == "Link"

    partner_user = PartnerUser.get_by(
        partner_id=get_proton_partner().id, user_id=user.id
    )
    assert partner_user.partner_id == get_proton_partner().id
    assert partner_user.external_user_id == partner_user_id


def test_link_account_with_proton_account_different_address(flask_client):
    # In this scenario we have:
    # - ProtonUser (foo@proton)
    # - SimpleLoginUser (bar@somethingelse)
    # We will try to link both accounts
    partner_user_id = random_string()
    link_request = random_link_request(
        external_user_id=partner_user_id, email=random_email()
    )
    user = create_user()

    res = process_link_case(link_request, user, get_proton_partner())
    assert res.user.id == user.id
    assert res.user.email == user.email
    assert res.strategy == "Link"

    partner_user = PartnerUser.get_by(
        partner_id=get_proton_partner().id, user_id=user.id
    )
    assert partner_user.partner_id == get_proton_partner().id
    assert partner_user.external_user_id == partner_user_id


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
    link_request = random_link_request(
        external_user_id=partner_user_id, email=partner_email
    )
    sl_user_1 = create_user(partner_email)
    sl_user_2 = create_user_for_partner(
        partner_user_id, email=random_email()
    )  # User already linked with the proton account

    res = process_link_case(link_request, sl_user_1, get_proton_partner())
    assert res.user.id == sl_user_1.id
    assert res.user.email == partner_email
    assert res.strategy == "Link"

    partner_user = PartnerUser.get_by(
        partner_id=get_proton_partner().id, user_id=sl_user_1.id
    )
    assert partner_user.partner_id == get_proton_partner().id
    assert partner_user.external_user_id == partner_user_id

    partner_user = PartnerUser.get_by(
        partner_id=get_proton_partner().id, user_id=sl_user_2.id
    )
    assert partner_user is None


def test_link_account_with_proton_account_different_address_and_linked_to_other_user(
    flask_client,
):
    # In this scenario we have:
    # - PartnerUser (foo@partner)
    # - SimpleLoginUser1 (bar@somethingelse)
    # - SimpleLoginUser2 (other@somethingelse) linked with foo@partner
    # We will unlink SimpleLoginUser2 and link SimpleLoginUser1 with foo@partner
    partner_user_id = random_string()
    link_request = random_link_request(
        external_user_id=partner_user_id, email=random_email()
    )
    sl_user_1 = create_user(random_email())
    sl_user_2 = create_user_for_partner(
        partner_user_id, email=random_email()
    )  # User already linked with the proton account

    res = process_link_case(link_request, sl_user_1, get_proton_partner())
    assert res.user.id == sl_user_1.id
    assert res.user.email == sl_user_1.email
    assert res.strategy == "Link"

    partner_user_1 = PartnerUser.get_by(
        user_id=sl_user_1.id, partner_id=get_proton_partner().id
    )
    assert partner_user_1 is not None
    assert partner_user_1.partner_email == sl_user_2.email
    assert partner_user_1.partner_id == get_proton_partner().id
    assert partner_user_1.external_user_id == partner_user_id

    partner_user_2 = PartnerUser.get_by(
        user_id=sl_user_2.id, partner_id=get_proton_partner().id
    )
    assert partner_user_2 is None


def test_cannot_create_instance_of_base_strategy():
    with pytest.raises(Exception):
        ClientMergeStrategy(random_link_request(), None, get_proton_partner())


def test_ensure_partner_user_exists_for_user_raises_exception_when_linked_to_another_partner():
    # Setup test data:
    # - partner_1
    # - partner_2
    # - user
    user_email = random_email()
    user = create_user(user_email)
    external_id_1 = random_string()
    partner_1 = Partner.create(
        name=random_string(),
        contact_email=random_email(),
    )
    external_id_2 = random_string()
    partner_2 = Partner.create(
        name=random_string(),
        contact_email=random_email(),
    )

    # Link user with partner_1
    ensure_partner_user_exists_for_user(
        PartnerLinkRequest(
            name=random_string(),
            email=user_email,
            external_user_id=external_id_1,
            plan=SLPlan(type=SLPlanType.Free, expiration=None),
            from_partner=False,
        ),
        user,
        partner_1,
    )

    # Try to link user with partner_2 and confirm the exception
    with pytest.raises(AccountAlreadyLinkedToAnotherPartnerException):
        ensure_partner_user_exists_for_user(
            PartnerLinkRequest(
                name=random_string(),
                email=user_email,
                external_user_id=external_id_2,
                plan=SLPlan(type=SLPlanType.Free, expiration=None),
                from_partner=False,
            ),
            user,
            partner_2,
        )


def test_link_account_with_uppercase(flask_client):
    # In this scenario we have:
    # - PartnerUser (email1@partner)
    # - SimpleLoginUser registered with email1@proton
    # We will try to link both accounts with an uppercase email

    email = random_email()
    partner_user_id = random_string()
    link_request = random_link_request(
        external_user_id=partner_user_id, email=email.upper()
    )
    user = create_user(email)

    res = process_link_case(link_request, user, get_proton_partner())
    assert res is not None
    assert res.user is not None
    assert res.user.id == user.id
    assert res.user.email == email
    assert res.strategy == "Link"

    partner_user = PartnerUser.get_by(
        partner_id=get_proton_partner().id, user_id=user.id
    )
    assert partner_user.partner_id == get_proton_partner().id
    assert partner_user.external_user_id == partner_user_id
