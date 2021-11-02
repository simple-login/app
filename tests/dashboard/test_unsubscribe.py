from app.models import (
    Alias,
)
from tests.utils import login


def test_add_contact_success(flask_client):
    login(flask_client)
    alias = Alias.first()

    flask_client.post(f"/dashboard/unsubscribe/{alias.id}")
    assert not alias.enabled
