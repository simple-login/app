from app import config
from app.db import Session
from app.models import User, Job
from tests.utils import create_new_user, random_email


def test_available_sl_domains(flask_client):
    user = create_new_user()

    assert set(user.available_sl_domains()) == {"d1.test", "d2.test", "sl.local"}
    assert user.created_by_partner is False


def test_create_from_partner(flask_client):
    user = User.create(email=random_email(), from_partner=True)
    assert User.FLAG_CREATED_FROM_PARTNER == (
        user.flags & User.FLAG_CREATED_FROM_PARTNER
    )
    assert user.notification is False
    assert user.trial_end is None
    job = Session.query(Job).order_by(Job.id.desc()).first()
    assert job is not None
    assert job.name == config.JOB_SEND_PROTON_WELCOME_1
    assert job.payload.get("user_id") == user.id
    assert user.created_by_partner is True
