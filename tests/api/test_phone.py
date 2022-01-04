import arrow

from app.models import (
    PhoneReservation,
    PhoneNumber,
    PhoneCountry,
    PhoneMessage,
)
from tests.utils import login


def test_phone_messages(flask_client):
    user = login(flask_client)

    country = PhoneCountry.create(name="FR", commit=True)
    number = PhoneNumber.create(
        country_id=country.id, number="+331234567890", active=True, commit=True
    )
    reservation = PhoneReservation.create(
        number_id=number.id,
        user_id=user.id,
        start=arrow.now().shift(hours=-1),
        end=arrow.now().shift(hours=1),
        commit=True,
    )

    # no messages yet
    r = flask_client.post(f"/api/phone/reservations/{reservation.id}")
    assert r.status_code == 200
    assert r.json == {"ended": False, "messages": []}

    # a message arrives
    PhoneMessage.create(
        number_id=number.id, from_number="from_number", body="body", commit=True
    )
    r = flask_client.post(f"/api/phone/reservations/{reservation.id}")
    assert len(r.json["messages"]) == 1
    msg = r.json["messages"][0]
    assert msg["body"] == "body"
    assert msg["from_number"] == "from_number"
    assert "created_at" in msg
    assert "id" in msg

    # print(json.dumps(r.json,  indent=2))


def test_phone_messages_ended_reservation(flask_client):
    user = login(flask_client)

    country = PhoneCountry.create(name="FR", commit=True)
    number = PhoneNumber.create(
        country_id=country.id, number="+331234567890", active=True, commit=True
    )
    reservation = PhoneReservation.create(
        number_id=number.id,
        user_id=user.id,
        start=arrow.now().shift(hours=-2),
        end=arrow.now().shift(hours=-1),  # reservation is ended
        commit=True,
    )

    r = flask_client.post(f"/api/phone/reservations/{reservation.id}")
    assert r.status_code == 200
    assert r.json == {"ended": True, "messages": []}
