from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager

login_manager = LoginManager()
login_manager.session_protection = "strong"

# Setup rate limit facility
limiter = Limiter(key_func=get_remote_address)


# @limiter.request_filter
# def ip_whitelist():
#     # Uncomment line to test rate limit in dev environment
#     # return False
#     # No limit for local development
#     return request.remote_addr == "127.0.0.1"
