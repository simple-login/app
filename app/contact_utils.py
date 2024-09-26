from dataclasses import dataclass
from enum import Enum
from typing import Optional

from sqlalchemy.exc import IntegrityError

from app.db import Session
from app.email_utils import generate_reply_email, parse_full_address
from app.email_validation import is_valid_email
from app.log import LOG
from app.models import Contact, Alias
from app.utils import sanitize_email


class ContactCreateError(Enum):
    InvalidEmail = "Invalid email"
    NotAllowed = "Your plan does not allow to create contacts"


@dataclass
class ContactCreateResult:
    contact: Optional[Contact]
    created: bool
    error: Optional[ContactCreateError]


def __update_contact_if_needed(
    contact: Contact, name: Optional[str], mail_from: Optional[str]
) -> ContactCreateResult:
    if name and contact.name != name:
        LOG.d(f"Setting {contact} name to {name}")
        contact.name = name
        Session.commit()
    if mail_from and contact.mail_from is None:
        LOG.d(f"Setting {contact} mail_from to {mail_from}")
        contact.mail_from = mail_from
        Session.commit()
    return ContactCreateResult(contact, created=False, error=None)


def create_contact(
    email: str,
    name: Optional[str],
    alias: Alias,
    mail_from: Optional[str] = None,
    allow_empty_email: bool = False,
    automatic_created: bool = False,
    from_partner: bool = False,
) -> ContactCreateResult:
    # If user cannot create contacts, they still need to be created when receiving an email for an alias
    if not automatic_created and not alias.user.can_create_contacts():
        return ContactCreateResult(
            None, created=False, error=ContactCreateError.NotAllowed
        )
    # Parse emails with form 'name <email>'
    try:
        email_name, email = parse_full_address(email)
    except ValueError:
        email = ""
        email_name = ""
    # If no name is explicitly given try to get it from the parsed email
    if name is None:
        name = email_name[: Contact.MAX_NAME_LENGTH]
    else:
        name = name[: Contact.MAX_NAME_LENGTH]
    # If still no name is there, make sure the name is None instead of empty string
    if not name:
        name = None
    if name is not None and "\x00" in name:
        LOG.w("Cannot use contact name because has \\x00")
        name = ""
    # Sanitize email and if it's not valid only allow to create a contact if it's explicitly allowed. Otherwise fail
    email = sanitize_email(email, not_lower=True)
    if not is_valid_email(email):
        LOG.w(f"invalid contact email {email}")
        if not allow_empty_email:
            return ContactCreateResult(
                None, created=False, error=ContactCreateError.InvalidEmail
            )
        LOG.d("Create a contact with invalid email for %s", alias)
        # either reuse a contact with empty email or create a new contact with empty email
        email = ""
    # If contact exists, update name and mail_from if needed
    contact = Contact.get_by(alias_id=alias.id, website_email=email)
    if contact is not None:
        return __update_contact_if_needed(contact, name, mail_from)
    # Create the contact
    reply_email = generate_reply_email(email, alias)
    try:
        flags = Contact.FLAG_PARTNER_CREATED if from_partner else 0
        contact = Contact.create(
            user_id=alias.user_id,
            alias_id=alias.id,
            website_email=email,
            name=name,
            reply_email=reply_email,
            mail_from=mail_from,
            automatic_created=automatic_created,
            flags=flags,
            invalid_email=email == "",
            commit=True,
        )
        LOG.d(
            f"Created contact {contact} for alias {alias} with email {email} invalid_email={contact.invalid_email}"
        )
    except IntegrityError:
        Session.rollback()
        LOG.info(
            f"Contact with email {email} for alias_id {alias.id} already existed, fetching from DB"
        )
        contact = Contact.get_by(alias_id=alias.id, website_email=email)
        return __update_contact_if_needed(contact, name, mail_from)
    return ContactCreateResult(contact, created=True, error=None)
