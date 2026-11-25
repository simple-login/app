from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from flask import request
from flask_admin import expose

from app.admin.base import BaseAdminView
from app.custom_domain_utils import (
    CannotUseDomainReason,
    CustomDomainCreationCheck,
    MAX_UNVERIFIED_CUSTOM_DOMAINS,
    check_custom_domain_creation,
    sanitize_domain,
)
from app.email_utils import check_domain_for_mailbox, MailboxDomainCheckResult
from app.models import User, PartnerUser, CustomDomain


@dataclass
class CustomDomainCreationDiagnosis:
    user: User
    check: CustomDomainCreationCheck
    is_premium: bool
    pending_domains: List[CustomDomain] = field(default_factory=list)
    existing_domain: Optional[CustomDomain] = None
    parent_domains: List[CustomDomain] = field(default_factory=list)
    max_unverified_domains: int = MAX_UNVERIFIED_CUSTOM_DOMAINS

    @property
    def foreign_parent_domains(self) -> List[CustomDomain]:
        return [d for d in self.parent_domains if d.user_id != self.user.id]

    @property
    def explanation(self) -> str:
        """Admin-facing explanation of why the user can or cannot add the domain."""
        explanation = self._base_explanation()
        foreign = self.foreign_parent_domains
        if foreign:
            owners = ", ".join(f"{d.domain} (owned by {d.user.email})" for d in foreign)
            explanation += (
                f" Note: parent domain {owners} belongs to another user, so this user "
                f"does not inherit its ownership verification and cannot skip the "
                f"pending-verification limit. They must add the TXT verification "
                f"record on {self.check.domain} itself, or the parent domain has to be "
                f"removed from / moved to the right account."
            )
        return explanation

    def _base_explanation(self) -> str:
        check = self.check
        if check.can_create:
            if check.verified_root_cd:
                return (
                    f"All checks pass. Ownership will be inherited from the verified "
                    f"parent domain {check.verified_root_cd.domain}."
                )
            return (
                "All checks pass. The user will still need to verify ownership via DNS."
            )
        if check.not_premium:
            return (
                "The user is not premium (no active subscription, lifetime or trial). "
                "For Proton users, check that their partner subscription is synced."
            )
        if check.unverified_limit_reached:
            return (
                f"The user already has {len(self.pending_domains)} domains pending "
                f"ownership verification (max {self.max_unverified_domains}), and no "
                f"ownership-verified parent domain that would bypass the limit. "
                f"They need to verify or delete one of the pending domains listed below."
            )
        cause = check.forbidden_cause
        if cause == CannotUseDomainReason.DomainAlreadyUsed:
            existing = self.existing_domain
            if existing and existing.user_id == self.user.id:
                return "The user already has this domain in their account."
            owner = existing.user.email if existing else "unknown"
            return f"The domain is already registered as a custom domain by another user ({owner})."
        if cause == CannotUseDomainReason.InvalidDomain:
            return "The domain name is not syntactically valid."
        if cause == CannotUseDomainReason.BuiltinDomain:
            return "The domain is a SimpleLogin domain (or a subdomain of one)."
        if cause == CannotUseDomainReason.DomainPartOfUserEmail:
            return "The user's account email uses this domain."
        if cause == CannotUseDomainReason.DomainUserInMailbox:
            return "A verified mailbox (of any user) already uses this domain."
        return check.error or "Unknown reason"


def resolve_user(query: str) -> Optional[User]:
    """Resolve a user from an email, a numeric/`uid:` id or a partner external user id."""
    query = query.strip()
    if not query:
        return None

    if query.startswith("uid:"):
        query = query[4:]
    if query.isdigit():
        user = User.get(int(query))
        if user:
            return user

    if "@" in query:
        user = User.get_by(email=query.lower())
        if user:
            return user

    partner_user = PartnerUser.get_by(external_user_id=query)
    if partner_user:
        return partner_user.user

    return None


def _parent_domain_names(domain: str) -> List[str]:
    labels = domain.split(".")
    return [".".join(labels[i:]) for i in range(1, len(labels) - 1)]


def diagnose_custom_domain_creation(
    user: User, domain: str
) -> CustomDomainCreationDiagnosis:
    check = check_custom_domain_creation(user, domain)
    pending_domains = (
        CustomDomain.filter_by(user_id=user.id, ownership_verified=False)
        .order_by(CustomDomain.id)
        .all()
    )
    parent_names = _parent_domain_names(check.domain)
    parent_domains = (
        CustomDomain.filter(CustomDomain.domain.in_(parent_names))
        .order_by(CustomDomain.id)
        .all()
        if parent_names
        else []
    )
    return CustomDomainCreationDiagnosis(
        user=user,
        check=check,
        is_premium=user.is_premium(),
        pending_domains=pending_domains,
        existing_domain=CustomDomain.get_by(domain=check.domain),
        parent_domains=parent_domains,
    )


class DomainCheckAdmin(BaseAdminView):
    @expose("/", methods=["GET"])
    def index(self):
        domain = request.args.get("domain", "").strip()
        user_query = request.args.get("user", "").strip()
        result: MailboxDomainCheckResult | None = None
        diagnosis: CustomDomainCreationDiagnosis | None = None
        user_not_found = False

        if domain:
            result = check_domain_for_mailbox(domain)
            if user_query:
                user = resolve_user(user_query)
                if user is None:
                    user_not_found = True
                else:
                    diagnosis = diagnose_custom_domain_creation(
                        user, sanitize_domain(domain)
                    )

        return self.render(
            "admin/domain_check.html",
            domain=domain,
            user_query=user_query,
            result=result,
            diagnosis=diagnosis,
            user_not_found=user_not_found,
        )
