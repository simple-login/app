from functools import wraps

from flask import request, abort
from twilio.request_validator import RequestValidator
from twilio.twiml.messaging_response import MessagingResponse

from app.config import TWILIO_AUTH_TOKEN
from app.log import LOG
from app.models import PhoneNumber, PhoneMessage
from app.phone.base import phone_bp


def validate_twilio_request(f):
    """Validates that incoming requests genuinely originated from Twilio"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Create an instance of the RequestValidator class
        validator = RequestValidator(TWILIO_AUTH_TOKEN)

        # Validate the request using its URL, POST data,
        # and X-TWILIO-SIGNATURE header
        request_valid = validator.validate(
            request.url, request.form, request.headers.get("X-TWILIO-SIGNATURE", "")
        )

        # Continue processing the request if it's valid, return a 403 error if
        # it's not
        if request_valid:
            return f(*args, **kwargs)
        else:
            return abort(403)

    return decorated_function


@phone_bp.route("/twilio/sms", methods=["GET", "POST"])
@validate_twilio_request
def twilio_sms():
    LOG.d("%s %s %s", request.args, request.form, request.data)
    resp = MessagingResponse()

    to_number = request.form.get("To")
    from_number = request.form.get("From")
    body = request.form.get("Body")

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
    return str(resp)
