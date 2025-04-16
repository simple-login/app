from email.message import Message
from typing import List, Optional


from app.db import Session
from app.email import headers
from app.email.forward_replacements import replace_headers_when_forward
from app.email_utils import generate_reply_email
from app.models import Alias, Contact
from app.utils import random_string
from tests.utils import create_new_user, random_email


def _emails_to_header(emails: List[str]) -> str:
    return ", ".join(emails)


def _email_list(size: int, initial: Optional[List[str]] = None) -> str:
    emails = initial or []
    for i in range(size):
        emails.append(random_email())

    return _emails_to_header(emails)


def _contacts_for_alias(alias: Alias) -> List[Contact]:
    return Contact.filter_by(alias_id=alias.id).order_by(Contact.id.asc()).all()


def _create_contact_for_alias(email: str, name: str, alias: Alias) -> Contact:
    return Contact.create(
        user_id=alias.user_id,
        alias_id=alias.id,
        website_email=email,
        name=name,
        reply_email=generate_reply_email(email, alias),
        is_cc=False,
        automatic_created=True,
    )


def test_does_nothing_on_empty_message():
    user = create_new_user()
    alias = Alias.create_new_random(user)
    res = replace_headers_when_forward(Message(), alias, 10)
    assert res is True


def test_does_nothing_with_empty_to_and_cc():
    user = create_new_user()
    alias = Alias.create_new_random(user)
    message = Message()
    message[headers.TO] = _email_list(0)
    message[headers.CC] = _email_list(0)

    res = replace_headers_when_forward(message, alias, 10)
    assert res is True


def test_does_not_create_contacts_if_already_exist():
    user = create_new_user()
    alias = Alias.create_new_random(user)

    contact_email1 = random_email()
    contact_name_1 = random_string()
    contact_email2 = random_email()
    contact_name_2 = random_string()
    existing_contact1 = _create_contact_for_alias(
        email=contact_email1, name=contact_name_1, alias=alias
    )
    existing_contact2 = _create_contact_for_alias(
        email=contact_email2, name=contact_name_2, alias=alias
    )

    message_to = _email_list(0, [contact_email1])
    message_cc = _email_list(0, [contact_email2])

    message = Message()
    message[headers.TO] = message_to
    message[headers.CC] = message_cc

    assert len(_contacts_for_alias(alias)) == 2

    res = replace_headers_when_forward(message, alias, 10)
    assert res is True
    Session.commit()

    # Assert no new contacts have been created
    contacts_for_alias = _contacts_for_alias(alias)
    assert len(contacts_for_alias) == 2
    assert contacts_for_alias[0].id == existing_contact1.id
    assert contacts_for_alias[1].id == existing_contact2.id

    # Assert headers
    assert message[headers.TO] == existing_contact1.new_addr()
    assert message[headers.CC] == existing_contact2.new_addr()


def test_only_creates_contacts_that_did_not_exist():
    user = create_new_user()
    alias = Alias.create_new_random(user)

    contact_email = random_email()
    contact_name = random_string()
    existing_contact = _create_contact_for_alias(
        email=contact_email, name=contact_name, alias=alias
    )

    new_email = random_email()
    message_to = _emails_to_header([contact_email, new_email])

    message = Message()
    message[headers.TO] = message_to
    message[headers.CC] = _emails_to_header([])

    assert len(_contacts_for_alias(alias)) == 1

    res = replace_headers_when_forward(message, alias, 10)
    assert res is True
    Session.commit()

    # Assert 1 new contact has been created
    contacts_for_alias = _contacts_for_alias(alias)
    assert len(contacts_for_alias) == 2
    assert contacts_for_alias[0].id == existing_contact.id
    assert contacts_for_alias[1].website_email == new_email

    # Assert headers
    assert message[headers.TO] == ",".join(
        [contacts_for_alias[0].new_addr(), contacts_for_alias[1].new_addr()]
    )

    # Empty header gets removed
    assert message[headers.CC] is None


def test_cannot_create_more_contacts_than_allowed():
    user = create_new_user()
    alias = Alias.create_new_random(user)

    contact_email = random_email()
    contact_name = random_string()
    _existing_contact = _create_contact_for_alias(
        email=contact_email, name=contact_name, alias=alias
    )

    contacts_to_create = 2
    max_contacts_to_create_limit = 1

    message_to = _emails_to_header(
        [contact_email, *[random_email() for _ in range(contacts_to_create)]]
    )

    message = Message()
    message[headers.TO] = message_to
    message[headers.CC] = _emails_to_header([])

    assert len(_contacts_for_alias(alias)) == 1

    # Would try to create 2 but can only create 1
    res = replace_headers_when_forward(message, alias, max_contacts_to_create_limit)
    assert res is False
