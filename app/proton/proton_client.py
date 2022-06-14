from abc import ABC, abstractmethod
from arrow import Arrow
from dataclasses import dataclass
from http import HTTPStatus
from requests import Response, Session
from typing import Optional

from app.account_linking import SLPlan, SLPlanType
from app.config import PROTON_EXTRA_HEADER_NAME, PROTON_EXTRA_HEADER_VALUE
from app.log import LOG

_APP_VERSION = "OauthClient_1.0.0"

PROTON_ERROR_CODE_NOT_EXISTS = 2501

PLAN_FREE = 1
PLAN_PREMIUM = 2


@dataclass
class UserInformation:
    email: str
    name: str
    id: str
    plan: SLPlan


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
    def get_user(self) -> Optional[UserInformation]:
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

        if PROTON_EXTRA_HEADER_NAME and PROTON_EXTRA_HEADER_VALUE:
            headers[PROTON_EXTRA_HEADER_NAME] = PROTON_EXTRA_HEADER_VALUE

        if original_ip is not None:
            headers["x-forwarded-for"] = original_ip
        client.headers.update(headers)
        self.client = client

    def get_user(self) -> Optional[UserInformation]:
        info = self.__get("/simple_login/v1/subscription")["Subscription"]
        if not info["IsAllowed"]:
            LOG.debug("Account is not allowed to log into SL")
            return None

        plan_value = info["Plan"]
        if plan_value == PLAN_FREE:
            plan = SLPlan(type=SLPlanType.Free, expiration=None)
        elif plan_value == PLAN_PREMIUM:
            plan = SLPlan(
                type=SLPlanType.Premium,
                expiration=Arrow.fromtimestamp(info["PlanExpiration"], tzinfo="utc"),
            )
        else:
            raise Exception(f"Invalid value for plan: {plan_value}")

        return UserInformation(
            email=info.get("Email"),
            name=info.get("DisplayName"),
            id=info.get("UserID"),
            plan=plan,
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
        as_json = res.json()
        res_code = as_json.get("Code")
        if not res_code or res_code != 1000:
            raise Exception(
                f"Unexpected response code. Wanted 1000 and got {res_code}: " + res.text
            )
        return as_json
