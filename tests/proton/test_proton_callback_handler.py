from arrow import Arrow
from app.account_linking import (
    SLPlan,
    SLPlanType,
)
from app.proton.proton_client import ProtonClient, UserInformation
from app.proton.proton_callback_handler import (
    ProtonCallbackHandler,
    get_proton_partner,
)
from app.models import User, PartnerUser
from app.utils import random_string

from tests.utils import random_email


class MockProtonClient(ProtonClient):
    def __init__(self, user: UserInformation):
        self.user = user

    def get_user(self) -> UserInformation:
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
    assert res.user.partner_user_id == external_id


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

    sa = PartnerUser.get_by(user_id=sl_user.id, partner_id=get_proton_partner().id)
    assert sa is not None
    assert sa.partner_email == user.email
