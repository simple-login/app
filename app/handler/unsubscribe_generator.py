from email.message import Message

from app.email import headers
from app.email_utils import add_or_replace_header
from app.models import Alias, Contact


class UnsubscribeGenerator:
    def add_header_to_message(
        self, alias: Alias, contact: Contact, message: Message
    ) -> Message:
        """
        Add List-Unsubscribe header
        """
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
