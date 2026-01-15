from flask import Flask
from flask_admin import Admin

from app.db import Session
from app.models import (
    User,
    Alias,
    Mailbox,
    Coupon,
    ManualSubscription,
    CustomDomain,
    AdminAuditLog,
    ProviderComplaint,
    Newsletter,
    NewsletterUser,
    DailyMetric,
    Metric2,
    InvalidMailboxDomain,
    ForbiddenMxIp,
)
from app.admin.base import SLAdminIndexView
from app.admin.user import UserAdmin
from app.admin.alias import AliasAdmin
from app.admin.mailbox import MailboxAdmin
from app.admin.coupon import CouponAdmin
from app.admin.manual_subscription import ManualSubscriptionAdmin
from app.admin.custom_domain import CustomDomainAdmin
from app.admin.admin_audit_log import AdminAuditLogAdmin
from app.admin.provider_complaint import ProviderComplaintAdmin
from app.admin.newsletter import NewsletterAdmin, NewsletterUserAdmin
from app.admin.metrics import DailyMetricAdmin, MetricAdmin
from app.admin.invalid_mailbox_domain import InvalidMailboxDomainAdmin
from app.admin.forbidden_mx_ip import ForbiddenMxIpAdmin
from app.admin.email_search import EmailSearchAdmin
from app.admin.custom_domain_search import CustomDomainSearchAdmin
from app.admin.abuser_lookup import AbuserLookupAdmin


def init_admin(app: Flask):
    admin = Admin(name="SimpleLogin", template_mode="bootstrap4")

    admin.init_app(app, index_view=SLAdminIndexView())
    admin.add_view(EmailSearchAdmin(name="Email Search", endpoint="admin.email_search"))
    admin.add_view(
        CustomDomainSearchAdmin(
            name="Custom domain search", endpoint="admin.custom_domain_search"
        )
    )
    admin.add_view(
        AbuserLookupAdmin(name="Abuser Lookup", endpoint="admin.abuser_lookup")
    )
    admin.add_view(UserAdmin(User, Session))
    admin.add_view(AliasAdmin(Alias, Session))
    admin.add_view(MailboxAdmin(Mailbox, Session))
    admin.add_view(CouponAdmin(Coupon, Session))
    admin.add_view(ManualSubscriptionAdmin(ManualSubscription, Session))
    admin.add_view(CustomDomainAdmin(CustomDomain, Session))
    admin.add_view(AdminAuditLogAdmin(AdminAuditLog, Session))
    admin.add_view(ProviderComplaintAdmin(ProviderComplaint, Session))
    admin.add_view(NewsletterAdmin(Newsletter, Session))
    admin.add_view(NewsletterUserAdmin(NewsletterUser, Session))
    admin.add_view(DailyMetricAdmin(DailyMetric, Session))
    admin.add_view(MetricAdmin(Metric2, Session))
    admin.add_view(InvalidMailboxDomainAdmin(InvalidMailboxDomain, Session))
    admin.add_view(ForbiddenMxIpAdmin(ForbiddenMxIp, Session))
