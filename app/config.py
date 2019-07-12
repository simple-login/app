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


URL = os.environ["URL"]
print("URL:", URL)

EMAIL_DOMAIN = os.environ["EMAIL_DOMAIN"]
SUPPORT_EMAIL = os.environ["SUPPORT_EMAIL"]
SENDGRID_API_KEY = os.environ["SENDGRID_API_KEY"]
DB_URI = os.environ["DB_URI"]

FLASK_SECRET = os.environ["FLASK_SECRET"]

# invalidate the session at each new version by changing the secret
FLASK_SECRET = FLASK_SECRET + SHA1

ENABLE_SENTRY = "ENABLE_SENTRY" in os.environ
ENV = os.environ["ENV"]

AWS_REGION = "eu-west-3"
BUCKET = os.environ["BUCKET"]
AWS_ACCESS_KEY_ID = os.environ["AWS_ACCESS_KEY_ID"]
AWS_SECRET_ACCESS_KEY = os.environ["AWS_SECRET_ACCESS_KEY"]

ENABLE_CLOUDWATCH = "ENABLE_CLOUDWATCH" in os.environ
CLOUDWATCH_LOG_GROUP = os.environ["CLOUDWATCH_LOG_GROUP"]
CLOUDWATCH_LOG_STREAM = os.environ["CLOUDWATCH_LOG_STREAM"]

STRIPE_API = os.environ["STRIPE_API"]  # Stripe public key
STRIPE_SECRET_KEY = os.environ["STRIPE_SECRET_KEY"]
STRIPE_YEARLY_PLAN = os.environ["STRIPE_YEARLY_PLAN"]
STRIPE_MONTHLY_PLAN = os.environ["STRIPE_MONTHLY_PLAN"]

# Max number emails user can generate for free plan
MAX_NB_EMAIL_FREE_PLAN = int(os.environ["MAX_NB_EMAIL_FREE_PLAN"])

LYRA_ANALYTICS_ID = os.environ["LYRA_ANALYTICS_ID"]

# Used to sign id_token
OPENID_PRIVATE_KEY_PATH = get_abs_path(os.environ["OPENID_PRIVATE_KEY_PATH"])
OPENID_PUBLIC_KEY_PATH = get_abs_path(os.environ["OPENID_PUBLIC_KEY_PATH"])

PARTNER_CODES = ["SL2019"]

# Allow user to have 1 year of premium: set the expiration_date to 1 year more
PROMO_CODE = "SIMPLEISBETTER"

WORDS_FILE_PATH = get_abs_path(os.environ["WORDS_FILE_PATH"])

GITHUB_CLIENT_ID = os.environ["GITHUB_CLIENT_ID"]
GITHUB_CLIENT_SECRET = os.environ["GITHUB_CLIENT_SECRET"]


GOOGLE_CLIENT_ID = os.environ["GOOGLE_CLIENT_ID"]
GOOGLE_CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]

FACEBOOK_CLIENT_ID = os.environ["FACEBOOK_CLIENT_ID"]
FACEBOOK_CLIENT_SECRET = os.environ["FACEBOOK_CLIENT_SECRET"]
