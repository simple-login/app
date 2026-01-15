from __future__ import annotations

from typing import Optional, List

import arrow
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
from app.models import User, CustomDomain, AdminAuditLog, AuditLogActionEnum, Alias


class CustomDomainWithValidationData:
    def __init__(self, domain: CustomDomain):
        self.domain: CustomDomain = domain
        self.ownership_expected: Optional[ExpectedValidationRecords] = None
        self.ownership_validation: Optional[DomainValidationResult] = None
        self.mx_expected: Optional[dict[int, ExpectedValidationRecords]] = None
        self.mx_validation: Optional[DomainValidationResult] = None
        self.spf_expected: Optional[ExpectedValidationRecords] = None
        self.spf_validation: Optional[DomainValidationResult] = None
        self.dkim_expected: dict[str, ExpectedValidationRecords] = {}
        self.dkim_validation: dict[str, str] = {}


class CustomDomainSearchResult:
    def __init__(self):
        self.no_match: bool = True
        self.query: str = ""
        self.domains: List[CustomDomainWithValidationData] = []
        self.found_by_regex: bool = False

    @staticmethod
    def search(query: str) -> CustomDomainSearchResult:
        """Search for custom domains by exact match or POSIX regex."""
        output = CustomDomainSearchResult()
        output.query = query

        # Try exact domain match first
        domain = CustomDomain.get_by(domain=query)
        if domain:
            output.domains = [CustomDomainSearchHelpers.get_validation_data(domain)]
            output.found_by_regex = False
            output.no_match = False
            return output

        # Try searching by user email
        user = User.get_by(email=query)
        if user:
            output.domains = [
                CustomDomainSearchHelpers.get_validation_data(d)
                for d in user.custom_domains
            ]
            output.found_by_regex = False
            output.no_match = len(output.domains) == 0
            return output

        # Try searching by user ID
        try:
            user_id = int(query)
            user = User.get(user_id)
            if user:
                output.domains = [
                    CustomDomainSearchHelpers.get_validation_data(d)
                    for d in user.custom_domains
                ]
                output.found_by_regex = False
                output.no_match = len(output.domains) == 0
                return output
        except ValueError:
            pass

        # Try regex search on domain names
        domains = (
            CustomDomain.filter(CustomDomain.domain.op("~")(query))
            .order_by(CustomDomain.id.desc())
            .limit(10)
            .all()
        )
        if domains:
            output.domains = [
                CustomDomainSearchHelpers.get_validation_data(d) for d in domains
            ]
            output.found_by_regex = True
            output.no_match = False

        return output


class CustomDomainSearchHelpers:
    _validator: Optional[CustomDomainValidation] = None

    @classmethod
    def get_validator(cls) -> CustomDomainValidation:
        """Get or create a domain validator instance."""
        if cls._validator is None:
            dns_client = get_network_dns_client()
            cls._validator = CustomDomainValidation(
                dkim_domain=config.EMAIL_DOMAIN,
                partner_domains=config.PARTNER_DNS_CUSTOM_DOMAINS,
                partner_domains_validation_prefixes=config.PARTNER_CUSTOM_DOMAIN_VALIDATION_PREFIXES,
                dns_client=dns_client,
            )
        return cls._validator

    @classmethod
    def get_validation_data(
        cls, domain: CustomDomain
    ) -> CustomDomainWithValidationData:
        """Get validation data for a custom domain.

        Uses a nested transaction (savepoint) to avoid persisting any changes
        made by the validation methods, since this is a read-only admin view.
        """
        validator = cls.get_validator()
        validation_data = CustomDomainWithValidationData(domain)

        # Use a nested transaction so we can rollback any changes made by validators
        # The validation methods modify domain state and commit, which we don't want
        # to persist in the admin view
        try:
            Session.begin_nested()

            if not domain.ownership_verified:
                validation_data.ownership_expected = (
                    validator.get_ownership_verification_record(domain)
                )
                validation_data.ownership_validation = (
                    validator.validate_domain_ownership(domain)
                )

            if not domain.verified:
                validation_data.mx_expected = validator.get_expected_mx_records(domain)
                validation_data.mx_validation = validator.validate_mx_records(domain)

            if not domain.spf_verified:
                validation_data.spf_expected = validator.get_expected_spf_domain(domain)
                validation_data.spf_validation = validator.validate_spf_records(domain)

            if not domain.dkim_verified:
                validation_data.dkim_expected = validator.get_dkim_records(domain)
                validation_data.dkim_validation = validator.validate_dkim_records(
                    domain
                )

        finally:
            # Always rollback to discard any changes made by the validators
            Session.rollback()
            # Refresh the domain object to get its original state
            Session.refresh(domain)

        return validation_data

    @staticmethod
    def alias_count(domain: CustomDomain) -> int:
        """Get count of aliases for this domain."""
        return Alias.filter(
            Alias.custom_domain_id == domain.id,
        ).count()

    @staticmethod
    def alias_list(domain: CustomDomain, limit: int = 10) -> List[Alias]:
        """Get list of aliases for this domain."""
        return (
            Alias.filter(Alias.custom_domain_id == domain.id)
            .order_by(Alias.created_at.desc())
            .limit(limit)
            .all()
        )


class CustomDomainSearchAdmin(BaseView):
    def is_accessible(self):
        return current_user.is_authenticated and current_user.is_admin

    def inaccessible_callback(self, name, **kwargs):
        flash("You don't have access to the admin page", "error")
        return redirect(url_for("dashboard.index", next=request.url))

    @expose("/", methods=["GET"])
    def index(self):
        search = CustomDomainSearchResult()
        query = request.args.get("query")

        if query:
            query = query.strip()
            search = CustomDomainSearchResult.search(query)

        return self.render(
            "admin/custom_domain_search.html",
            data=search,
            query=query,
            helper=CustomDomainSearchHelpers,
            now=arrow.now(),
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
            flash("Invalid domain_id", "error")
            return redirect(url_for("admin.custom_domain_search.index"))

        domain: Optional[CustomDomain] = CustomDomain.get(domain_id)
        if domain is None:
            flash("Domain not found", "error")
            return redirect(url_for("admin.custom_domain_search.index"))

        domain_name = domain.domain
        from app.custom_domain_utils import delete_custom_domain

        delete_custom_domain(domain)

        AdminAuditLog.create(
            admin_user_id=current_user.id,
            model="CustomDomain",
            model_id=domain_id,
            action=AuditLogActionEnum.delete_custom_domain.value,
            data={"domain": domain_name},
        )
        Session.commit()

        flash(f"Scheduled deletion of custom domain {domain_name}", "success")
        return redirect(url_for("admin.custom_domain_search.index", query=domain_name))
