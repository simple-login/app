from flask import url_for

from app import config
from app.models import EmailChange
from app.utils import canonicalize_email
from tests.utils import login, random_email, create_new_user


def test_setup_done(flask_client):
    config.SKIP_MX_LOOKUP_ON_CHECK = True
    user = create_new_user()
    login(flask_client, user)
    noncanonical_email = f"nonca.{random_email()}"

    r = flask_client.post(
        url_for("dashboard.account_setting"),
        data={
            "form-name": "update-email",
            "email": noncanonical_email,
        },
        follow_redirects=True,
    )

    assert r.status_code == 200
    email_change = EmailChange.get_by(user_id=user.id)
    assert email_change is not None
    assert email_change.new_email == canonicalize_email(noncanonical_email)
    config.SKIP_MX_LOOKUP_ON_CHECK = False
