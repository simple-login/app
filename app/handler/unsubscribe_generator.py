import urllib
from email.header import Header
from email.message import Message

from app import config
from app.email import headers
from app.email_utils import add_or_replace_header, delete_header
from app.handler.unsubscribe_encoder import (
    UnsubscribeEncoder,
    UnsubscribeAction,
    UnsubscribeData,
    UnsubscribeOriginalData,
)
from app.log import LOG
from app.models import Alias, Contact, UnsubscribeBehaviourEnum


class UnsubscribeGenerator:
    def _calculate_header_with_original_behaviour(
        self, alias: Alias, message: Message
    ) -> dict[str, str]:
        """
        Generate a header that will encode the original unsub request. To do so
         1. Look if there's an original List_Unsubscribe headers, otherwise do nothing
         2. Header has the form <method1>, <method2>, .. where each method is either
           - mailto:s@b.c?subject=something
           - http(s)://somewhere.com
        3. Check if there are http unsub requests in the header. If there are, reserve them and remove all mailto
           methods to avoid leaking the real mailbox. We forward the message with only http(s) methods.
        4. If there aren't neither https nor mailto methods, strip the header from the message and that's it.
           It could happen if the header is malformed.
        5. Encode in our unsub request the first original mail and subject to unsub, and use that as our unsub header.
        """
        unsubscribe_data = message[headers.LIST_UNSUBSCRIBE]
        if not unsubscribe_data:
            LOG.info("Email has no unsubscribe header")
            return {}
        if isinstance(unsubscribe_data, Header):
            unsubscribe_data = str(unsubscribe_data.encode())
        raw_methods = [method.strip() for method in unsubscribe_data.split(",")]
        mailto_unsubs = None
        other_unsubs = []
        for raw_method in raw_methods:
            start = raw_method.find("<")
            end = raw_method.rfind(">")
            if start == -1 or end == -1 or start >= end:
                continue
            method = raw_method[start + 1 : end]
            try:
                url_data = urllib.parse.urlparse(method)
            except ValueError:
                LOG.debug(f"Unsub has invalid method {method}. Ignoring.")
                continue
            if url_data.scheme == "mailto":
                if url_data.path == config.UNSUBSCRIBER:
                    LOG.debug(
                        f"Skipping replacing unsubscribe since the original email already points to {config.UNSUBSCRIBER}"
                    )
                    out = {headers.LIST_UNSUBSCRIBE: unsubscribe_data}
                    if message[headers.LIST_UNSUBSCRIBE_POST]:
                        out[headers.LIST_UNSUBSCRIBE_POST] = str(
                            message[headers.LIST_UNSUBSCRIBE_POST]
                        )
                    return out
                query_data = urllib.parse.parse_qs(url_data.query)
                mailto_unsubs = (url_data.path, query_data.get("subject", [""])[0])
                LOG.debug(f"Unsub is mailto to {mailto_unsubs}")
            else:
                LOG.debug(f"Unsub has {url_data.scheme} scheme")
                other_unsubs.append(method)
        # If there are non mailto unsubscribe methods, use those in the header
        if other_unsubs:
            LOG.debug(f"Adding click unsub methods to header {other_unsubs}")
            return {
                headers.LIST_UNSUBSCRIBE: ", ".join(
                    [f"<{method}>" for method in other_unsubs]
                ),
                headers.LIST_UNSUBSCRIBE_POST: "List-Unsubscribe=One-Click",
            }
        elif not mailto_unsubs:
            LOG.debug("No unsubs. Deleting all unsub headers")
            return {}
        unsub_link = UnsubscribeEncoder.encode(
            UnsubscribeAction.OriginalUnsubscribeMailto,
            UnsubscribeOriginalData(alias.id, mailto_unsubs[0], mailto_unsubs[1]),
        )
        LOG.debug(f"Adding unsub link {unsub_link.link}")
        out = {headers.LIST_UNSUBSCRIBE: f"<{unsub_link.link}>"}
        if not unsub_link.via_email:
            out[headers.LIST_UNSUBSCRIBE_POST] = "List-Unsubscribe=One-Click"
        return out

    def __replace_unsub_headers(
        self, message, unsub_headers: dict[str, str]
    ) -> Message:
        delete_header(message, headers.LIST_UNSUBSCRIBE)
        delete_header(message, headers.LIST_UNSUBSCRIBE_POST)
        for header in unsub_headers:
            add_or_replace_header(message, header, unsub_headers[header])
        return message

    def _add_unsubscribe_header(
        self, message: Message, unsub: UnsubscribeData
    ) -> Message:
        unsub_link = UnsubscribeEncoder.encode(unsub.action, unsub.data)

        add_or_replace_header(message, headers.LIST_UNSUBSCRIBE, f"<{unsub_link.link}>")
        if not unsub_link.via_email:
            add_or_replace_header(
                message, headers.LIST_UNSUBSCRIBE_POST, "List-Unsubscribe=One-Click"
            )
        return message

    def add_header_to_message(
        self, alias: Alias, contact: Contact, message: Message
    ) -> Message:
        """
        Add List-Unsubscribe header based on the user preference.
        """
        unsub_behaviour = alias.user.unsub_behaviour
        original_unsub_proxied = self._calculate_header_with_original_behaviour(
            alias, message
        )
        message = self.__preserve_original_headers(message, original_unsub_proxied)
        if unsub_behaviour == UnsubscribeBehaviourEnum.PreserveOriginal:
            return self.__replace_unsub_headers(message, original_unsub_proxied)
        elif unsub_behaviour == UnsubscribeBehaviourEnum.DisableAlias:
            unsub = UnsubscribeData(UnsubscribeAction.DisableAlias, alias.id)
            return self._add_unsubscribe_header(message, unsub)
        else:
            unsub = UnsubscribeData(UnsubscribeAction.DisableContact, contact.id)
            return self._add_unsubscribe_header(message, unsub)

    def __preserve_original_headers(
        self, message: Message, original_unsub_proxied: dict[str, str]
    ) -> Message:
        unsubscribe_data = message[headers.LIST_UNSUBSCRIBE]
        if unsubscribe_data:
            add_or_replace_header(
                message, headers.SL_ORIGINAL_LIST_UNSUBSCRIBE, unsubscribe_data
            )
        unsubscribe_data = message[headers.LIST_UNSUBSCRIBE_POST]
        if unsubscribe_data:
            add_or_replace_header(
                message, headers.SL_ORIGINAL_LIST_UNSUBSCRIBE_POST, unsubscribe_data
            )
        for header in original_unsub_proxied:
            add_or_replace_header(
                message, f"X-SL-Proxy-{header}", original_unsub_proxied[header]
            )

        return message
