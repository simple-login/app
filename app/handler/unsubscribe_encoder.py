import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Optional, Union, Tuple

import itsdangerous

from app import config
from app.models import EnumE

UNSUB_PREFIX = "unsub"


class UnsubscribeAction(EnumE):
    UnsubscribeNewsletter = 1
    DisableAlias = 2
    DisableContact = 3
    OriginalUnsubscribeMailto = 4


@dataclass
class UnsubscribeData:
    action: UnsubscribeAction
    data: Union[Tuple[int, str, str], int]


class UnsubscribeEncoder:
    @staticmethod
    def _get_signer() -> itsdangerous.Signer:
        return itsdangerous.Signer(
            config.UNSUBSCRIBE_SECRET, digest_method=hashlib.sha3_224
        )

    @staticmethod
    def encode(unsub: UnsubscribeData) -> str:
        payload = (unsub.action.value, unsub.data)
        serialized_data = (
            base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8"))
            .rstrip(b"=")
            .decode("utf-8")
        )
        signer = itsdangerous.Signer(
            config.UNSUBSCRIBE_SECRET, digest_method=hashlib.sha3_224
        )
        signed_data = signer.sign(serialized_data).decode("utf-8")
        return f"{UNSUB_PREFIX}.{signed_data}"

    @classmethod
    def decode(cls, data: str) -> Optional[UnsubscribeData]:
        if data.find(UNSUB_PREFIX) == -1:
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
                    return UnsubscribeData(
                        UnsubscribeAction.UnsubscribeNewsletter, user_id
                    )
                else:
                    # some email providers might strip off the = suffix
                    alias_id = int(data)
                    return UnsubscribeData(UnsubscribeAction.DisableAlias, alias_id)
            except ValueError:
                return None
        signer = cls._get_signer()
        try:
            verified_data = signer.unsign(data[len(UNSUB_PREFIX) + 1 :])
        except itsdangerous.BadSignature:
            return None
        try:
            padded_data = verified_data + (b"=" * (-len(verified_data) % 4))
            payload = json.loads(base64.urlsafe_b64decode(padded_data))
        except ValueError:
            return None
        action = UnsubscribeAction(payload[0])
        action_data = payload[1]
        if action == UnsubscribeAction.OriginalUnsubscribeMailto:
            action_data = tuple(action_data)
        return UnsubscribeData(action, action_data)
