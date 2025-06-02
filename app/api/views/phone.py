import arrow
from flask import g
from flask import jsonify

from app.api.base import api_bp, require_api_auth
from app.models import (
    PhoneReservation,
    PhoneMessage,
)


@api_bp.route("/phone/reservations/<int:reservation_id>", methods=["GET", "POST"])
@require_api_auth
def phone_messages(reservation_id):
    """
    Return messages during this reservation
    Output:
        - messages: list of alias:
            - id
            - from_number
            - body
            - created_at: e.g. 5 minutes ago

    """
    user = g.user
    reservation: PhoneReservation = PhoneReservation.get(reservation_id)
    if not reservation or reservation.user_id != user.id:
        return jsonify(error="Invalid reservation"), 400

    phone_number = reservation.number
    messages = PhoneMessage.filter(
        PhoneMessage.number_id == phone_number.id,
        PhoneMessage.created_at > reservation.start,
        PhoneMessage.created_at < reservation.end,
    ).all()

    return (
        jsonify(
            messages=[
                {
                    "id": message.id,
                    "from_number": message.from_number,
                    "body": message.body,
                    "created_at": message.created_at.humanize(),
                }
                for message in messages
            ],
            ended=reservation.end < arrow.now(),
        ),
        200,
    )
