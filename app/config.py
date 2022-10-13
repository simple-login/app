import os
import random
import socket
import string
from ast import literal_eval
from typing import Callable, List
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


def get_abs_path(file_path: str):
    """append ROOT_DIR for relative path"""
    # Already absolute path
    if file_path.startswith("/"):
        return file_path
    else:
        return os.path.join(ROOT_DIR, file_path)


def sl_getenv(env_var: str, default_factory: Callable = None):
    """
    Get env value, convert into Python object
    Args:
        env_var (str): env var, example: SL_DB
        default_factory: returns value if this env var is not set.

    """
    value = os.getenv(env_var)
    if value is None:
        return default_factory()

    return literal_eval(value)


config_file = os.environ.get("CONFIG")
if config_file:
    config_file = get_abs_path(config_file)
    print("load config file", config_file)
    load_dotenv(get_abs_path(config_file))
else:
    load_dotenv()

COLOR_LOG = "COLOR_LOG" in os.environ

# Allow user to have 1 year of premium: set the expiration_date to 1 year more
PROMO_CODE = "SIMPLEISBETTER"

# Server url
URL = os.environ["URL"]
print(">>> URL:", URL)

# Calculate RP_ID for WebAuthn
RP_ID = urlparse(URL).hostname

SENTRY_DSN = os.environ.get("SENTRY_DSN")

# can use another sentry project for the front-end to avoid noises
SENTRY_FRONT_END_DSN = os.environ.get("SENTRY_FRONT_END_DSN") or SENTRY_DSN

# Email related settings
NOT_SEND_EMAIL = "NOT_SEND_EMAIL" in os.environ
EMAIL_DOMAIN = os.environ["EMAIL_DOMAIN"].lower()
SUPPORT_EMAIL = os.environ["SUPPORT_EMAIL"]
SUPPORT_NAME = os.environ.get("SUPPORT_NAME", "Son from SimpleLogin")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL")
# to receive monitoring daily report
MONITORING_EMAIL = os.environ.get("MONITORING_EMAIL")

# VERP: mail_from set to BOUNCE_PREFIX + email_log.id + BOUNCE_SUFFIX
BOUNCE_PREFIX = os.environ.get("BOUNCE_PREFIX") or "bounce+"
BOUNCE_SUFFIX = os.environ.get("BOUNCE_SUFFIX") or f"+@{EMAIL_DOMAIN}"

# Used for VERP during reply phase. It's similar to BOUNCE_PREFIX.
# It's needed when sending emails from custom domain to respect DMARC.
# BOUNCE_PREFIX_FOR_REPLY_PHASE should never be used in any existing alias
# and can't be used for creating a new alias on custom domain
# Note BOUNCE_PREFIX_FOR_REPLY_PHASE doesn't have the trailing plus sign (+) as BOUNCE_PREFIX
BOUNCE_PREFIX_FOR_REPLY_PHASE = (
    os.environ.get("BOUNCE_PREFIX_FOR_REPLY_PHASE") or "bounce_reply"
)

# VERP for transactional email: mail_from set to BOUNCE_PREFIX + email_log.id + BOUNCE_SUFFIX
TRANSACTIONAL_BOUNCE_PREFIX = (
    os.environ.get("TRANSACTIONAL_BOUNCE_PREFIX") or "transactional+"
)
TRANSACTIONAL_BOUNCE_SUFFIX = (
    os.environ.get("TRANSACTIONAL_BOUNCE_SUFFIX") or f"+@{EMAIL_DOMAIN}"
)

try:
    MAX_NB_EMAIL_FREE_PLAN = int(os.environ["MAX_NB_EMAIL_FREE_PLAN"])
except Exception:
    print("MAX_NB_EMAIL_FREE_PLAN is not set, use 5 as default value")
    MAX_NB_EMAIL_FREE_PLAN = 5

MAX_NB_EMAIL_OLD_FREE_PLAN = int(os.environ.get("MAX_NB_EMAIL_OLD_FREE_PLAN", 15))

# maximum number of directory a premium user can create
MAX_NB_DIRECTORY = 50
MAX_NB_SUBDOMAIN = 5

ENFORCE_SPF = "ENFORCE_SPF" in os.environ

# override postfix server locally
# use 240.0.0.1 here instead of 10.0.0.1 as existing SL instances use the 240.0.0.0 network
POSTFIX_SERVER = os.environ.get("POSTFIX_SERVER", "240.0.0.1")

DISABLE_REGISTRATION = "DISABLE_REGISTRATION" in os.environ

# allow using a different postfix port, useful when developing locally
POSTFIX_PORT = 25
if "POSTFIX_PORT" in os.environ:
    POSTFIX_PORT = int(os.environ["POSTFIX_PORT"])

# Use port 587 instead of 25 when sending emails through Postfix
# Useful when calling Postfix from an external network
POSTFIX_SUBMISSION_TLS = "POSTFIX_SUBMISSION_TLS" in os.environ

# ["domain1.com", "domain2.com"]
OTHER_ALIAS_DOMAINS = sl_getenv("OTHER_ALIAS_DOMAINS", list)
OTHER_ALIAS_DOMAINS = [d.lower().strip() for d in OTHER_ALIAS_DOMAINS]

# List of domains user can use to create alias
if "ALIAS_DOMAINS" in os.environ:
    ALIAS_DOMAINS = sl_getenv("ALIAS_DOMAINS")  # ["domain1.com", "domain2.com"]
else:
    ALIAS_DOMAINS = OTHER_ALIAS_DOMAINS + [EMAIL_DOMAIN]
ALIAS_DOMAINS = [d.lower().strip() for d in ALIAS_DOMAINS]

# ["domain1.com", "domain2.com"]
PREMIUM_ALIAS_DOMAINS = sl_getenv("PREMIUM_ALIAS_DOMAINS", list)
PREMIUM_ALIAS_DOMAINS = [d.lower().strip() for d in PREMIUM_ALIAS_DOMAINS]

# the alias domain used when creating the first alias for user
FIRST_ALIAS_DOMAIN = os.environ.get("FIRST_ALIAS_DOMAIN") or EMAIL_DOMAIN

# list of (priority, email server)
# e.g. [(10, "mx1.hostname."), (10, "mx2.hostname.")]
EMAIL_SERVERS_WITH_PRIORITY = sl_getenv("EMAIL_SERVERS_WITH_PRIORITY")

# disable the alias suffix, i.e. the ".random_word" part
DISABLE_ALIAS_SUFFIX = "DISABLE_ALIAS_SUFFIX" in os.environ

# the email address that receives all unsubscription request
UNSUBSCRIBER = os.environ.get("UNSUBSCRIBER")

# due to a typo, both UNSUBSCRIBER and OLD_UNSUBSCRIBER are supported
OLD_UNSUBSCRIBER = os.environ.get("OLD_UNSUBSCRIBER")

DKIM_SELECTOR = b"dkim"
DKIM_PRIVATE_KEY = None

if "DKIM_PRIVATE_KEY_PATH" in os.environ:
    DKIM_PRIVATE_KEY_PATH = get_abs_path(os.environ["DKIM_PRIVATE_KEY_PATH"])
    with open(DKIM_PRIVATE_KEY_PATH) as f:
        DKIM_PRIVATE_KEY = f.read()

# Database
DB_URI = os.environ["DB_URI"]

# Flask secret
FLASK_SECRET = os.environ["FLASK_SECRET"]
if not FLASK_SECRET:
    raise RuntimeError("FLASK_SECRET is empty. Please define it.")
SESSION_COOKIE_NAME = "slapp"
MAILBOX_SECRET = FLASK_SECRET + "mailbox"
CUSTOM_ALIAS_SECRET = FLASK_SECRET + "custom_alias"
UNSUBSCRIBE_SECRET = FLASK_SECRET + "unsub"

# AWS
AWS_REGION = os.environ.get("AWS_REGION") or "eu-west-3"
BUCKET = os.environ.get("BUCKET")
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")

# Paddle
try:
    PADDLE_VENDOR_ID = int(os.environ["PADDLE_VENDOR_ID"])
    PADDLE_MONTHLY_PRODUCT_ID = int(os.environ["PADDLE_MONTHLY_PRODUCT_ID"])
    PADDLE_YEARLY_PRODUCT_ID = int(os.environ["PADDLE_YEARLY_PRODUCT_ID"])
except (KeyError, ValueError):
    print("Paddle param not set")
    PADDLE_VENDOR_ID = -1
    PADDLE_MONTHLY_PRODUCT_ID = -1
    PADDLE_YEARLY_PRODUCT_ID = -1

# Other Paddle product IDS
PADDLE_MONTHLY_PRODUCT_IDS = sl_getenv("PADDLE_MONTHLY_PRODUCT_IDS", list)
PADDLE_MONTHLY_PRODUCT_IDS.append(PADDLE_MONTHLY_PRODUCT_ID)

PADDLE_YEARLY_PRODUCT_IDS = sl_getenv("PADDLE_YEARLY_PRODUCT_IDS", list)
PADDLE_YEARLY_PRODUCT_IDS.append(PADDLE_YEARLY_PRODUCT_ID)

PADDLE_PUBLIC_KEY_PATH = get_abs_path(
    os.environ.get("PADDLE_PUBLIC_KEY_PATH", "local_data/paddle.key.pub")
)

PADDLE_AUTH_CODE = os.environ.get("PADDLE_AUTH_CODE")

PADDLE_COUPON_ID = os.environ.get("PADDLE_COUPON_ID")

# OpenID keys, used to sign id_token
OPENID_PRIVATE_KEY_PATH = get_abs_path(
    os.environ.get("OPENID_PRIVATE_KEY_PATH", "local_data/jwtRS256.key")
)
OPENID_PUBLIC_KEY_PATH = get_abs_path(
    os.environ.get("OPENID_PUBLIC_KEY_PATH", "local_data/jwtRS256.key.pub")
)

# Used to generate random email
# words.txt is a list of English words and doesn't contain any "bad" word
# words_alpha.txt comes from https://github.com/dwyl/english-words and also contains bad words.
WORDS_FILE_PATH = get_abs_path(
    os.environ.get("WORDS_FILE_PATH", "local_data/words.txt")
)

# Used to generate random email
if os.environ.get("GNUPGHOME"):
    GNUPGHOME = get_abs_path(os.environ.get("GNUPGHOME"))
else:
    letters = string.ascii_lowercase
    random_dir_name = "".join(random.choice(letters) for _ in range(20))
    GNUPGHOME = f"/tmp/{random_dir_name}"
    if not os.path.exists(GNUPGHOME):
        os.mkdir(GNUPGHOME, mode=0o700)

    print("WARNING: Use a temp directory for GNUPGHOME", GNUPGHOME)

# Github, Google, Facebook client id and secrets
GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET")

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

FACEBOOK_CLIENT_ID = os.environ.get("FACEBOOK_CLIENT_ID")
FACEBOOK_CLIENT_SECRET = os.environ.get("FACEBOOK_CLIENT_SECRET")

PROTON_CLIENT_ID = os.environ.get("PROTON_CLIENT_ID")
PROTON_CLIENT_SECRET = os.environ.get("PROTON_CLIENT_SECRET")
PROTON_BASE_URL = os.environ.get(
    "PROTON_BASE_URL", "https://account.protonmail.com/api"
)
PROTON_VALIDATE_CERTS = "PROTON_VALIDATE_CERTS" in os.environ
CONNECT_WITH_PROTON = "CONNECT_WITH_PROTON" in os.environ
PROTON_EXTRA_HEADER_NAME = os.environ.get("PROTON_EXTRA_HEADER_NAME")
PROTON_EXTRA_HEADER_VALUE = os.environ.get("PROTON_EXTRA_HEADER_VALUE")

# in seconds
AVATAR_URL_EXPIRATION = 3600 * 24 * 7  # 1h*24h/d*7d=1week

# session key
MFA_USER_ID = "mfa_user_id"

FLASK_PROFILER_PATH = os.environ.get("FLASK_PROFILER_PATH")
FLASK_PROFILER_PASSWORD = os.environ.get("FLASK_PROFILER_PASSWORD")

# Job names
JOB_ONBOARDING_1 = "onboarding-1"
JOB_ONBOARDING_2 = "onboarding-2"
JOB_ONBOARDING_3 = "onboarding-3"
JOB_ONBOARDING_4 = "onboarding-4"
JOB_BATCH_IMPORT = "batch-import"
JOB_DELETE_ACCOUNT = "delete-account"
JOB_DELETE_MAILBOX = "delete-mailbox"
JOB_DELETE_DOMAIN = "delete-domain"
JOB_SEND_USER_REPORT = "send-user-report"
JOB_SEND_PROTON_WELCOME_1 = "proton-welcome-1"

# for pagination
PAGE_LIMIT = 20

# Upload to static/upload instead of s3
LOCAL_FILE_UPLOAD = "LOCAL_FILE_UPLOAD" in os.environ
UPLOAD_DIR = None

# Rate Limiting
# nb max of activity (forward/reply) an alias can have during 1 min
MAX_ACTIVITY_DURING_MINUTE_PER_ALIAS = 10

# nb max of activity (forward/reply) a mailbox can have during 1 min
MAX_ACTIVITY_DURING_MINUTE_PER_MAILBOX = 15

if LOCAL_FILE_UPLOAD:
    print("Upload files to local dir")
    UPLOAD_DIR = os.path.join(ROOT_DIR, "static/upload")
    if not os.path.exists(UPLOAD_DIR):
        print("Create upload dir")
        os.makedirs(UPLOAD_DIR)

LANDING_PAGE_URL = os.environ.get("LANDING_PAGE_URL") or "https://simplelogin.io"

STATUS_PAGE_URL = os.environ.get("STATUS_PAGE_URL") or "https://status.simplelogin.io"

# Loading PGP keys when mail_handler runs. To be used locally when init_app is not called.
LOAD_PGP_EMAIL_HANDLER = "LOAD_PGP_EMAIL_HANDLER" in os.environ

# Used when querying info on Apple API
# for iOS App
APPLE_API_SECRET = os.environ.get("APPLE_API_SECRET")
# for Mac App
MACAPP_APPLE_API_SECRET = os.environ.get("MACAPP_APPLE_API_SECRET")

# <<<<< ALERT EMAIL >>>>

# maximal number of alerts that can be sent to the same email in 24h
MAX_ALERT_24H = 4

# When a reverse-alias receives emails from un unknown mailbox
ALERT_REVERSE_ALIAS_UNKNOWN_MAILBOX = "reverse_alias_unknown_mailbox"

# When somebody is trying to spoof a reply
ALERT_DMARC_FAILED_REPLY_PHASE = "dmarc_failed_reply_phase"

# When a forwarding email is bounced
ALERT_BOUNCE_EMAIL = "bounce"

ALERT_BOUNCE_EMAIL_REPLY_PHASE = "bounce-when-reply"

# When a forwarding email is detected as spam
ALERT_SPAM_EMAIL = "spam"

# When an email is sent from a mailbox to an alias - a cycle
ALERT_SEND_EMAIL_CYCLE = "cycle"

ALERT_NON_REVERSE_ALIAS_REPLY_PHASE = "non_reverse_alias_reply_phase"

ALERT_FROM_ADDRESS_IS_REVERSE_ALIAS = "from_address_is_reverse_alias"

ALERT_TO_NOREPLY = "to_noreply"

ALERT_SPF = "spf"

ALERT_INVALID_TOTP_LOGIN = "invalid_totp_login"

# when a mailbox is also an alias
# happens when user adds a mailbox with their domain
# then later adds this domain into SimpleLogin
ALERT_MAILBOX_IS_ALIAS = "mailbox_is_alias"

AlERT_WRONG_MX_RECORD_CUSTOM_DOMAIN = "custom_domain_mx_record_issue"

# alert when a new alias is about to be created on a disabled directory
ALERT_DIRECTORY_DISABLED_ALIAS_CREATION = "alert_directory_disabled_alias_creation"

ALERT_COMPLAINT_REPLY_PHASE = "alert_complaint_reply_phase"
ALERT_COMPLAINT_FORWARD_PHASE = "alert_complaint_forward_phase"
ALERT_COMPLAINT_TRANSACTIONAL_PHASE = "alert_complaint_transactional_phase"

ALERT_QUARANTINE_DMARC = "alert_quarantine_dmarc"

ALERT_DUAL_SUBSCRIPTION_WITH_PARTNER = "alert_dual_sub_with_partner"

# <<<<< END ALERT EMAIL >>>>

# Disable onboarding emails
DISABLE_ONBOARDING = "DISABLE_ONBOARDING" in os.environ

HCAPTCHA_SECRET = os.environ.get("HCAPTCHA_SECRET")
HCAPTCHA_SITEKEY = os.environ.get("HCAPTCHA_SITEKEY")

PLAUSIBLE_HOST = os.environ.get("PLAUSIBLE_HOST")
PLAUSIBLE_DOMAIN = os.environ.get("PLAUSIBLE_DOMAIN")

# server host
HOST = socket.gethostname()

SPAMASSASSIN_HOST = os.environ.get("SPAMASSASSIN_HOST")
# by default use a tolerant score
if "MAX_SPAM_SCORE" in os.environ:
    MAX_SPAM_SCORE = float(os.environ["MAX_SPAM_SCORE"])
else:
    MAX_SPAM_SCORE = 5.5

# use a more restrictive score when replying
if "MAX_REPLY_PHASE_SPAM_SCORE" in os.environ:
    MAX_REPLY_PHASE_SPAM_SCORE = float(os.environ["MAX_REPLY_PHASE_SPAM_SCORE"])
else:
    MAX_REPLY_PHASE_SPAM_SCORE = 5

PGP_SENDER_PRIVATE_KEY = None
PGP_SENDER_PRIVATE_KEY_PATH = os.environ.get("PGP_SENDER_PRIVATE_KEY_PATH")
if PGP_SENDER_PRIVATE_KEY_PATH:
    with open(get_abs_path(PGP_SENDER_PRIVATE_KEY_PATH)) as f:
        PGP_SENDER_PRIVATE_KEY = f.read()

# the signer address that signs outgoing encrypted emails
PGP_SIGNER = os.environ.get("PGP_SIGNER")

# emails that have empty From address is sent from this special reverse-alias
NOREPLY = os.environ.get("NOREPLY", f"noreply@{EMAIL_DOMAIN}")

# list of no reply addresses
NOREPLIES = sl_getenv("NOREPLIES", list) or [NOREPLY]

COINBASE_WEBHOOK_SECRET = os.environ.get("COINBASE_WEBHOOK_SECRET")
COINBASE_CHECKOUT_ID = os.environ.get("COINBASE_CHECKOUT_ID")
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
try:
    COINBASE_YEARLY_PRICE = float(os.environ["COINBASE_YEARLY_PRICE"])
except Exception:
    COINBASE_YEARLY_PRICE = 30.00

ALIAS_LIMIT = os.environ.get("ALIAS_LIMIT") or "100/day;50/hour;5/minute"

ENABLE_SPAM_ASSASSIN = "ENABLE_SPAM_ASSASSIN" in os.environ

ALIAS_RANDOM_SUFFIX_LENGTH = int(os.environ.get("ALIAS_RAND_SUFFIX_LENGTH", 5))

try:
    HIBP_SCAN_INTERVAL_DAYS = int(os.environ.get("HIBP_SCAN_INTERVAL_DAYS"))
except Exception:
    HIBP_SCAN_INTERVAL_DAYS = 7
HIBP_API_KEYS = sl_getenv("HIBP_API_KEYS", list) or []

POSTMASTER = os.environ.get("POSTMASTER")

# store temporary files, especially for debugging
TEMP_DIR = os.environ.get("TEMP_DIR")

# Store unsent emails
SAVE_UNSENT_DIR = os.environ.get("SAVE_UNSENT_DIR")
if SAVE_UNSENT_DIR and not os.path.isdir(SAVE_UNSENT_DIR):
    try:
        os.makedirs(SAVE_UNSENT_DIR)
    except FileExistsError:
        pass

# enable the alias automation disable: an alias can be automatically disabled if it has too many bounces
ALIAS_AUTOMATIC_DISABLE = "ALIAS_AUTOMATIC_DISABLE" in os.environ

# whether the DKIM signing is handled by Rspamd
RSPAMD_SIGN_DKIM = "RSPAMD_SIGN_DKIM" in os.environ

TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")

PHONE_PROVIDER_1_HEADER = "X-SimpleLogin-Secret"
PHONE_PROVIDER_1_SECRET = os.environ.get("PHONE_PROVIDER_1_SECRET")

PHONE_PROVIDER_2_HEADER = os.environ.get("PHONE_PROVIDER_2_HEADER")
PHONE_PROVIDER_2_SECRET = os.environ.get("PHONE_PROVIDER_2_SECRET")

ZENDESK_HOST = os.environ.get("ZENDESK_HOST")
ZENDESK_API_TOKEN = os.environ.get("ZENDESK_API_TOKEN")
ZENDESK_ENABLED = "ZENDESK_ENABLED" in os.environ

DMARC_CHECK_ENABLED = "DMARC_CHECK_ENABLED" in os.environ

# Bounces can happen after 5 days
VERP_MESSAGE_LIFETIME = 5 * 86400
VERP_PREFIX = os.environ.get("VERP_PREFIX") or "sl"
# Generate with python3 -c 'import secrets; print(secrets.token_hex(28))'
VERP_EMAIL_SECRET = os.environ.get("VERP_EMAIL_SECRET") or (
    FLASK_SECRET + "pleasegenerateagoodrandomtoken"
)
if len(VERP_EMAIL_SECRET) < 32:
    raise RuntimeError(
        "Please, set VERP_EMAIL_SECRET to a random string at least 32 chars long"
    )
ALIAS_TRANSFER_TOKEN_SECRET = os.environ.get("ALIAS_TRANSFER_TOKEN_SECRET") or (
    FLASK_SECRET + "aliastransfertoken"
)


def get_allowed_redirect_domains() -> List[str]:
    allowed_domains = sl_getenv("ALLOWED_REDIRECT_DOMAINS", list)
    if allowed_domains:
        return allowed_domains
    parsed_url = urlparse(URL)
    return [parsed_url.hostname]


ALLOWED_REDIRECT_DOMAINS = get_allowed_redirect_domains()


def setup_nameservers():
    nameservers = os.environ.get("NAMESERVERS", "1.1.1.1")
    return nameservers.split(",")


NAMESERVERS = setup_nameservers()

DISABLE_CREATE_CONTACTS_FOR_FREE_USERS = False
PARTNER_API_TOKEN_SECRET = os.environ.get("PARTNER_API_TOKEN_SECRET") or (
    FLASK_SECRET + "partnerapitoken"
)

JOB_MAX_ATTEMPTS = 5
JOB_TAKEN_RETRY_WAIT_MINS = 30

# MEM_STORE
MEM_STORE_URI = os.environ.get("MEM_STORE_URI", None)

# Recovery codes hash salt
RECOVERY_CODE_HMAC_SECRET = os.environ.get("RECOVERY_CODE_HMAC_SECRET") or (
    FLASK_SECRET + "generatearandomtoken"
)
if not RECOVERY_CODE_HMAC_SECRET or len(RECOVERY_CODE_HMAC_SECRET) < 16:
    raise RuntimeError(
        "Please define RECOVERY_CODE_HMAC_SECRET in your configuration with a random string at least 16 chars long"
    )


# the minimum rspamd spam score above which emails that fail DMARC should be quarantined
if "MIN_RSPAMD_SCORE_FOR_FAILED_DMARC" in os.environ:
    MIN_RSPAMD_SCORE_FOR_FAILED_DMARC = float(
        os.environ["MIN_RSPAMD_SCORE_FOR_FAILED_DMARC"]
    )
else:
    MIN_RSPAMD_SCORE_FOR_FAILED_DMARC = None

# run over all reverse alias for an alias and replace them with sender address
ENABLE_ALL_REVERSE_ALIAS_REPLACEMENT = (
    "ENABLE_ALL_REVERSE_ALIAS_REPLACEMENT" in os.environ
)

if ENABLE_ALL_REVERSE_ALIAS_REPLACEMENT:
    # max number of reverse alias that can be replaced
    MAX_NB_REVERSE_ALIAS_REPLACEMENT = int(
        os.environ["MAX_NB_REVERSE_ALIAS_REPLACEMENT"]
    )

DISABLE_RATE_LIMIT = "DISABLE_RATE_LIMIT" in os.environ
