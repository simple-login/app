import enum

HEADER_ALLOW_API_COOKIES = "X-Sl-Allowcookies"
DMARC_RECORD = "v=DMARC1; p=quarantine; pct=100; adkim=s; aspf=s"
HKDF_INFO_TEMPLATE = "enc_key.ab.sl.proton.me:%s"
AEAD_AAD_DATA = "data.ab.sl.proton.me"


class JobType(enum.Enum):
    ONBOARDING_1 = "onboarding-1"
    ONBOARDING_2 = "onboarding-2"
    ONBOARDING_4 = "onboarding-4"
    BATCH_IMPORT = "batch-import"
    DELETE_ACCOUNT = "delete-account"
    DELETE_MAILBOX = "delete-mailbox"
    DELETE_DOMAIN = "delete-domain"
    SEND_USER_REPORT = "send-user-report"
    SEND_PROTON_WELCOME_1 = "proton-welcome-1"
    SEND_ALIAS_CREATION_EVENTS = "send-alias-creation-events"
    SEND_EVENT_TO_WEBHOOK = "send-event-to-webhook"
    SYNC_SUBSCRIPTION = "sync-subscription"
    ABUSER_MARK = "abuser-mark"
