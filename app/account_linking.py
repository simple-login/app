from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from arrow import Arrow
from newrelic import agent

from app.db import Session
from app.email_utils import send_welcome_email
from app.utils import sanitize_email
from app.errors import AccountAlreadyLinkedToAnotherPartnerException
from app.log import LOG
from app.models import (
    PartnerSubscription,
    Partner,
    PartnerUser,
    User,
)
from app.utils import random_string


class SLPlanType(Enum):
    Free = 1
    Premium = 2


@dataclass
class SLPlan:
    type: SLPlanType
    expiration: Optional[Arrow]


@dataclass
class PartnerLinkRequest:
    name: str
    email: str
    external_user_id: str
    plan: SLPlan
    from_partner: bool


@dataclass
class LinkResult:
    user: User
    strategy: str


def set_plan_for_partner_user(partner_user: PartnerUser, plan: SLPlan):
    sub = PartnerSubscription.get_by(partner_user_id=partner_user.id)
    if plan.type == SLPlanType.Free:
        if sub is not None:
            LOG.i(
                f"Deleting partner_subscription [user_id={partner_user.user_id}] [partner_id={partner_user.partner_id}]"
            )
            PartnerSubscription.delete(sub.id)
            agent.record_custom_event("PlanChange", {"plan": "free"})
    else:
        if sub is None:
            LOG.i(
                f"Creating partner_subscription [user_id={partner_user.user_id}] [partner_id={partner_user.partner_id}]"
            )
            PartnerSubscription.create(
                partner_user_id=partner_user.id,
                end_at=plan.expiration,
            )
            agent.record_custom_event("PlanChange", {"plan": "premium", "type": "new"})
        else:
            if sub.end_at != plan.expiration:
                LOG.i(
                    f"Updating partner_subscription [user_id={partner_user.user_id}] [partner_id={partner_user.partner_id}]"
                )
                agent.record_custom_event(
                    "PlanChange", {"plan": "premium", "type": "extension"}
                )
                sub.end_at = plan.expiration
    Session.commit()


def set_plan_for_user(user: User, plan: SLPlan, partner: Partner):
    partner_user = PartnerUser.get_by(partner_id=partner.id, user_id=user.id)
    if partner_user is None:
        return
    return set_plan_for_partner_user(partner_user, plan)


def ensure_partner_user_exists_for_user(
    link_request: PartnerLinkRequest, sl_user: User, partner: Partner
) -> PartnerUser:
    # Find partner_user by user_id
    res = PartnerUser.get_by(user_id=sl_user.id)
    if res and res.partner_id != partner.id:
        raise AccountAlreadyLinkedToAnotherPartnerException()
    if not res:
        res = PartnerUser.create(
            user_id=sl_user.id,
            partner_id=partner.id,
            partner_email=link_request.email,
            external_user_id=link_request.external_user_id,
        )
        Session.commit()
        LOG.i(
            f"Created new partner_user for partner:{partner.id} user:{sl_user.id} external_user_id:{link_request.external_user_id}. PartnerUser.id is {res.id}"
        )
    return res


class ClientMergeStrategy(ABC):
    def __init__(
        self,
        link_request: PartnerLinkRequest,
        user: Optional[User],
        partner: Partner,
    ):
        if self.__class__ == ClientMergeStrategy:
            raise RuntimeError("Cannot directly instantiate a ClientMergeStrategy")
        self.link_request = link_request
        self.user = user
        self.partner = partner

    @abstractmethod
    def process(self) -> LinkResult:
        pass


class NewUserStrategy(ClientMergeStrategy):
    def process(self) -> LinkResult:
        # Will create a new SL User with a random password
        new_user = User.create(
            email=self.link_request.email,
            name=self.link_request.name,
            password=random_string(20),
            activated=True,
            from_partner=self.link_request.from_partner,
        )
        partner_user = PartnerUser.create(
            user_id=new_user.id,
            partner_id=self.partner.id,
            external_user_id=self.link_request.external_user_id,
            partner_email=self.link_request.email,
        )
        LOG.i(
            f"Created new user for login request for partner:{self.partner.id} external_user_id:{self.link_request.external_user_id}. New user {new_user.id} partner_user:{partner_user.id}"
        )
        set_plan_for_partner_user(
            partner_user,
            self.link_request.plan,
        )
        Session.commit()

        if not new_user.created_by_partner:
            send_welcome_email(new_user)

        agent.record_custom_event("PartnerUserCreation", {"partner": self.partner.name})

        return LinkResult(
            user=new_user,
            strategy=self.__class__.__name__,
        )


class ExistingUnlinkedUserStrategy(ClientMergeStrategy):
    def process(self) -> LinkResult:

        partner_user = ensure_partner_user_exists_for_user(
            self.link_request, self.user, self.partner
        )
        set_plan_for_partner_user(partner_user, self.link_request.plan)

        return LinkResult(
            user=self.user,
            strategy=self.__class__.__name__,
        )


class LinkedWithAnotherPartnerUserStrategy(ClientMergeStrategy):
    def process(self) -> LinkResult:
        raise AccountAlreadyLinkedToAnotherPartnerException()


def get_login_strategy(
    link_request: PartnerLinkRequest, user: Optional[User], partner: Partner
) -> ClientMergeStrategy:
    if user is None:
        # We couldn't find any SimpleLogin user with the requested e-mail
        return NewUserStrategy(link_request, user, partner)
    # Check if user is already linked with another partner_user
    other_partner_user = PartnerUser.get_by(partner_id=partner.id, user_id=user.id)
    if other_partner_user is not None:
        return LinkedWithAnotherPartnerUserStrategy(link_request, user, partner)
    # There is a SimpleLogin user with the partner_user's e-mail
    return ExistingUnlinkedUserStrategy(link_request, user, partner)


def process_login_case(
    link_request: PartnerLinkRequest, partner: Partner
) -> LinkResult:
    # Sanitize email just in case
    link_request.email = sanitize_email(link_request.email)
    # Try to find a SimpleLogin user registered with that partner user id
    partner_user = PartnerUser.get_by(
        partner_id=partner.id, external_user_id=link_request.external_user_id
    )
    if partner_user is None:
        # We didn't find any SimpleLogin user registered with that partner user id
        # Try to find it using the partner's e-mail address
        user = User.get_by(email=link_request.email)
        return get_login_strategy(link_request, user, partner).process()
    else:
        # We found the SL user registered with that partner user id
        # We're done
        set_plan_for_partner_user(partner_user, link_request.plan)
        # It's the same user. No need to do anything
        return LinkResult(
            user=partner_user.user,
            strategy="Link",
        )


def link_user(
    link_request: PartnerLinkRequest, current_user: User, partner: Partner
) -> LinkResult:
    # Sanitize email just in case
    link_request.email = sanitize_email(link_request.email)
    partner_user = ensure_partner_user_exists_for_user(
        link_request, current_user, partner
    )
    set_plan_for_partner_user(partner_user, link_request.plan)

    agent.record_custom_event("AccountLinked", {"partner": partner.name})
    Session.commit()
    return LinkResult(
        user=current_user,
        strategy="Link",
    )


def switch_already_linked_user(
    link_request: PartnerLinkRequest, partner_user: PartnerUser, current_user: User
):
    # Find if the user has another link and unlink it
    other_partner_user = PartnerUser.get_by(
        user_id=current_user.id,
        partner_id=partner_user.partner_id,
    )
    if other_partner_user is not None:
        LOG.i(
            f"Deleting previous partner_user:{other_partner_user.id} from user:{current_user.id}"
        )
        PartnerUser.delete(other_partner_user.id)
    LOG.i(f"Linking partner_user:{partner_user.id} to user:{current_user.id}")
    # Link this partner_user to the current user
    partner_user.user_id = current_user.id
    # Set plan
    set_plan_for_partner_user(partner_user, link_request.plan)
    Session.commit()
    return LinkResult(
        user=current_user,
        strategy="Link",
    )


def process_link_case(
    link_request: PartnerLinkRequest,
    current_user: User,
    partner: Partner,
) -> LinkResult:
    # Sanitize email just in case
    link_request.email = sanitize_email(link_request.email)
    # Try to find a SimpleLogin user linked with this Partner account
    partner_user = PartnerUser.get_by(
        partner_id=partner.id, external_user_id=link_request.external_user_id
    )
    if partner_user is None:
        # There is no SL user linked with the partner. Proceed with linking
        return link_user(link_request, current_user, partner)

    # There is a SL user registered with the partner. Check if is the current one
    if partner_user.user_id == current_user.id:
        # Update plan
        set_plan_for_partner_user(partner_user, link_request.plan)
        # It's the same user. No need to do anything
        return LinkResult(
            user=current_user,
            strategy="Link",
        )
    else:
        return switch_already_linked_user(link_request, partner_user, current_user)
