import urllib.parse
from email.message import Message

from app import config
from app.email import headers
from app.email_utils import add_or_replace_header, delete_header
from app.handler.unsubscribe_handler import (
    UnsubscribeEncoder,
    UnsubscribeData,
    UnsubscribeAction,
)
from app.models import Alias, Contact, UnsubscribeBehaviourEnum

UNSUB_PREFIX = "unsub"


class UnsubscribeGenerator:
    def _add_unsubscribe_header(self, message: Message, unsub_payload: str) -> Message:
        if config.UNSUBSCRIBER:
            unsub_mailto = f"mailto:{config.UNSUBSCRIBER}?subject={unsub_payload}"
            add_or_replace_header(
                message, headers.LIST_UNSUBSCRIBE, f"<{unsub_mailto}>"
            )
            delete_header(message, headers.LIST_UNSUBSCRIBE_POST)
        else:
            url = f"{config.URL}/dashboard/encoded_unsubscribe?request={unsub_payload}"
            add_or_replace_header(message, headers.LIST_UNSUBSCRIBE, f"<{url}>")
            add_or_replace_header(
                message, headers.LIST_UNSUBSCRIBE_POST, "List-Unsubscribe=One-Click"
            )
        return message

    def _generate_header_with_original_behaviour(
        self, alias: Alias, message: Message
    ) -> Message:
        unsubscribe_data = message[headers.LIST_UNSUBSCRIBE]
        if not unsubscribe_data:
            return message
        raw_methods = [method.strip() for method in unsubscribe_data.split(",")]
        mailto_unsubs = None
        other_unsubs = []
        for raw_method in raw_methods:
            start = raw_method.find("<")
            end = raw_method.rfind(">")
            if start == -1 or end == -1 or start >= end:
                continue
            method = raw_method[start + 1 : end]
            url_data = urllib.parse.urlparse(method)
            if url_data.scheme == "mailto":
                query_data = urllib.parse.parse_qs(url_data.query)
                mailto_unsubs = (url_data.path, query_data.get("subject", [""])[0])
            else:
                other_unsubs.append(method)
        # If there are non mailto unsubscribe methods, use those in the header
        if other_unsubs:
            add_or_replace_header(
                message,
                headers.LIST_UNSUBSCRIBE,
                ", ".join([f"<{method}>" for method in other_unsubs]),
            )
            add_or_replace_header(
                message, headers.LIST_UNSUBSCRIBE_POST, "List-Unsubscribe=One-Click"
            )
            return message
        unsub_payload = UnsubscribeEncoder.encode(
            UnsubscribeData(
                UnsubscribeAction.OriginalUnsubscribeMailto,
                (alias.id, mailto_unsubs[0], mailto_unsubs[1]),
            )
        )
        return self._add_unsubscribe_header(message, unsub_payload)

    def _generate_header_with_sl_behaviour(
        self, alias: Alias, contact: Contact, message: Message
    ) -> Message:
        user = alias.user
        if user.one_click_unsubscribe_block_sender:
            unsubscribe_link, via_email = alias.unsubscribe_link(contact)
        else:
            unsubscribe_link, via_email = alias.unsubscribe_link()

        add_or_replace_header(
            message, headers.LIST_UNSUBSCRIBE, f"<{unsubscribe_link}>"
        )
        if not via_email:
            add_or_replace_header(
                message, headers.LIST_UNSUBSCRIBE_POST, "List-Unsubscribe=One-Click"
            )
        return message

    def add_header_to_message(
        self, alias: Alias, contact: Contact, message: Message
    ) -> Message:
        """
        Add List-Unsubscribe header
        """
        if alias.user.unsub_behaviour == UnsubscribeBehaviourEnum.PreserveOriginal:
            return self._generate_header_with_original_behaviour(alias, message)
        else:
            return self._generate_header_with_sl_behaviour(alias, contact, message)
