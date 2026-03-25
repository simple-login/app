from typing import Optional

from arrow import Arrow

from app import config
from app.account_linking import (
    SLPlan,
    SLPlanType,
)
from app.constants import JobType
from app.models import User, PartnerUser, Job, JobState
from app.proton.proton_callback_handler import (
    ProtonCallbackHandler,
    generate_account_not_allowed_to_log_in,
)
from app.proton.proton_client import ProtonClient, UserInformation
from app.proton.proton_partner import get_proton_partner
from app.utils import random_string
from tests.utils import random_email


def setup_module():
    config.SKIP_MX_LOOKUP_ON_CHECK = True


def teardown_module():
    config.SKIP_MX_LOOKUP_ON_CHECK = False


class MockProtonClient(ProtonClient):
    def __init__(self, user: Optional[UserInformation]):
        self.user = user

    def get_user(self) -> Optional[UserInformation]:
        return self.user


def check_initial_sync_job(user: User, expected: bool):
    found = False
    for job in Job.yield_per_query(10).filter_by(
        name=JobType.SEND_ALIAS_CREATION_EVENTS.value,
        state=JobState.ready.value,
    ):
        if job.payload.get("user_id") == user.id:
            found = True
            Job.delete(job.id)
            break
    assert expected == found


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


def test_proton_callback_handler_existing_sl_user():
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
    check_initial_sync_job(res.user, True)


def test_proton_callback_handler_linked_sl_user():
    email = random_email()
    external_id = random_string()
    sl_user = User.create(email, commit=True)
    PartnerUser.create(
        user_id=sl_user.id,
        partner_id=get_proton_partner().id,
        external_user_id=external_id,
        partner_email=email,
        commit=True,
    )

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
    check_initial_sync_job(res.user, False)


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
