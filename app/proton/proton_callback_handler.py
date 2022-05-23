import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass
from flask import url_for
from typing import Optional

from app.db import Session
from app.errors import ProtonPartnerNotSetUp
from app.models import User, PartnerUser, Partner
from app.proton.proton_client import ProtonClient, ProtonUser
from app.utils import random_string

PROTON_PARTNER_NAME = "Proton"
_PROTON_PARTNER: Optional[Partner] = None


def get_proton_partner() -> Partner:
    global _PROTON_PARTNER
    if _PROTON_PARTNER is None:
        partner = Partner.get_by(name=PROTON_PARTNER_NAME)
        if partner is None:
            raise ProtonPartnerNotSetUp
        Session.expunge(partner)
        _PROTON_PARTNER = partner
    return _PROTON_PARTNER


class Action(enum.Enum):
    Login = 1
    Link = 2


@dataclass
class ProtonCallbackResult:
    redirect_to_login: bool
    flash_message: Optional[str]
    flash_category: Optional[str]
    redirect: Optional[str]
    user: Optional[User]


def ensure_partner_user_exists(
    proton_user: ProtonUser, sl_user: User, partner: Partner
):
    if not PartnerUser.get_by(user_id=sl_user.id, partner_id=partner.id):
        PartnerUser.create(
            user_id=sl_user.id,
            partner_id=partner.id,
            partner_email=proton_user.email,
        )
        Session.commit()


class ClientMergeStrategy(ABC):
    def __init__(
        self, proton_user: ProtonUser, sl_user: Optional[User], partner: Partner
    ):
        if self.__class__ == ClientMergeStrategy:
            raise RuntimeError("Cannot directly instantiate a ClientMergeStrategy")
        self.proton_user = proton_user
        self.sl_user = sl_user
        self.partner = partner

    @abstractmethod
    def process(self) -> ProtonCallbackResult:
        pass


class UnexistantSlClientStrategy(ClientMergeStrategy):
    def process(self) -> ProtonCallbackResult:
        # Will create a new SL User with a random password
        new_user = User.create(
            email=self.proton_user.email,
            name=self.proton_user.name,
            partner_user_id=self.proton_user.id,
            partner_id=self.partner.id,
            password=random_string(20),
        )
        PartnerUser.create(
            user_id=new_user.id,
            partner_id=self.partner.id,
            partner_email=self.proton_user.email,
        )
        # TODO: Adjust plans
        Session.commit()

        return ProtonCallbackResult(
            redirect_to_login=False,
            flash_message=None,
            flash_category=None,
            redirect=None,
            user=new_user,
        )


class ExistingSlClientStrategy(ClientMergeStrategy):
    def process(self) -> ProtonCallbackResult:
        ensure_partner_user_exists(self.proton_user, self.sl_user, self.partner)
        # TODO: Adjust plans

        return ProtonCallbackResult(
            redirect_to_login=False,
            flash_message=None,
            flash_category=None,
            redirect=None,
            user=self.sl_user,
        )


class ExistingSlUserLinkedWithDifferentProtonAccountStrategy(ClientMergeStrategy):
    def process(self) -> ProtonCallbackResult:
        return ProtonCallbackResult(
            redirect_to_login=True,
            flash_message="This Proton account is already linked to another account",
            flash_category="error",
            user=None,
            redirect=None,
        )


class AlreadyLinkedUserStrategy(ClientMergeStrategy):
    def process(self) -> ProtonCallbackResult:
        return ProtonCallbackResult(
            redirect_to_login=False,
            flash_message=None,
            flash_category=None,
            redirect=None,
            user=self.sl_user,
        )


def get_login_strategy(
    proton_user: ProtonUser, sl_user: Optional[User], partner: Partner
) -> ClientMergeStrategy:
    if sl_user is None:
        # We couldn't find any SimpleLogin user with the requested e-mail
        return UnexistantSlClientStrategy(proton_user, sl_user, partner)
    # There is a SimpleLogin user with the proton_user's e-mail
    # Try to find if it has been registered via a partner
    if sl_user.partner_id is None:
        # It has not been registered via a Partner
        return ExistingSlClientStrategy(proton_user, sl_user, partner)
    # It has been registered via a partner
    # Check if the partner_user_id matches
    if sl_user.partner_user_id != proton_user.id:
        # It doesn't match. That means that the SimpleLogin user has a different Proton account linked
        return ExistingSlUserLinkedWithDifferentProtonAccountStrategy(
            proton_user, sl_user, partner
        )
    # This case means that the sl_user is already linked, so nothing to do
    return AlreadyLinkedUserStrategy(proton_user, sl_user, partner)


def process_login_case(
    proton_user: ProtonUser, partner: Partner
) -> ProtonCallbackResult:
    # Try to find a SimpleLogin user registered with that proton user id
    sl_user_with_external_id = User.get_by(
        partner_id=partner.id, partner_user_id=proton_user.id
    )
    if sl_user_with_external_id is None:
        # We didn't find any SimpleLogin user registered with that proton user id
        # Try to find it using the proton's e-mail address
        sl_user = User.get_by(email=proton_user.email)
        return get_login_strategy(proton_user, sl_user, partner).process()
    else:
        # We found the SL user registered with that proton user id
        # We're done
        return AlreadyLinkedUserStrategy(
            proton_user, sl_user_with_external_id, partner
        ).process()


def link_user(
    proton_user: ProtonUser, current_user: User, partner: Partner
) -> ProtonCallbackResult:
    current_user.partner_user_id = proton_user.id
    current_user.partner_id = partner.id

    ensure_partner_user_exists(proton_user, current_user, partner)

    Session.commit()
    return ProtonCallbackResult(
        redirect_to_login=False,
        redirect=url_for("dashboard.setting"),
        flash_category="success",
        flash_message="Account successfully linked",
        user=current_user,
    )


def process_link_case(
    proton_user: ProtonUser,
    current_user: User,
    partner: Partner,
) -> ProtonCallbackResult:
    # Try to find a SimpleLogin user linked with this Proton account
    sl_user_linked_to_proton_account = User.get_by(
        partner_id=partner.id, partner_user_id=proton_user.id
    )
    if sl_user_linked_to_proton_account is None:
        # There is no SL user linked with the proton email. Proceed with linking
        return link_user(proton_user, current_user, partner)
    else:
        # There is a SL user registered with the proton email. Check if is the current one
        if sl_user_linked_to_proton_account.id == current_user.id:
            # It's the same user. No need to do anything
            return ProtonCallbackResult(
                redirect_to_login=False,
                redirect=url_for("dashboard.setting"),
                flash_category="success",
                flash_message="Account successfully linked",
                user=current_user,
            )
        else:
            # It's a different user. Unlink the other account and link the current one
            sl_user_linked_to_proton_account.partner_id = None
            sl_user_linked_to_proton_account.partner_user_id = None
            other_partner_user = PartnerUser.get_by(
                user_id=sl_user_linked_to_proton_account.id,
                partner_id=partner.id,
            )
            if other_partner_user is not None:
                PartnerUser.delete(other_partner_user.id)

            return link_user(proton_user, current_user, partner)


class ProtonCallbackHandler:
    def __init__(self, proton_client: ProtonClient):
        self.proton_client = proton_client

    def handle_login(self, partner: Partner) -> ProtonCallbackResult:
        return process_login_case(self.__get_proton_user(), partner)

    def handle_link(
        self, current_user: Optional[User], partner: Partner
    ) -> ProtonCallbackResult:
        if current_user is None:
            raise Exception("Cannot link account with current_user being None")
        return process_link_case(self.__get_proton_user(), current_user, partner)

    def __get_proton_user(self) -> ProtonUser:
        user = self.proton_client.get_user()
        plan = self.proton_client.get_plan()
        return ProtonUser(email=user.email, plan=plan, name=user.name, id=user.id)
