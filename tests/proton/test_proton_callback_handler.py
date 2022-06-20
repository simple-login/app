from arrow import Arrow
from app.account_linking import (
    SLPlan,
    SLPlanType,
)
from app.proton.proton_client import ProtonClient, UserInformation
from app.proton.proton_callback_handler import (
    ProtonCallbackHandler,
    generate_account_not_allowed_to_log_in,
)
from app.models import User, PartnerUser
from app.proton.utils import get_proton_partner
from app.utils import random_string
from typing import Optional
from tests.utils import random_email


class MockProtonClient(ProtonClient):
    def __init__(self, user: Optional[UserInformation]):
        self.user = user

    def get_user(self) -> Optional[UserInformation]:
        return self.user


def test_proton_callback_handler_unexistant_sl_user():
    email = random_email()
    name = random_string()
    external_id = random_string()
    handler = ProtonCallbackHandler(
        MockProtonClient(
            user=UserInformation(
                email=email,
                name=name,
                id=external_id,
                plan=SLPlan(
                    type=SLPlanType.Premium, expiration=Arrow.utcnow().shift(hours=2)
                ),
            )
        )
    )
    res = handler.handle_login(get_proton_partner())

    assert res.user is not None
    assert res.user.email == email
    assert res.user.name == name
    # Ensure the user is not marked as created from partner
    assert User.FLAG_CREATED_FROM_PARTNER != (
        res.user.flags & User.FLAG_CREATED_FROM_PARTNER
    )
    assert res.user.notification is True
    assert res.user.trial_end is not None

    partner_user = PartnerUser.get_by(
        partner_id=get_proton_partner().id, user_id=res.user.id
    )
    assert partner_user is not None
    assert partner_user.external_user_id == external_id


def test_proton_callback_handler_existant_sl_user():
    email = random_email()
    sl_user = User.create(email, commit=True)

    external_id = random_string()
    user = UserInformation(
        email=email,
        name=random_string(),
        id=external_id,
        plan=SLPlan(type=SLPlanType.Premium, expiration=Arrow.utcnow().shift(hours=2)),
    )
    handler = ProtonCallbackHandler(MockProtonClient(user=user))
    res = handler.handle_login(get_proton_partner())

    assert res.user is not None
    assert res.user.id == sl_user.id
    # Ensure the user is not marked as created from partner
    assert User.FLAG_CREATED_FROM_PARTNER != (
        res.user.flags & User.FLAG_CREATED_FROM_PARTNER
    )
    assert res.user.notification is True
    assert res.user.trial_end is not None

    sa = PartnerUser.get_by(user_id=sl_user.id, partner_id=get_proton_partner().id)
    assert sa is not None
    assert sa.partner_email == user.email


def test_proton_callback_handler_none_user_login():
    handler = ProtonCallbackHandler(MockProtonClient(user=None))
    res = handler.handle_login(get_proton_partner())

    expected = generate_account_not_allowed_to_log_in()
    assert res == expected


def test_proton_callback_handler_none_user_link():
    sl_user = User.create(random_email(), commit=True)
    handler = ProtonCallbackHandler(MockProtonClient(user=None))
    res = handler.handle_link(sl_user, get_proton_partner())

    expected = generate_account_not_allowed_to_log_in()
    assert res == expected
