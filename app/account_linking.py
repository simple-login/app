from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import sqlalchemy.exc
from arrow import Arrow
from newrelic import agent
from psycopg2.errors import UniqueViolation
from sqlalchemy import or_

from app import config
from app.db import Session
from app.email_utils import send_welcome_email, email_can_be_used_as_mailbox
from app.errors import (
    AccountAlreadyLinkedToAnotherPartnerException,
    AccountIsUsingAliasAsEmail,
    AccountAlreadyLinkedToAnotherUserException,
    EmailNotAllowed,
)
from app.events.event_dispatcher import EventDispatcher
from app.events.generated.event_pb2 import UserPlanChanged, EventContent
from app.log import LOG
from app.models import (
    PartnerSubscription,
    PartnerUser,
    User,
    Alias,
)
from app.partner_user_utils import create_partner_user, create_partner_subscription
from app.partner_utils import PartnerData
from app.user_audit_log_utils import emit_user_audit_log, UserAuditLogAction
from app.utils import random_string
from app.utils import sanitize_email, canonicalize_email


class SLPlanType(Enum):
    Free = 1
    Premium = 2
    PremiumLifetime = 3


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


def send_user_plan_changed_event(
    partner_user: PartnerUser,
) -> UserPlanChanged:
    subscription_end = partner_user.user.get_active_subscription_end(
        include_partner_subscription=False
    )
    if partner_user.user.lifetime:
        event = UserPlanChanged(lifetime=True)
    elif subscription_end:
        event = UserPlanChanged(plan_end_time=subscription_end.timestamp)
    else:
        event = UserPlanChanged(plan_end_time=None)
    EventDispatcher.send_event(partner_user.user, EventContent(user_plan_change=event))
    Session.flush()
    return event


def set_plan_for_partner_user(partner_user: PartnerUser, plan: SLPlan):
    sub = PartnerSubscription.get_by(partner_user_id=partner_user.id)
    is_lifetime = plan.type == SLPlanType.PremiumLifetime
    if plan.type == SLPlanType.Free:
        if sub is not None:
            LOG.i(
                f"Deleting partner_subscription [user_id={partner_user.user_id}] [partner_id={partner_user.partner_id}]"
            )
            PartnerSubscription.delete(sub.id)
            agent.record_custom_event("PlanChange", {"plan": "free"})
    else:
        end_time = plan.expiration
        if plan.type == SLPlanType.PremiumLifetime:
            end_time = None
        if sub is None:
            LOG.i(
                f"Creating partner_subscription [user_id={partner_user.user_id}] [partner_id={partner_user.partner_id}] with {end_time} / {is_lifetime}"
            )
            create_partner_subscription(
                partner_user=partner_user,
                expiration=end_time,
                lifetime=is_lifetime,
                msg="Upgraded via partner. User did not have a previous partner subscription",
            )
            agent.record_custom_event("PlanChange", {"plan": "premium", "type": "new"})
        else:
            if sub.end_at != plan.expiration or sub.lifetime != is_lifetime:
                agent.record_custom_event(
                    "PlanChange", {"plan": "premium", "type": "extension"}
                )
                sub.end_at = plan.expiration if not is_lifetime else None
                sub.lifetime = is_lifetime
                LOG.i(
                    f"Updating partner_subscription [user_id={partner_user.user_id}] [partner_id={partner_user.partner_id}] to {sub.end_at} / {sub.lifetime} "
                )
                emit_user_audit_log(
                    user=partner_user.user,
                    action=UserAuditLogAction.SubscriptionExtended,
                    message="Extended partner subscription",
                )
    Session.flush()
    send_user_plan_changed_event(partner_user)
    Session.commit()


def set_plan_for_user(user: User, plan: SLPlan, partner: PartnerData):
    partner_user = PartnerUser.get_by(partner_id=partner.id, user_id=user.id)
    if partner_user is None:
        return
    return set_plan_for_partner_user(partner_user, plan)


def ensure_partner_user_exists_for_user(
    link_request: PartnerLinkRequest, sl_user: User, partner: PartnerData
) -> PartnerUser:
    # Find partner_user by user_id
    res = PartnerUser.get_by(user_id=sl_user.id)
    if res and res.partner_id != partner.id:
        raise AccountAlreadyLinkedToAnotherPartnerException()
    if not res:
        try:
            res = create_partner_user(
                user=sl_user,
                partner_id=partner.id,
                partner_email=link_request.email,
                external_user_id=link_request.external_user_id,
            )

            Session.commit()
        except (UniqueViolation, sqlalchemy.exc.IntegrityError):
            res = PartnerUser.get_by(
                partner_id=partner.id, external_user_id=link_request.external_user_id
            )
            if res is None:
                res = PartnerUser.get_by(partner_id=partner.id, user_id=sl_user.id)
            if res is not None and (
                res.user_id != sl_user.id
                or res.external_user_id != link_request.external_user_id
            ):
                LOG.warning(
                    f"Account is linked to another user. Expected user {sl_user.id} got {res.user_id}. Expected external user {link_request.external_user_id} got {res.external_user_id}"
                )
                raise AccountAlreadyLinkedToAnotherPartnerException()

        LOG.i(
            f"Created new partner_user for partner:{partner.id} user:{sl_user.id} external_user_id:{link_request.external_user_id}. PartnerUser.id is {res.id}"
        )
    return res


class ClientMergeStrategy(ABC):
    def __init__(
        self,
        link_request: PartnerLinkRequest,
        user: Optional[User],
        partner: PartnerData,
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
        canonical_email = canonicalize_email(self.link_request.email)
        if not email_can_be_used_as_mailbox(canonical_email):
            raise EmailNotAllowed()
        try:
            # Will create a new SL User with a random password
            new_user = User.create(
                email=canonical_email,
                name=self.link_request.name,
                password=random_string(20),
                activated=True,
                from_partner=self.link_request.from_partner,
            )
            self.create_partner_user(new_user)
            Session.commit()

            if not new_user.created_by_partner:
                send_welcome_email(new_user)

            agent.record_custom_event(
                "PartnerUserCreation", {"partner": self.partner.name}
            )

            return LinkResult(
                user=new_user,
                strategy=self.__class__.__name__,
            )
        except (UniqueViolation, sqlalchemy.exc.IntegrityError) as e:
            Session.rollback()
            LOG.debug(f"Got the duplicate user error: {e}")
            return self.create_missing_link(canonical_email)

    def create_missing_link(self, canonical_email: str):
        # If there's a unique key violation due to race conditions try to create only the partner if needed
        partner_user = PartnerUser.get_by(
            external_user_id=self.link_request.external_user_id,
            partner_id=self.partner.id,
        )
        if partner_user is None:
            # Get the user by canonical email and if not by normal email
            user = User.get_by(email=canonical_email) or User.get_by(
                email=self.link_request.email
            )
            if not user:
                raise RuntimeError(
                    "Tried to create only partner on UniqueViolation but cannot find the user"
                )
            partner_user = self.create_partner_user(user)
            Session.commit()
        return LinkResult(
            user=partner_user.user, strategy=ExistingUnlinkedUserStrategy.__name__
        )

    def create_partner_user(self, new_user: User):
        partner_user = create_partner_user(
            user=new_user,
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
        return partner_user


class ExistingUnlinkedUserStrategy(ClientMergeStrategy):
    def process(self) -> LinkResult:
        # IF it was scheduled to be deleted. Unschedule it.
        self.user.delete_on = None
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
        raise AccountAlreadyLinkedToAnotherUserException()


def get_login_strategy(
    link_request: PartnerLinkRequest, user: Optional[User], partner: PartnerData
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


def check_alias(email: str):
    alias = Alias.get_by(email=email)
    if alias is not None:
        raise AccountIsUsingAliasAsEmail()


def process_login_case(
    link_request: PartnerLinkRequest, partner: PartnerData
) -> LinkResult:
    # Sanitize email just in case
    link_request.email = sanitize_email(link_request.email)
    # Try to find a SimpleLogin user registered with that partner user id
    partner_user = PartnerUser.get_by(
        partner_id=partner.id, external_user_id=link_request.external_user_id
    )
    if partner_user is None:
        canonical_email = canonicalize_email(link_request.email)
        # We didn't find any SimpleLogin user registered with that partner user id
        # Make sure they aren't using an alias as their link email
        check_alias(link_request.email)
        check_alias(canonical_email)
        # Try to find it using the partner's e-mail address
        users = User.filter(
            or_(User.email == link_request.email, User.email == canonical_email)
        ).all()
        if len(users) > 1:
            user = [user for user in users if user.email == canonical_email][0]
        elif len(users) == 1:
            user = users[0]
        else:
            user = None
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
    link_request: PartnerLinkRequest, current_user: User, partner: PartnerData
) -> LinkResult:
    # Sanitize email just in case
    link_request.email = sanitize_email(link_request.email)
    # If it was scheduled to be deleted. Unschedule it.
    current_user.delete_on = None
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
    if config.PROTON_PREVENT_CHANGE_LINKED_ACCOUNT:
        LOG.i(
            f"Proton account is linked to another user partner_user:{partner_user.id} from user:{current_user.id}"
        )
        raise AccountAlreadyLinkedToAnotherUserException()
    # Find if the user has another link and unlink it
    other_partner_user = PartnerUser.get_by(
        user_id=current_user.id,
        partner_id=partner_user.partner_id,
    )
    if other_partner_user is not None:
        LOG.i(
            f"Deleting previous partner_user:{other_partner_user.id} from user:{current_user.id}"
        )
        emit_user_audit_log(
            user=other_partner_user.user,
            action=UserAuditLogAction.UnlinkAccount,
            message=f"Deleting partner_user {other_partner_user.id} (external_user_id={other_partner_user.external_user_id} | partner_email={other_partner_user.partner_email}) from user {current_user.id}, as we received a new link request for the same partner",
        )
        PartnerUser.delete(other_partner_user.id)
    LOG.i(f"Linking partner_user:{partner_user.id} to user:{current_user.id}")
    # Link this partner_user to the current user
    emit_user_audit_log(
        user=partner_user.user,
        action=UserAuditLogAction.UnlinkAccount,
        message=f"Unlinking from partner, as user will now be tied to another external account. old=(id={partner_user.user.id} | email={partner_user.user.email}) | new=(id={current_user.id} | email={current_user.email})",
    )
    partner_user.user_id = current_user.id
    emit_user_audit_log(
        user=current_user,
        action=UserAuditLogAction.LinkAccount,
        message=f"Linking user {current_user.id} ({current_user.email}) to partner_user:{partner_user.id} (external_user_id={partner_user.external_user_id} | partner_email={partner_user.partner_email})",
    )
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
    partner: PartnerData,
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
