from flask import url_for

from app.models import (
    Alias,
    Contact,
)
from tests.utils import login, random_email


def test_add_contact_success(flask_client):
    user = login(flask_client)
    alias = Alias.filter(Alias.user_id == user.id).first()

    assert Contact.filter_by(user_id=user.id).count() == 0

    email = random_email()
    # <<< Create a new contact >>>
    flask_client.post(
        url_for("dashboard.alias_contact_manager", alias_id=alias.id),
        data={
            "form-name": "create",
            "email": email,
        },
        follow_redirects=True,
    )
    # a new contact is added
    assert Contact.filter_by(user_id=user.id).count() == 1
    contact = Contact.filter_by(user_id=user.id).first()
    assert contact.website_email == email

    # <<< Create a new contact using a full email format >>>
    email = random_email()
    flask_client.post(
        url_for("dashboard.alias_contact_manager", alias_id=alias.id),
        data={
            "form-name": "create",
            "email": f"First Last <{email}>",
        },
        follow_redirects=True,
    )
    # a new contact is added
    assert Contact.filter_by(user_id=user.id).count() == 2
    contact = (
        Contact.filter_by(user_id=user.id).filter(Contact.id != contact.id).first()
    )
    assert contact.website_email == email
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
    assert Contact.filter_by(user_id=user.id).count() == 2
    assert "Invalid email format. Email must be either email@example.com" in str(r.data)
