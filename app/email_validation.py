from email_validator import (
    validate_email,
    EmailNotValidError,
)

from app.utils import convert_to_id

# allow also + and @ that are present in a reply address
_ALLOWED_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.+@"


def is_valid_email(email_address: str) -> bool:
    """
    Used to check whether an email address is valid
    NOT run MX check.
    NOT allow unicode.
    """
    try:
        validate_email(email_address, check_deliverability=False, allow_smtputf8=False)
        return True
    except EmailNotValidError:
        return False


def normalize_reply_email(reply_email: str) -> str:
    """Handle the case where reply email contains *strange* char that was wrongly generated in the past"""
    if not reply_email.isascii():
        reply_email = convert_to_id(reply_email)

    ret = []
    # drop all control characters like shift, separator, etc
    for c in reply_email:
        if c not in _ALLOWED_CHARS:
            ret.append("_")
        else:
            ret.append(c)

    return "".join(ret)
