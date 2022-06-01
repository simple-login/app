from dataclasses import dataclass
from enum import Enum
from flask import url_for
from typing import Optional

from app.db import Session
from app.errors import ProtonPartnerNotSetUp
from app.models import User, Partner
from app.proton.proton_client import ProtonClient, ProtonUser
from app.account_linking import (
    process_login_case,
    process_link_case,
    PartnerUserDto,
    LinkException,
)

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


class ProtonCallbackHandler:
    def __init__(self, proton_client: ProtonClient):
        self.proton_client = proton_client

    def handle_login(self, partner: Partner) -> ProtonCallbackResult:
        try:
            res = process_login_case(self.__get_partner_user(), partner)
            return ProtonCallbackResult(
                redirect_to_login=False,
                flash_message="Account successfully linked",
                flash_category="success",
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
        self, current_user: Optional[User], partner: Partner
    ) -> ProtonCallbackResult:
        if current_user is None:
            raise Exception("Cannot link account with current_user being None")
        try:
            res = process_link_case(self.__get_partner_user(), current_user, partner)
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

    def __get_partner_user(self) -> PartnerUserDto:
        proton_user = self.__get_proton_user()
        return PartnerUserDto(
            email=proton_user.email,
            partner_user_id=proton_user.id,
            name=proton_user.name,
            plan=proton_user.plan,
        )

    def __get_proton_user(self) -> ProtonUser:
        user = self.proton_client.get_user()
        return ProtonUser(email=user.email, plan=user.plan, name=user.name, id=user.id)
