import enum
from dataclasses import dataclass
from typing import Optional

from app import config


class UnsubscribeAction(enum.Enum):
    UnsubscribeNewsletter = 1
    DisableAlias = 2
    DisableContact = 3


@dataclass
class UnsubscribeData:
    action: UnsubscribeAction
    data: int


@dataclass
class UnsubscribeLink:
    link: str
    via_email: bool


class UnsubscribeEncoder:
    @staticmethod
    def encode(action: UnsubscribeAction, data: int) -> UnsubscribeLink:
        if config.UNSUBSCRIBER:
            return UnsubscribeLink(UnsubscribeEncoder.encode_mailto(action, data), True)
        return UnsubscribeLink(UnsubscribeEncoder.encode_url(action, data), False)

    @staticmethod
    def encode_subject(action: UnsubscribeAction, data: int) -> str:
        if action == UnsubscribeAction.DisableAlias:
            return f"{data}="
        if action == UnsubscribeAction.DisableContact:
            return f"{data}_"
        if action == UnsubscribeAction.UnsubscribeNewsletter:
            return f"{data}*"

    @staticmethod
    def encode_mailto(action: UnsubscribeAction, data: int) -> str:
        subject = UnsubscribeEncoder.encode_subject(action, data)
        return f"mailto:{config.UNSUBSCRIBER}?subject={subject}"

    @staticmethod
    def encode_url(action: UnsubscribeAction, data: int) -> str:
        if action == UnsubscribeAction.DisableAlias:
            return f"{config.URL}/dashboard/unsubscribe/{data}"
        if action == UnsubscribeAction.DisableContact:
            return f"{config.URL}/dashboard/block_contact/{data}"
        if action == UnsubscribeAction.UnsubscribeNewsletter:
            raise Exception("Cannot encode url to disable newsletter")

    @staticmethod
    def decode_subject(data: str) -> Optional[UnsubscribeData]:
        try:
            # subject has the format {alias.id}=
            if data.endswith("="):
                alias_id = int(data[:-1])
                return UnsubscribeData(UnsubscribeAction.DisableAlias, alias_id)
            # {contact.id}_
            elif data.endswith("_"):
                contact_id = int(data[:-1])
                return UnsubscribeData(UnsubscribeAction.DisableContact, contact_id)
            # {user.id}*
            elif data.endswith("*"):
                user_id = int(data[:-1])
                return UnsubscribeData(UnsubscribeAction.UnsubscribeNewsletter, user_id)
            else:
                # some email providers might strip off the = suffix
                alias_id = int(data)
                return UnsubscribeData(UnsubscribeAction.DisableAlias, alias_id)
        except ValueError:
            return None
