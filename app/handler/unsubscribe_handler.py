from email.message import Message, EmailMessage
from email.utils import make_msgid, formatdate
from typing import Optional

from aiosmtpd.smtp import Envelope

from app import config
from app.db import Session
from app.email import headers, status
from app.email_utils import (
    send_email,
    render,
    get_email_domain_part,
    add_dkim_signature,
    generate_verp_email,
)
from app.handler.unsubscribe_encoder import (
    UnsubscribeData,
    UnsubscribeEncoder,
    UnsubscribeAction,
    UnsubscribeOriginalData,
)
from app.log import LOG
from app.mail_sender import sl_sendmail
from app.models import (
    Alias,
    Contact,
    User,
    Mailbox,
    TransactionalEmail,
    VerpType,
)
from app.utils import sanitize_email


class UnsubscribeHandler:
    def _extract_unsub_info_from_message(
        self, message: Message
    ) -> Optional[UnsubscribeData]:
        header_value = message[headers.SUBJECT]
        if not header_value:
            return None
        return UnsubscribeEncoder.decode_subject(header_value)

    def handle_unsubscribe_from_message(self, envelope: Envelope, msg: Message) -> str:
        unsub_data = self._extract_unsub_info_from_message(msg)
        if not unsub_data:
            LOG.w("Wrong format subject %s", msg[headers.SUBJECT])
            return status.E507
        mailbox = Mailbox.get_by(email=envelope.mail_from)
        if not mailbox:
            LOG.w("Unknown mailbox %s", msg[headers.SUBJECT])
            return status.E507

        if unsub_data.action == UnsubscribeAction.DisableAlias:
            return self._disable_alias(unsub_data.data, mailbox.user, mailbox)
        elif unsub_data.action == UnsubscribeAction.DisableContact:
            return self._disable_contact(unsub_data.data, mailbox.user, mailbox)
        elif unsub_data.action == UnsubscribeAction.UnsubscribeNewsletter:
            return self._unsubscribe_user_from_newsletter(unsub_data.data, mailbox.user)
        elif unsub_data.action == UnsubscribeAction.OriginalUnsubscribeMailto:
            return self._unsubscribe_original_behaviour(unsub_data.data, mailbox.user)
        else:
            raise Exception(f"Unknown unsubscribe action {unsub_data.action}")

    def handle_unsubscribe_from_request(
        self, user: User, unsub_request: str
    ) -> Optional[UnsubscribeData]:
        unsub_data = UnsubscribeEncoder.decode_subject(unsub_request)
        if not unsub_data:
            LOG.w("Wrong request %s", unsub_request)
            return None
        if unsub_data.action == UnsubscribeAction.DisableAlias:
            response_code = self._disable_alias(unsub_data.data, user)
        elif unsub_data.action == UnsubscribeAction.DisableContact:
            response_code = self._disable_contact(unsub_data.data, user)
        elif unsub_data.action == UnsubscribeAction.UnsubscribeNewsletter:
            response_code = self._unsubscribe_user_from_newsletter(
                unsub_data.data, user
            )
        elif unsub_data.action == UnsubscribeAction.OriginalUnsubscribeMailto:
            response_code = self._unsubscribe_original_behaviour(unsub_data.data, user)
        else:
            raise Exception(f"Unknown unsubscribe action {unsub_data.action}")
        if response_code == status.E202:
            return unsub_data
        return None

    def _disable_alias(
        self, alias_id: int, user: User, mailbox: Optional[Mailbox] = None
    ) -> str:
        alias = Alias.get(alias_id)
        if not alias:
            return status.E508
        if alias.user_id != user.id:
            LOG.w("Alias doesn't belong to user")
            return status.E508

        # Only alias's owning mailbox can send the unsubscribe request
        if mailbox and not self._check_email_is_authorized_for_alias(
            mailbox.email, alias
        ):
            return status.E509
        alias.enabled = False
        Session.commit()
        enable_alias_url = config.URL + f"/dashboard/?highlight_alias_id={alias.id}"
        for mailbox in alias.mailboxes:
            send_email(
                mailbox.email,
                f"Alias {alias.email} has been disabled successfully",
                render(
                    "transactional/unsubscribe-disable-alias.txt",
                    user=alias.user,
                    alias=alias.email,
                    enable_alias_url=enable_alias_url,
                ),
                render(
                    "transactional/unsubscribe-disable-alias.html",
                    user=alias.user,
                    alias=alias.email,
                    enable_alias_url=enable_alias_url,
                ),
            )
        return status.E202

    def _disable_contact(
        self, contact_id: int, user: User, mailbox: Optional[Mailbox] = None
    ) -> str:
        contact = Contact.get(contact_id)
        if not contact:
            return status.E508
        if contact.user_id != user.id:
            LOG.w("Contact doesn't belong to user")
            return status.E508

        # Only contact's owning mailbox can send the unsubscribe request
        if mailbox and not self._check_email_is_authorized_for_alias(
            mailbox.email, contact.alias
        ):
            return status.E509
        alias = contact.alias
        contact.block_forward = True
        Session.commit()
        unblock_contact_url = (
            config.URL
            + f"/dashboard/alias_contact_manager/{alias.id}?highlight_contact_id={contact.id}"
        )
        for mailbox in alias.mailboxes:
            send_email(
                mailbox.email,
                f"Emails from {contact.website_email} to {alias.email} are now blocked",
                render(
                    "transactional/unsubscribe-block-contact.txt.jinja2",
                    user=alias.user,
                    alias=alias,
                    contact=contact,
                    unblock_contact_url=unblock_contact_url,
                ),
            )
        return status.E202

    def _unsubscribe_user_from_newsletter(
        self, user_id: int, request_user: User
    ) -> str:
        """return the SMTP status"""
        user = User.get(user_id)
        if not user:
            LOG.w("No such user %s", user_id)
            return status.E510

        if user.id != request_user.id:
            LOG.w("Unauthorized unsubscribe user from", request_user)
            return status.E511
        user.notification = False
        Session.commit()

        send_email(
            user.email,
            "You have been unsubscribed from SimpleLogin newsletter",
            render(
                "transactional/unsubscribe-newsletter.txt",
                user=user,
            ),
            render(
                "transactional/unsubscribe-newsletter.html",
                user=user,
            ),
        )
        return status.E202

    def _check_email_is_authorized_for_alias(
        self, email_address: str, alias: Alias
    ) -> bool:
        """return if the email_address is authorized to unsubscribe from an alias or block a contact
        Usually the mail_from=mailbox.email but it can also be one of the authorized address
        """
        for mailbox in alias.mailboxes:
            if mailbox.email == email_address:
                return True

            for authorized_address in mailbox.authorized_addresses:
                if authorized_address.email == email_address:
                    LOG.d(
                        "Found an authorized address for %s %s %s",
                        alias,
                        mailbox,
                        authorized_address,
                    )
                    return True

        LOG.d(
            "%s cannot disable alias %s. Alias authorized addresses:%s",
            email_address,
            alias,
            alias.authorized_addresses,
        )
        return False

    def _unsubscribe_original_behaviour(
        self, original_unsub_data: UnsubscribeOriginalData, user: User
    ) -> str:
        alias = Alias.get(original_unsub_data.alias_id)
        if not alias:
            return status.E508
        if alias.user_id != user.id:
            return status.E509
        email_domain = get_email_domain_part(alias.email)
        to_email = sanitize_email(original_unsub_data.recipient)
        msg = EmailMessage()
        msg[headers.TO] = to_email
        msg[headers.SUBJECT] = original_unsub_data.subject
        msg[headers.FROM] = alias.email
        msg[headers.MESSAGE_ID] = make_msgid(domain=email_domain)
        msg[headers.DATE] = formatdate()
        msg[headers.CONTENT_TYPE] = "text/plain"
        msg[headers.MIME_VERSION] = "1.0"
        msg.set_payload("")
        add_dkim_signature(msg, email_domain)

        transaction = TransactionalEmail.create(email=to_email, commit=True)
        sl_sendmail(
            generate_verp_email(
                VerpType.transactional, transaction.id, sender_domain=email_domain
            ),
            to_email,
            msg,
            retries=3,
            ignore_smtp_error=True,
        )
        return status.E202
