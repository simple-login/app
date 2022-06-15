from app.config import CONNECT_WITH_PROTON, CONNECT_WITH_PROTON_COOKIE_NAME
from flask import request


def is_connect_with_proton_enabled() -> bool:
    if CONNECT_WITH_PROTON:
        return True
    if CONNECT_WITH_PROTON_COOKIE_NAME and request.cookies.get(
        CONNECT_WITH_PROTON_COOKIE_NAME
    ):
        return True
    return False
