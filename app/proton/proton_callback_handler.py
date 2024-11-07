from dataclasses import dataclass
from enum import Enum
from flask import url_for
from typing import Optional

from app.errors import LinkException
from app.models import User, Partner
from app.proton.proton_client import ProtonClient, ProtonUser
from app.account_linking import (
    process_login_case,
    process_link_case,
    PartnerLinkRequest,
)


class Action(Enum):
    Login = 1
    Link = 2


@dataclass
class ProtonCallbackResult:
    redirect_to_login: bool
    flash_message: Optional[str]
    flash_category: Optional[str]
    redirect: Optional[str]
    user: Optional[User]


def generate_account_not_allowed_to_log_in() -> ProtonCallbackResult:
    return ProtonCallbackResult(
        redirect_to_login=True,
        flash_message="This account is not allowed to log in with Proton. Please convert your account to a full Proton account",
        flash_category="error",
        redirect=None,
        user=None,
    )


class ProtonCallbackHandler:
    def __init__(self, proton_client: ProtonClient):
        self.proton_client = proton_client

    def handle_login(self, partner: Partner) -> ProtonCallbackResult:
        try:
            user = self.__get_partner_user()
            if user is None:
                return generate_account_not_allowed_to_log_in()
            res = process_login_case(user, partner)
            return ProtonCallbackResult(
                redirect_to_login=False,
                flash_message=None,
                flash_category=None,
                redirect=None,
                user=res.user,
            )
        except LinkException as e:
            return ProtonCallbackResult(
                redirect_to_login=True,
                flash_message=e.message,
                flash_category="error",
                redirect=None,
                user=None,
            )

    def handle_link(
        self,
        current_user: Optional[User],
        partner: Partner,
    ) -> ProtonCallbackResult:
        if current_user is None:
            raise Exception("Cannot link account with current_user being None")
        try:
            user = self.__get_partner_user()
            if user is None:
                return generate_account_not_allowed_to_log_in()
            res = process_link_case(user, current_user, partner)
            return ProtonCallbackResult(
                redirect_to_login=False,
                flash_message="Account successfully linked",
                flash_category="success",
                redirect=url_for("dashboard.setting"),
                user=res.user,
            )
        except LinkException as e:
            return ProtonCallbackResult(
                redirect_to_login=False,
                flash_message=e.message,
                flash_category="error",
                redirect=None,
                user=None,
            )

    def __get_partner_user(self) -> Optional[PartnerLinkRequest]:
        proton_user = self.__get_proton_user()
        if proton_user is None:
            return None
        return PartnerLinkRequest(
            email=proton_user.email,
            external_user_id=proton_user.id,
            name=proton_user.name,
            plan=proton_user.plan,
            from_partner=False,  # The user has started this flow, so we don't mark it as created by a partner
        )

    def __get_proton_user(self) -> Optional[ProtonUser]:
        user = self.proton_client.get_user()
        if user is None:
            return None
        return ProtonUser(email=user.email, plan=user.plan, name=user.name, id=user.id)
