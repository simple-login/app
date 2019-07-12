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
    print("load config file", config_file)
    load_dotenv(get_abs_path(config_file))
else:
    load_dotenv()


URL = os.environ.get("URL") or "http://sl-server:7777"
print("URL:", URL)

EMAIL_DOMAIN = os.environ.get("EMAIL_DOMAIN") or "sl"
SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL") or "support@sl"
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY")
DB_URI = os.environ.get("DB_URI") or "sqlite:///db.sqlite"

FLASK_SECRET = os.environ.get("FLASK_SECRET") or "secret"

# invalidate the session at each new version by changing the secret
FLASK_SECRET = FLASK_SECRET + SHA1

ENABLE_SENTRY = "ENABLE_SENTRY" in os.environ
ENV = os.environ.get("ENV")

AWS_REGION = "eu-west-3"
BUCKET = os.environ.get("BUCKET") or "local.sl"
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")

ENABLE_CLOUDWATCH = "ENABLE_CLOUDWATCH" in os.environ
CLOUDWATCH_LOG_GROUP = os.environ.get("CLOUDWATCH_LOG_GROUP")
CLOUDWATCH_LOG_STREAM = os.environ.get("CLOUDWATCH_LOG_STREAM")

STRIPE_API = os.environ.get("STRIPE_API")  # Stripe public key
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_YEARLY_PLAN = os.environ.get("STRIPE_YEARLY_PLAN")
STRIPE_MONTHLY_PLAN = os.environ.get("STRIPE_MONTHLY_PLAN")

# Max number emails user can generate for free plan
MAX_NB_EMAIL_FREE_PLAN = int(os.environ.get("MAX_NB_EMAIL_FREE_PLAN"))

LYRA_ANALYTICS_ID = os.environ.get("LYRA_ANALYTICS_ID")

# Used to sign id_token
OPENID_PRIVATE_KEY_PATH = get_abs_path(os.environ["OPENID_PRIVATE_KEY_PATH"])
OPENID_PUBLIC_KEY_PATH = get_abs_path(os.environ["OPENID_PUBLIC_KEY_PATH"])

PARTNER_CODES = ["SL2019"]

# Allow user to have 1 year of premium: set the expiration_date to 1 year more
PROMO_CODE = "SIMPLEISBETTER"

WORDS_FILE_PATH = get_abs_path(os.environ["WORDS_FILE_PATH"])

GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET")


GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

FACEBOOK_CLIENT_ID = os.environ.get("FACEBOOK_CLIENT_ID")
FACEBOOK_CLIENT_SECRET = os.environ.get("FACEBOOK_CLIENT_SECRET")
