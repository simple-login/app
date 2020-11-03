from flask import url_for

from app.config import EMAIL_DOMAIN
from app.models import (
    Alias,
    Contact,
)
from tests.utils import login


def test_add_contact_success(flask_client):
    login(flask_client)
    alias = Alias.first()

    assert Contact.query.count() == 0

    # <<< Create a new contact >>>
    flask_client.post(
        url_for("dashboard.alias_contact_manager", alias_id=alias.id),
        data={
            "form-name": "create",
            "email": "abcd@gmail.com",
        },
        follow_redirects=True,
    )
    # a new contact is added
    assert Contact.query.count() == 1
    contact = Contact.first()
    assert contact.website_email == "abcd@gmail.com"

    # <<< Create a new contact using a full email format >>>
    flask_client.post(
        url_for("dashboard.alias_contact_manager", alias_id=alias.id),
        data={
            "form-name": "create",
            "email": "First Last <another@gmail.com>",
        },
        follow_redirects=True,
    )
    # a new contact is added
    assert Contact.query.count() == 2
    contact = Contact.get(2)
    assert contact.website_email == "another@gmail.com"
    assert contact.name == "First Last"

    # <<< Create a new contact with invalid email address >>>
    r = flask_client.post(
        url_for("dashboard.alias_contact_manager", alias_id=alias.id),
        data={
            "form-name": "create",
            "email": "with space@gmail.com",
        },
        follow_redirects=True,
    )

    # no new contact is added
    assert Contact.query.count() == 2
    assert "Invalid email format. Email must be either email@example.com" in str(r.data)
