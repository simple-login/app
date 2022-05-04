from dataclasses import dataclass
from typing import Optional

from app.models import EnumE


class UnsubscribeAction(EnumE):
    UnsubscribeNewsletter = 1
    DisableAlias = 2
    DisableContact = 3


@dataclass
class UnsubscribeData:
    action: UnsubscribeAction
    data: int


class UnsubscribeEncoder:
    @staticmethod
    def encode(unsub: UnsubscribeData) -> str:
        if unsub.action == UnsubscribeAction.DisableAlias:
            return f"{unsub.data}="
        if unsub.action == UnsubscribeAction.DisableContact:
            return f"{unsub.data}_"
        if unsub.action == UnsubscribeAction.UnsubscribeNewsletter:
            return f"{unsub.data}*"

    @classmethod
    def decode(cls, data: str) -> Optional[UnsubscribeData]:
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
