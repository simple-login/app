from abc import ABC, abstractmethod
from arrow import Arrow
from dataclasses import dataclass
from http import HTTPStatus
from requests import Response, Session
from typing import Optional

from app.account_linking import SLPlan, SLPlanType

_APP_VERSION = "OauthClient_1.0.0"

PROTON_ERROR_CODE_NOT_EXISTS = 2501


def plan_from_name(name: str) -> SLPlanType:
    if not name:
        raise Exception("Empty plan name")

    name_lower = name.lower()
    if name_lower == "free":
        return SLPlanType.Free
    else:
        return SLPlanType.Premium


@dataclass
class UserInformation:
    email: str
    name: str
    id: str
    plan: SLPlan


class AuthorizeResponse:
    def __init__(self, code: str, has_accepted: bool):
        self.code = code
        self.has_accepted = has_accepted

    def __str__(self):
        return f"[code={self.code}] [has_accepted={self.has_accepted}]"


@dataclass
class SessionResponse:
    state: str
    expires_in: int
    token_type: str
    refresh_token: str
    access_token: str
    session_id: str


@dataclass
class ProtonUser:
    id: str
    name: str
    email: str
    plan: SLPlan


@dataclass
class AccessCredentials:
    access_token: str
    session_id: str


def convert_access_token(access_token_response: str) -> AccessCredentials:
    """
    The Access token response contains both the Proton Session ID and the Access Token.
    The Session ID is necessary in order to use the Proton API. However, the OAuth response does not allow us to return
    extra content.
    This method takes the Access token response and extracts the session ID and the access token.
    """
    parts = access_token_response.split("-")
    if len(parts) != 3:
        raise Exception("Invalid access token response")
    if parts[0] != "pt":
        raise Exception("Invalid access token response format")
    return AccessCredentials(
        session_id=parts[1],
        access_token=parts[2],
    )


class ProtonClient(ABC):
    @abstractmethod
    def get_user(self) -> UserInformation:
        pass


class HttpProtonClient(ProtonClient):
    def __init__(
        self,
        base_url: str,
        credentials: AccessCredentials,
        original_ip: Optional[str],
        verify: bool = True,
    ):
        self.base_url = base_url
        self.access_token = credentials.access_token
        client = Session()
        client.verify = verify
        headers = {
            "x-pm-appversion": _APP_VERSION,
            "x-pm-apiversion": "3",
            "x-pm-uid": credentials.session_id,
            "authorization": f"Bearer {credentials.access_token}",
            "accept": "application/vnd.protonmail.v1+json",
            "user-agent": "ProtonOauthClient",
        }
        if original_ip is not None:
            headers["x-forwarded-for"] = original_ip
        client.headers.update(headers)
        self.client = client

    def get_user(self) -> UserInformation:
        info = self.__get("/users")["User"]
        subscribed = info["Subscribed"] == 1
        plan = None
        if subscribed:
            plan = self.get_plan()

        return UserInformation(
            email=info.get("Email"),
            name=info.get("Name"),
            id=info.get("ID"),
            plan=plan,
        )

    def get_plan(self) -> SLPlan:
        url = f"{self.base_url}/payments/subscription"
        res = self.client.get(url)

        status = res.status_code
        if status == HTTPStatus.UNPROCESSABLE_ENTITY:
            as_json = res.json()
            error_code = as_json.get("Code")
            if error_code == PROTON_ERROR_CODE_NOT_EXISTS:
                return SLPlan(type=SLPlanType.Free, expiration=None)

        subscription = self.__validate_response(res).get("Subscription")
        if subscription is None:
            return SLPlan(type=SLPlanType.Free, expiration=None)

        expiration = Arrow.utcfromtimestamp(subscription["PeriodEnd"])

        # Check if subscription is expired
        if expiration < Arrow.utcnow():
            return SLPlan(type=SLPlanType.Free, expiration=None)

        plans = subscription["Plans"]
        if len(plans) == 0:
            return SLPlan(type=SLPlanType.Free, expiration=None)

        plan = plans[0]
        plan_type = plan_from_name(plan["Name"])
        return SLPlan(
            type=plan_type,
            expiration=expiration,
        )

    def __get(self, route: str) -> dict:
        url = f"{self.base_url}{route}"
        res = self.client.get(url)
        return self.__validate_response(res)

    @staticmethod
    def __validate_response(res: Response) -> dict:
        status = res.status_code
        if status != HTTPStatus.OK:
            raise Exception(
                f"Unexpected status code. Wanted 200 and got {status}: " + res.text
            )
        return res.json()
