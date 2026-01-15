from __future__ import annotations

from typing import Optional

from flask import redirect, url_for, request, flash
from flask_admin import BaseView, expose
from flask_login import current_user

from app import config
from app.custom_domain_validation import (
    CustomDomainValidation,
    DomainValidationResult,
    ExpectedValidationRecords,
)
from app.db import Session
from app.dns_utils import get_network_dns_client
from app.models import User, CustomDomain, AdminAuditLog, AuditLogActionEnum


class CustomDomainWithValidationData:
    def __init__(self, domain: CustomDomain):
        self.domain: CustomDomain = domain
        self.ownership_expected: Optional[ExpectedValidationRecords] = None
        self.ownership_validation: Optional[DomainValidationResult] = None
        self.mx_expected: Optional[dict[int, ExpectedValidationRecords]] = None
        self.mx_validation: Optional[DomainValidationResult] = None
        self.spf_expected: Optional[ExpectedValidationRecords] = None
        self.spf_validation: Optional[DomainValidationResult] = None
        self.dkim_expected: {str: ExpectedValidationRecords} = {}
        self.dkim_validation: {str: str} = {}


class CustomDomainSearchResult:
    def __init__(self):
        self.no_match: bool = False
        self.user: Optional[User] = None
        self.domains: list[CustomDomainWithValidationData] = []

    @staticmethod
    def from_user(user: Optional[User]) -> CustomDomainSearchResult:
        out = CustomDomainSearchResult()
        if user is None:
            out.no_match = True
            return out
        out.user = user
        dns_client = get_network_dns_client()
        validator = CustomDomainValidation(
            dkim_domain=config.EMAIL_DOMAIN,
            partner_domains=config.PARTNER_DNS_CUSTOM_DOMAINS,
            partner_domains_validation_prefixes=config.PARTNER_CUSTOM_DOMAIN_VALIDATION_PREFIXES,
            dns_client=dns_client,
        )
        for custom_domain in user.custom_domains:
            validation_data = CustomDomainWithValidationData(custom_domain)
            if not custom_domain.ownership_verified:
                validation_data.ownership_expected = (
                    validator.get_ownership_verification_record(custom_domain)
                )
                validation_data.ownership_validation = (
                    validator.validate_domain_ownership(custom_domain)
                )
            if not custom_domain.verified:
                validation_data.mx_expected = validator.get_expected_mx_records(
                    custom_domain
                )
                validation_data.mx_validation = validator.validate_mx_records(
                    custom_domain
                )
            if not custom_domain.spf_verified:
                validation_data.spf_expected = validator.get_expected_spf_record(
                    custom_domain
                )
                validation_data.spf_validation = validator.validate_spf_records(
                    custom_domain
                )
            if not custom_domain.dkim_verified:
                validation_data.dkim_expected = validator.get_dkim_records(
                    custom_domain
                )
                validation_data.dkim_validation = validator.validate_dkim_records(
                    custom_domain
                )
            out.domains.append(validation_data)

        return out


class CustomDomainSearchAdmin(BaseView):
    def is_accessible(self):
        return current_user.is_authenticated and current_user.is_admin

    def inaccessible_callback(self, name, **kwargs):
        # redirect to login page if user doesn't have access
        flash("You don't have access to the admin page", "error")
        return redirect(url_for("dashboard.index", next=request.url))

    @expose("/", methods=["GET", "POST"])
    def index(self):
        query = request.args.get("user")
        if query is None:
            search = CustomDomainSearchResult()
        else:
            try:
                user_id = int(query)
                user = User.get_by(id=user_id)
            except ValueError:
                user = User.get_by(email=query)
                if user is None:
                    cd = CustomDomain.get_by(domain=query)
                    if cd is not None:
                        user = cd.user
            search = CustomDomainSearchResult.from_user(user)

        return self.render(
            "admin/custom_domain_search.html",
            data=search,
            query=query,
        )

    @expose("/delete_domain", methods=["POST"])
    def delete_custom_domain(self):
        domain_id = request.form.get("domain_id")
        if not domain_id:
            flash("Missing domain_id", "error")
            return redirect(url_for("admin.custom_domain_search.index"))
        try:
            domain_id = int(domain_id)
        except ValueError:
            flash("Missing domain_id", "error")
            return redirect(url_for("admin.custom_domain_search.index"))
        domain: Optional[CustomDomain] = CustomDomain.get(domain_id)
        if domain is None:
            flash("Domain not found", "error")
            return redirect(url_for("admin.custom_domain_search.index"))

        domain_user_email = domain.user.email
        domain_domain = domain.domain
        from app.custom_domain_utils import delete_custom_domain

        delete_custom_domain(domain)

        AdminAuditLog.create(
            admin_user_id=current_user.id,
            model=CustomDomain.__class__.__name__,
            model_id=domain_id,
            action=AuditLogActionEnum.delete_custom_domain.value,
            data={"domain": domain_domain},
        )
        Session.commit()

        flash("Scheduled deletion of custom domain", "success")
        return redirect(
            url_for("admin.custom_domain_search.index", user=domain_user_email)
        )
