import base64
import enum
import hashlib
import json
from dataclasses import dataclass
from typing import Optional, Union

import itsdangerous

from app import config
from app.log import LOG

UNSUB_PREFIX = "un"


class UnsubscribeAction(enum.Enum):
    UnsubscribeNewsletter = 1
    DisableAlias = 2
    DisableContact = 3
    OriginalUnsubscribeMailto = 4


@dataclass
class UnsubscribeOriginalData:
    alias_id: int
    recipient: str
    subject: str


@dataclass
class UnsubscribeData:
    action: UnsubscribeAction
    data: Union[UnsubscribeOriginalData, int]


@dataclass
class UnsubscribeLink:
    link: str
    via_email: bool


class UnsubscribeEncoder:
    @staticmethod
    def encode(
        action: UnsubscribeAction, data: Union[int, UnsubscribeOriginalData]
    ) -> UnsubscribeLink:
        if config.UNSUBSCRIBER:
            return UnsubscribeLink(UnsubscribeEncoder.encode_mailto(action, data), True)
        return UnsubscribeLink(UnsubscribeEncoder.encode_url(action, data), False)

    @classmethod
    def encode_subject(
        cls, action: UnsubscribeAction, data: Union[int, UnsubscribeOriginalData]
    ) -> str:
        if (
            action != UnsubscribeAction.OriginalUnsubscribeMailto
            and type(data) is not int
        ):
            raise ValueError(f"Data has to be an int for an action of type {action}")
        if action == UnsubscribeAction.OriginalUnsubscribeMailto:
            if type(data) is not UnsubscribeOriginalData:
                raise ValueError(
                    f"Data has to be an UnsubscribeOriginalData for an action of type {action}"
                )
            # Initial 0 is the version number. If we need to add support for extra use-cases we can bump up this number
            data = (0, data.alias_id, data.recipient, data.subject)
        payload = (action.value, data)
        serialized_data = (
            base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8"))
            .rstrip(b"=")
            .decode("utf-8")
        )
        signed_data = cls._get_signer().sign(serialized_data).decode("utf-8")
        encoded_request = f"{UNSUB_PREFIX}.{signed_data}"
        if len(encoded_request) > 256:
            LOG.e("Encoded request is longer than 256 chars")
        return encoded_request

    @staticmethod
    def encode_mailto(
        action: UnsubscribeAction, data: Union[int, UnsubscribeOriginalData]
    ) -> str:
        subject = UnsubscribeEncoder.encode_subject(action, data)
        return f"mailto:{config.UNSUBSCRIBER}?subject={subject}"

    @staticmethod
    def encode_url(
        action: UnsubscribeAction, data: Union[int, UnsubscribeOriginalData]
    ) -> str:
        if action == UnsubscribeAction.DisableAlias:
            return f"{config.URL}/dashboard/unsubscribe/{data}"
        if action == UnsubscribeAction.DisableContact:
            return f"{config.URL}/dashboard/block_contact/{data}"
        if action in (
            UnsubscribeAction.UnsubscribeNewsletter,
            UnsubscribeAction.OriginalUnsubscribeMailto,
        ):
            encoded = UnsubscribeEncoder.encode_subject(action, data)
            return f"{config.URL}/dashboard/unsubscribe/encoded?data={encoded}"

    @staticmethod
    def _get_signer() -> itsdangerous.Signer:
        return itsdangerous.Signer(
            config.UNSUBSCRIBE_SECRET, digest_method=hashlib.sha3_224
        )

    @classmethod
    def decode_subject(cls, data: str) -> Optional[UnsubscribeData]:
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
            # Skip version number in action_data[0] for now it's always 0
            action_data = UnsubscribeOriginalData(
                action_data[1], action_data[2], action_data[3]
            )
        return UnsubscribeData(action, action_data)
