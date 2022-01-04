from flask import request

from app.config import (
    PHONE_PROVIDER_1_HEADER,
    PHONE_PROVIDER_1_SECRET,
)
from app.log import LOG
from app.models import PhoneNumber, PhoneMessage
from app.phone.base import phone_bp


@phone_bp.route("/provider1/sms", methods=["GET", "POST"])
def provider1_sms():
    if request.headers.get(PHONE_PROVIDER_1_HEADER) != PHONE_PROVIDER_1_SECRET:
        LOG.e(
            "Unauthenticated callback %s %s %s %s",
            request.headers,
            request.method,
            request.args,
            request.data,
        )
        return "not ok", 200

    # request.form should be a dict that contains message_id, number, text, sim_card_number.
    # "number" is the contact number and "sim_card_number" the virtual number
    # The "reception_date" is in local time and shouldn't be used
    # For ex:
    # ImmutableMultiDict([('message_id', 'sms_0000000000000000000000'), ('number', '+33600112233'),
    # ('text', 'Lorem Ipsum is simply dummy text ...'), ('sim_card_number', '12345'),
    # ('reception_date', '2022-01-04 14:42:51')])
    to_number = request.form.get("sim_card_number")
    from_number = request.form.get("number")
    body = request.form.get("text")

    LOG.d("%s->%s:%s", from_number, to_number, body)

    phone_number = PhoneNumber.get_by(number=to_number)
    if phone_number:
        PhoneMessage.create(
            number_id=phone_number.id,
            from_number=from_number,
            body=body,
            commit=True,
        )
    else:
        LOG.e("Unknown phone number %s %s", to_number, request.form)
        return "not ok", 200
    return "ok", 200
