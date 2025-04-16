from dataclasses import dataclass
from email.message import Message
from itertools import batched
from typing import List

from email_validator import validate_email, EmailNotValidError
from flanker.addresslib import address
from flanker.addresslib.address import EmailAddress
from sqlalchemy import and_
from sqlalchemy.exc import IntegrityError

from app.db import Session
from app.email import headers
from app.email_utils import (
    get_header_unicode,
    add_or_replace_header,
    delete_header,
    generate_reply_email,
)
from app.log import LOG
from app.models import Alias, Contact
from app.utils import sanitize_email

_IN_BATCH_SIZE = 50


@dataclass
class MessageContacts:
    existing: dict[str, Contact]
    non_existing_to: set[EmailAddress]
    non_existing_cc: set[EmailAddress]


@dataclass
class HeaderReplacement:
    header: str
    replacement: str


@dataclass
class Replacements:
    contacts_to_create: List[Contact]
    contacts_to_update: List[Contact]
    headers_to_delete: List[str]
    headers_to_replace: List[HeaderReplacement]

    def __init__(self):
        self.contacts_to_create = []
        self.headers_to_delete = []
        self.contacts_to_update = []
        self.headers_to_replace = []


def _get_addresses_for_headers(
    msg: Message, message_headers: List[str]
) -> dict[str, set[EmailAddress]]:
    addresses: dict[str, set[EmailAddress]] = {h: set() for h in message_headers}
    for header in message_headers:
        header_value = msg.get_all(header, [])
        header_value = [get_header_unicode(h) for h in header_value]

        for value in header_value:
            for parsed in address.parse_list(value):
                addresses[header].add(parsed)

    return addresses


def _contacts_for_message(msg: Message, alias: Alias) -> MessageContacts:
    addresses = _get_addresses_for_headers(msg, [headers.TO, headers.CC])

    to_addresses = addresses[headers.TO]
    cc_addresses = addresses[headers.CC]

    all_addresses_set = set()
    all_addresses_set.update(to_addresses)
    all_addresses_set.update(cc_addresses)
    all_addresses = list(all_addresses_set)

    existing_contacts: dict[str, Contact] = {}
    non_existing_cc: set[EmailAddress] = set()
    non_existing_to: set[EmailAddress] = set()
    for chunk in batched(all_addresses, _IN_BATCH_SIZE):
        chunk_addresses: List[EmailAddress] = [add.address for add in chunk]
        chunk_contacts = Contact.filter(
            and_(
                Contact.alias_id == alias.id, Contact.website_email.in_(chunk_addresses)
            )
        ).all()

        for contact in chunk_contacts:
            existing_contacts[contact.email] = contact

        if len(chunk_addresses) != len(chunk_contacts):
            # Check which ones are missing
            for chunk_address in chunk_addresses:
                if chunk_address not in existing_contacts:
                    if chunk_address in to_addresses:
                        non_existing_to.add(chunk_address)
                    elif chunk_address in cc_addresses:
                        non_existing_cc.add(chunk_address)

    return MessageContacts(
        existing=existing_contacts,
        non_existing_to=non_existing_to,
        non_existing_cc=non_existing_cc,
    )


def _calculate_replacements_for_header(
    msg: Message,
    alias: Alias,
    header: str,
    contacts: dict[str, Contact],
    replacements: Replacements,
):
    """
    Replace CC or To header by Reply emails in forward phase
    """
    new_addrs: [str] = []
    headers = msg.get_all(header, [])
    # headers can be an array of Header, convert it to string here
    headers = [get_header_unicode(h) for h in headers]

    full_addresses: [EmailAddress] = []
    for h in headers:
        full_addresses += address.parse_list(h)

    for full_address in full_addresses:
        contact_email = sanitize_email(full_address.address, not_lower=True)

        # no transformation when alias is already in the header
        if contact_email.lower() == alias.email:
            new_addrs.append(full_address.full_spec())
            continue

        try:
            # NOT allow unicode for contact address
            validate_email(
                contact_email, check_deliverability=False, allow_smtputf8=False
            )
        except EmailNotValidError:
            LOG.w("invalid contact email %s. %s. Skip", contact_email, headers)
            continue

        contact_name = full_address.display_name
        if len(contact_name) >= Contact.MAX_NAME_LENGTH:
            contact_name = contact_name[0 : Contact.MAX_NAME_LENGTH]

        contact = contacts.get(contact_email, None)
        if contact:
            # update the contact name if needed
            if contact.name != full_address.display_name:
                LOG.d(
                    "Update contact %s name %s to %s",
                    contact,
                    contact.name,
                    contact_name,
                )
                contact.name = contact_name
                replacements.contacts_to_update.append(contact)
        else:
            LOG.d(
                "create contact for alias %s and email %s, header %s",
                alias,
                contact_email,
                header,
            )

            try:
                contact = Contact.create(
                    user_id=alias.user_id,
                    alias_id=alias.id,
                    website_email=contact_email,
                    name=contact_name,
                    reply_email=generate_reply_email(contact_email, alias),
                    is_cc=header.lower() == "cc",
                    automatic_created=True,
                )
                replacements.contacts_to_create.append(contact)
            except IntegrityError:
                LOG.w("Contact %s %s already exist", alias, contact_email)
                Session.rollback()
                contact = Contact.get_by(alias_id=alias.id, website_email=contact_email)

        new_addrs.append(contact.new_addr())

    if new_addrs:
        new_header = ",".join(new_addrs)
        LOG.d("Replace %s header, old: %s, new: %s", header, msg[header], new_header)
        replacements.headers_to_replace.append(
            HeaderReplacement(header=header, replacement=new_header)
        )
    else:
        LOG.d("Delete %s header, old value %s", header, msg[header])
        replacements.headers_to_delete.append(header)


def calculate_forward_replacements(
    message: Message, alias: Alias, contacts: dict[str, Contact]
) -> Replacements:
    replacements = Replacements()
    _calculate_replacements_for_header(
        message, alias, headers.TO, contacts, replacements
    )
    _calculate_replacements_for_header(
        message, alias, headers.CC, contacts, replacements
    )
    return replacements


def replace_headers_when_forward(
    message: Message, alias: Alias, max_contacts_to_create_limit: int
) -> bool:
    contacts = _contacts_for_message(message, alias)

    total_contacts_to_create = len(contacts.non_existing_to) + len(
        contacts.non_existing_cc
    )
    if total_contacts_to_create > max_contacts_to_create_limit:
        LOG.i(
            f"Would have tried to create {total_contacts_to_create} contacts, but only {max_contacts_to_create_limit} allowed"
        )
        return False

    replacements = calculate_forward_replacements(message, alias, contacts.existing)

    if len(replacements.contacts_to_create) > max_contacts_to_create_limit:
        return False

    for replacement in replacements.headers_to_replace:
        add_or_replace_header(message, replacement.header, replacement.replacement)

    for header in replacements.headers_to_delete:
        delete_header(message, header)

    return True
