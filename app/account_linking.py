from abc import ABC, abstractmethod
from arrow import Arrow
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from app.db import Session
from app.models import PartnerSubscription, Partner, PartnerUser, User
from app.utils import random_string


class SLPlanType(Enum):
    Free = 1
    Premium = 2


@dataclass
class SLPlan:
    type: SLPlanType
    expiration: Optional[Arrow]


@dataclass
class PartnerUserDto:
    name: str
    email: str
    partner_user_id: str
    plan: SLPlan


@dataclass
class LinkResult:
    user: User
    strategy: str


class LinkException(Exception):
    def __init__(self, message: str):
        self.message = message


class AccountAlreadyLinkedToAnotherPartnerException(LinkException):
    def __init__(self):
        super().__init__("This account is already linked to another Partner")


def set_plan_for_user(user: User, plan: SLPlan, partner: Partner):
    subs = PartnerSubscription.find_by_user_id(user.id)
    if plan.type == SLPlanType.Free:
        # If the plan is Free, check if there is a subscription. If there is, remove it
        if subs is None:
            # There was no subscription. We are done
            return
        else:
            # There was a subscription. This is a downgrade. Remove it
            PartnerSubscription.delete(subs.id)
    else:
        # We want to set a plan for the user
        # Check if there is a subscription
        if subs is not None:
            # There already is a subscription. Update it
            subs.end_at = plan.expiration
            return
        else:
            # There is no subscription. Create it
            partner_user = PartnerUser.get_or_create(
                user_id=user.id, partner_id=partner.id
            )
            PartnerSubscription.create(
                partner_user_id=partner_user.id,
                end_at=plan.expiration,
            )

    Session.commit()


def ensure_partner_user_exists(
    partner_user: PartnerUserDto, sl_user: User, partner: Partner
) -> PartnerUser:
    res = PartnerUser.get_by(user_id=sl_user.id, partner_id=partner.id)
    if not res:
        res = PartnerUser.create(
            user_id=sl_user.id,
            partner_id=partner.id,
            partner_email=partner_user.email,
        )
        Session.commit()
    return res


class ClientMergeStrategy(ABC):
    def __init__(
        self, partner_user: PartnerUserDto, sl_user: Optional[User], partner: Partner
    ):
        if self.__class__ == ClientMergeStrategy:
            raise RuntimeError("Cannot directly instantiate a ClientMergeStrategy")
        self.partner_user = partner_user
        self.sl_user = sl_user
        self.partner = partner

    @abstractmethod
    def process(self) -> LinkResult:
        pass


class UnexistantSlClientStrategy(ClientMergeStrategy):
    def process(self) -> LinkResult:
        # Will create a new SL User with a random password
        new_user = User.create(
            email=self.partner_user.email,
            name=self.partner_user.name,
            partner_user_id=self.partner_user.partner_user_id,
            partner_id=self.partner.id,
            password=random_string(20),
        )
        PartnerUser.create(
            user_id=new_user.id,
            partner_id=self.partner.id,
            partner_email=self.partner_user.email,
        )

        set_plan_for_user(
            new_user,
            self.partner_user.plan,
            self.partner,
        )
        Session.commit()

        return LinkResult(
            user=new_user,
            strategy=self.__class__.__name__,
        )


class ExistingSlClientStrategy(ClientMergeStrategy):
    def process(self) -> LinkResult:
        ensure_partner_user_exists(self.partner_user, self.sl_user, self.partner)
        set_plan_for_user(
            self.sl_user,
            self.partner_user.plan,
            self.partner,
        )

        return LinkResult(
            user=self.sl_user,
            strategy=self.__class__.__name__,
        )


class ExistingSlUserLinkedWithDifferentPartnerStrategy(ClientMergeStrategy):
    def process(self) -> LinkResult:
        raise AccountAlreadyLinkedToAnotherPartnerException()


class AlreadyLinkedUserStrategy(ClientMergeStrategy):
    def process(self) -> LinkResult:
        set_plan_for_user(self.sl_user, self.partner_user.plan, self.partner)
        return LinkResult(
            user=self.sl_user,
            strategy=self.__class__.__name__,
        )


def get_login_strategy(
    partner_user: PartnerUserDto, sl_user: Optional[User], partner: Partner
) -> ClientMergeStrategy:
    if sl_user is None:
        # We couldn't find any SimpleLogin user with the requested e-mail
        return UnexistantSlClientStrategy(partner_user, sl_user, partner)
    # There is a SimpleLogin user with the partner_user's e-mail
    # Try to find if it has been registered via a partner
    if sl_user.partner_id is None:
        # It has not been registered via a Partner
        return ExistingSlClientStrategy(partner_user, sl_user, partner)
    # It has been registered via a partner
    # Check if the partner_user_id matches
    if sl_user.partner_user_id != partner_user.partner_user_id:
        # It doesn't match. That means that the SimpleLogin user has a different Partner account linked
        return ExistingSlUserLinkedWithDifferentPartnerStrategy(
            partner_user, sl_user, partner
        )
    # This case means that the sl_user is already linked, so nothing to do
    return AlreadyLinkedUserStrategy(partner_user, sl_user, partner)


def process_login_case(partner_user: PartnerUserDto, partner: Partner) -> LinkResult:
    # Try to find a SimpleLogin user registered with that partner user id
    sl_user_with_external_id = User.get_by(
        partner_id=partner.id, partner_user_id=partner_user.partner_user_id
    )
    if sl_user_with_external_id is None:
        # We didn't find any SimpleLogin user registered with that partner user id
        # Try to find it using the partner's e-mail address
        sl_user = User.get_by(email=partner_user.email)
        return get_login_strategy(partner_user, sl_user, partner).process()
    else:
        # We found the SL user registered with that partner user id
        # We're done
        return AlreadyLinkedUserStrategy(
            partner_user, sl_user_with_external_id, partner
        ).process()


def link_user(
    partner_user: PartnerUserDto, current_user: User, partner: Partner
) -> LinkResult:
    current_user.partner_user_id = partner_user.partner_user_id
    current_user.partner_id = partner.id

    ensure_partner_user_exists(partner_user, current_user, partner)
    set_plan_for_user(current_user, partner_user.plan, partner)

    Session.commit()
    return LinkResult(
        user=current_user,
        strategy="Link",
    )


def process_link_case(
    partner_user: PartnerUserDto,
    current_user: User,
    partner: Partner,
) -> LinkResult:
    # Try to find a SimpleLogin user linked with this Partner account
    sl_user_linked_to_partner_account = User.get_by(
        partner_id=partner.id, partner_user_id=partner_user.partner_user_id
    )
    if sl_user_linked_to_partner_account is None:
        # There is no SL user linked with the partner email. Proceed with linking
        return link_user(partner_user, current_user, partner)
    else:
        # There is a SL user registered with the partner email. Check if is the current one
        if sl_user_linked_to_partner_account.id == current_user.id:
            # It's the same user. No need to do anything
            return LinkResult(
                user=current_user,
                strategy="Link",
            )
        else:
            # It's a different user. Unlink the other account and link the current one
            sl_user_linked_to_partner_account.partner_id = None
            sl_user_linked_to_partner_account.partner_user_id = None
            other_partner_user = PartnerUser.get_by(
                user_id=sl_user_linked_to_partner_account.id,
                partner_id=partner.id,
            )
            if other_partner_user is not None:
                PartnerUser.delete(other_partner_user.id)

            return link_user(partner_user, current_user, partner)
