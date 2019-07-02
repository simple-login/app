from app.config import EMAIL_DOMAIN
from app.models import generate_email


def test_generate_email(flask_client):
    email = generate_email()
    assert email.endswith("@" + EMAIL_DOMAIN)
