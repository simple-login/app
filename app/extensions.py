from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import current_user, LoginManager

from app import config

login_manager = LoginManager()
login_manager.session_protection = "strong"


# We want to rate limit based on:
# - If the user is not logged in: request source IP
# - If the user is logged in: user_id
def __key_func():
    if current_user.is_authenticated:
        return f"userid:{current_user.id}"
    else:
        ip_addr = get_remote_address()
        return f"ip:{ip_addr}"


# Setup rate limit facility
limiter = Limiter(key_func=__key_func)


@limiter.request_filter
def disable_rate_limit():
    return config.DISABLE_RATE_LIMIT


# @limiter.request_filter
# def ip_whitelist():
#     # Uncomment line to test rate limit in dev environment
#     # return False
#     # No limit for local development
#     return request.remote_addr == "127.0.0.1"
