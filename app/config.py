import os
import subprocess

from dotenv import load_dotenv

SHA1 = subprocess.getoutput("git rev-parse HEAD")
ROOT_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


def get_abs_path(file_path: str):
    """append ROOT_DIR for relative path"""
    # Already absolute path
    if file_path.startswith("/"):
        return file_path
    else:
        return os.path.join(ROOT_DIR, file_path)


config_file = os.environ.get("CONFIG")
if config_file:
    config_file = get_abs_path(config_file)
    print("load config file", config_file)
    load_dotenv(get_abs_path(config_file))
else:
    load_dotenv()

RESET_DB = "RESET_DB" in os.environ
COLOR_LOG = "COLOR_LOG" in os.environ

# Allow user to have 1 year of premium: set the expiration_date to 1 year more
PROMO_CODE = "SIMPLEISBETTER"

# Debug mode
DEBUG = os.environ["DEBUG"] if "DEBUG" in os.environ else False
# Server url
URL = os.environ["URL"]
print(">>> URL:", URL)

SENTRY_DSN = os.environ.get("SENTRY_DSN")

# Email related settings
NOT_SEND_EMAIL = "NOT_SEND_EMAIL" in os.environ
EMAIL_DOMAIN = os.environ["EMAIL_DOMAIN"]
SUPPORT_EMAIL = os.environ["SUPPORT_EMAIL"]
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL")
MAX_NB_EMAIL_FREE_PLAN = int(os.environ["MAX_NB_EMAIL_FREE_PLAN"])
# allow to override postfix server locally
POSTFIX_SERVER = os.environ.get("POSTFIX_SERVER", "240.0.0.1")

# list of (priority, email server)
EMAIL_SERVERS_WITH_PRIORITY = eval(
    os.environ["EMAIL_SERVERS_WITH_PRIORITY"]
)  # [(10, "email.hostname.")]

# these emails are ignored when computing stats
if os.environ.get("IGNORED_EMAILS"):
    IGNORED_EMAILS = eval(os.environ.get("IGNORED_EMAILS"))
else:
    IGNORED_EMAILS = []

# disable the alias suffix, i.e. the ".random_word" part
DISABLE_ALIAS_SUFFIX = "DISABLE_ALIAS_SUFFIX" in os.environ

DKIM_PRIVATE_KEY_PATH = get_abs_path(os.environ["DKIM_PRIVATE_KEY_PATH"])
DKIM_PUBLIC_KEY_PATH = get_abs_path(os.environ["DKIM_PUBLIC_KEY_PATH"])
DKIM_SELECTOR = b"dkim"

with open(DKIM_PRIVATE_KEY_PATH) as f:
    DKIM_PRIVATE_KEY = f.read()


with open(DKIM_PUBLIC_KEY_PATH) as f:
    DKIM_DNS_VALUE = (
        f.read()
        .replace("-----BEGIN PUBLIC KEY-----", "")
        .replace("-----END PUBLIC KEY-----", "")
        .replace("\r", "")
        .replace("\n", "")
    )


DKIM_HEADERS = [b"from", b"to", b"subject"]

# Database
DB_URI = os.environ["DB_URI"]

# Flask secret
FLASK_SECRET = os.environ["FLASK_SECRET"]

# AWS
AWS_REGION = "eu-west-3"
BUCKET = os.environ["BUCKET"]
AWS_ACCESS_KEY_ID = os.environ["AWS_ACCESS_KEY_ID"]
AWS_SECRET_ACCESS_KEY = os.environ["AWS_SECRET_ACCESS_KEY"]

CLOUDWATCH_LOG_GROUP = CLOUDWATCH_LOG_STREAM = ""
ENABLE_CLOUDWATCH = "ENABLE_CLOUDWATCH" in os.environ
if ENABLE_CLOUDWATCH:
    CLOUDWATCH_LOG_GROUP = os.environ["CLOUDWATCH_LOG_GROUP"]
    CLOUDWATCH_LOG_STREAM = os.environ["CLOUDWATCH_LOG_STREAM"]

# Paddle
PADDLE_VENDOR_ID = int(os.environ["PADDLE_VENDOR_ID"])
PADDLE_MONTHLY_PRODUCT_ID = int(os.environ["PADDLE_MONTHLY_PRODUCT_ID"])
PADDLE_YEARLY_PRODUCT_ID = int(os.environ["PADDLE_YEARLY_PRODUCT_ID"])
PADDLE_PUBLIC_KEY_PATH = get_abs_path(os.environ["PADDLE_PUBLIC_KEY_PATH"])

# OpenID keys, used to sign id_token
OPENID_PRIVATE_KEY_PATH = get_abs_path(os.environ["OPENID_PRIVATE_KEY_PATH"])
OPENID_PUBLIC_KEY_PATH = get_abs_path(os.environ["OPENID_PUBLIC_KEY_PATH"])

# Used to generate random email
WORDS_FILE_PATH = get_abs_path(os.environ["WORDS_FILE_PATH"])


# Github, Google, Facebook client id and secrets
GITHUB_CLIENT_ID = os.environ["GITHUB_CLIENT_ID"]
GITHUB_CLIENT_SECRET = os.environ["GITHUB_CLIENT_SECRET"]


GOOGLE_CLIENT_ID = os.environ["GOOGLE_CLIENT_ID"]
GOOGLE_CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]

FACEBOOK_CLIENT_ID = os.environ["FACEBOOK_CLIENT_ID"]
FACEBOOK_CLIENT_SECRET = os.environ["FACEBOOK_CLIENT_SECRET"]

# in seconds
AVATAR_URL_EXPIRATION = 3600 * 24 * 7  # 1h*24h/d*7d=1week

# session key
HIGHLIGHT_GEN_EMAIL_ID = "highlight_gen_email_id"
MFA_USER_ID = "mfa_user_id"

FLASK_PROFILER_PATH = os.environ.get("FLASK_PROFILER_PATH")
FLASK_PROFILER_PASSWORD = os.environ.get("FLASK_PROFILER_PASSWORD")
