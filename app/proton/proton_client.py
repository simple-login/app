import dataclasses
from abc import ABC, abstractmethod
from enum import Enum
from http import HTTPStatus
from requests import Response, Session
from typing import Optional

_APP_VERSION = "OauthClient_1.0.0"

PROTON_ERROR_CODE_NOT_EXISTS = 2501


class ProtonPlan(Enum):
    Free = 0
    Professional = 1
    Visionary = 2

    def name(self):
        if self == self.Free:
            return "Free"
        elif self == self.Professional:
            return "Professional"
        elif self == self.Visionary:
            return "Visionary"
        else:
            raise Exception("Unknown plan")


def plan_from_name(name: str) -> ProtonPlan:
    name_lower = name.lower()
    if name_lower == "free":
        return ProtonPlan.Free
    elif name_lower == "professional":
        return ProtonPlan.Professional
    elif name_lower == "visionary":
        return ProtonPlan.Visionary
    else:
        raise Exception(f"Unknown plan [{name}]")


@dataclasses.dataclass
class UserInformation:
    email: str
    name: str
    id: str


class AuthorizeResponse:
    def __init__(self, code: str, has_accepted: bool):
        self.code = code
        self.has_accepted = has_accepted

    def __str__(self):
        return f"[code={self.code}] [has_accepted={self.has_accepted}]"


@dataclasses.dataclass
class SessionResponse:
    state: str
    expires_in: int
    token_type: str
    refresh_token: str
    access_token: str
    session_id: str


@dataclasses.dataclass
class ProtonUser:
    id: str
    name: str
    email: str
    plan: ProtonPlan


@dataclasses.dataclass
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

    @abstractmethod
    def get_organization(self) -> dict:
        pass

    @abstractmethod
    def get_plan(self) -> ProtonPlan:
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
        return UserInformation(
            email=info.get("Email"), name=info.get("Name"), id=info.get("ID")
        )

    def get_organization(self) -> dict:
        return self.__get("/code/v4/organizations")["Organization"]

    def get_plan(self) -> ProtonPlan:
        url = f"{self.base_url}/core/v4/organizations"
        res = self.client.get(url)

        status = res.status_code
        if status == HTTPStatus.UNPROCESSABLE_ENTITY:
            as_json = res.json()
            error_code = as_json.get("Code")
            if error_code == PROTON_ERROR_CODE_NOT_EXISTS:
                return ProtonPlan.Free

        org = self.__validate_response(res).get("Organization")
        if org is None:
            return ProtonPlan.Free
        return plan_from_name(org["PlanName"])

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
