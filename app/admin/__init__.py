"""Admin models for Flask-Admin views."""

from app.admin.index import init_admin
from app.admin.base import SLModelView, SLAdminIndexView
from app.admin.user import UserAdmin
from app.admin.email_log import EmailLogAdmin
from app.admin.alias import AliasAdmin
from app.admin.mailbox import MailboxAdmin
from app.admin.coupon import CouponAdmin
from app.admin.manual_subscription import ManualSubscriptionAdmin
from app.admin.custom_domain import CustomDomainAdmin
from app.admin.referral import ReferralAdmin
from app.admin.admin_audit_log import AdminAuditLogAdmin
from app.admin.provider_complaint import ProviderComplaintAdmin
from app.admin.newsletter import NewsletterAdmin, NewsletterUserAdmin
from app.admin.metrics import DailyMetricAdmin, MetricAdmin
from app.admin.invalid_mailbox_domain import InvalidMailboxDomainAdmin
from app.admin.forbidden_mx_ip import ForbiddenMxIpAdmin
from app.admin.email_search import (
    EmailSearchResult,
    EmailSearchHelpers,
    EmailSearchAdmin,
)
from app.admin.custom_domain_search import (
    CustomDomainWithValidationData,
    CustomDomainSearchResult,
    CustomDomainSearchHelpers,
    CustomDomainSearchAdmin,
)
from app.admin.abuser_lookup import AbuserLookupResult, AbuserLookupAdmin

__all__ = [
    # Initialization
    "init_admin",
    # Base classes
    "SLModelView",
    "SLAdminIndexView",
    # Model views
    "UserAdmin",
    "EmailLogAdmin",
    "AliasAdmin",
    "MailboxAdmin",
    "CouponAdmin",
    "ManualSubscriptionAdmin",
    "CustomDomainAdmin",
    "ReferralAdmin",
    "AdminAuditLogAdmin",
    "ProviderComplaintAdmin",
    "NewsletterAdmin",
    "NewsletterUserAdmin",
    "DailyMetricAdmin",
    "MetricAdmin",
    "InvalidMailboxDomainAdmin",
    "ForbiddenMxIpAdmin",
    # Search views
    "EmailSearchResult",
    "EmailSearchHelpers",
    "EmailSearchAdmin",
    "CustomDomainWithValidationData",
    "CustomDomainSearchResult",
    "CustomDomainSearchHelpers",
    "CustomDomainSearchAdmin",
    "AbuserLookupResult",
    "AbuserLookupAdmin",
]
