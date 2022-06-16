from app.models import User
from tests.utils import create_new_user, random_email


def test_available_sl_domains(flask_client):
    user = create_new_user()

    assert set(user.available_sl_domains()) == {"d1.test", "d2.test", "sl.local"}


def test_create_from_partner(flask_client):
    user = User.create(email=random_email(), from_partner=True)
    assert User.FLAG_CREATED_FROM_PARTNER == (
        user.flags & User.FLAG_CREATED_FROM_PARTNER
    )
    assert user.notification is False
    assert user.trial_end is None
