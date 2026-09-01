from __future__ import annotations

from typing import Optional, List

import arrow
from flask import redirect, url_for, request, flash
from flask_admin import expose
from flask_login import current_user

from app import config
from app.admin.base import BaseAdminView
from app.custom_domain_validation import (
    CustomDomainValidation,
    DomainValidationResult,
    ExpectedValidationRecords,
)
from app.db import Session
from app.dns_utils import get_network_dns_client
from app.models import (
    User,
    CustomDomain,
    AdminAuditLog,
    AuditLogActionEnum,
    Alias,
    DomainDeletedAlias,
)
from app.regex_utils import is_safe_regex_pattern


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
        """Search for custom domains by exact match or POSIX regex.

        - Numeric query: search by domain ID
        - Query with '@': search by user email
        - Query with 'uid:<int>': search by user ID
        - Otherwise: exact domain match, then regex on domain names
        """
        output = CustomDomainSearchResult()
        output.query = query

        # Search by domain ID if query is a plain integer
        try:
            domain_id = int(query)
            domain = CustomDomain.get(domain_id)
            if domain:
                output.domains = [CustomDomainSearchHelpers.get_validation_data(domain)]
                output.found_by_regex = False
                output.no_match = False
            return output
        except ValueError:
            pass

        # Search by user email if query contains '@'
        if "@" in query:
            user = User.get_by(email=query)
            if user:
                output.domains = [
                    CustomDomainSearchHelpers.get_validation_data(d)
                    for d in user.custom_domains
                ]
                output.found_by_regex = False
                output.no_match = len(output.domains) == 0
            return output

        # Search by user ID if query has the form 'uid:<int>'
        if query.startswith("uid:"):
            try:
                user_id = int(query[4:])
                user = User.get(user_id)
                if user:
                    output.domains = [
                        CustomDomainSearchHelpers.get_validation_data(d)
                        for d in user.custom_domains
                    ]
                    output.found_by_regex = False
                    output.no_match = len(output.domains) == 0
            except ValueError:
                pass
            return output

        # Try exact domain match first
        domain = CustomDomain.get_by(domain=query)
        if domain:
            output.domains = [CustomDomainSearchHelpers.get_validation_data(domain)]
            output.found_by_regex = False
            output.no_match = False
            return output

        # Try regex search on domain names
        # Validate regex pattern to prevent ReDoS attacks
        if not is_safe_regex_pattern(query, " in custom domain search"):
            return output

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
    def alias_list(domain: CustomDomain, page: int = 1, limit: int = 25) -> List[Alias]:
        """Get paginated list of aliases for this domain.

        Pagination is handled at the database level to avoid loading all aliases into memory.
        """
        offset = (page - 1) * limit
        return (
            Alias.filter(Alias.custom_domain_id == domain.id)
            .order_by(Alias.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    @staticmethod
    def deleted_alias_count(domain: CustomDomain) -> int:
        """Get count of deleted aliases for this domain."""
        return DomainDeletedAlias.filter(
            DomainDeletedAlias.domain_id == domain.id
        ).count()

    @staticmethod
    def deleted_alias_list(
        domain: CustomDomain, page: int = 1, limit: int = 25
    ) -> List[DomainDeletedAlias]:
        """Get paginated list of deleted aliases for this domain.

        Pagination is handled at the database level to avoid loading all deleted aliases into memory.
        """
        offset = (page - 1) * limit
        return (
            DomainDeletedAlias.filter(DomainDeletedAlias.domain_id == domain.id)
            .order_by(DomainDeletedAlias.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )


class CustomDomainSearchAdmin(BaseAdminView):
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
        from app.log import LOG

        domain_id = request.form.get("domain_id")
        confirm_domain = request.form.get("confirm_domain", "").strip()

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

        # Verify domain confirmation matches
        if confirm_domain != domain_name:
            flash(
                "Domain confirmation does not match. Domain was not deleted.",
                "error",
            )
            return redirect(
                url_for("admin.custom_domain_search.index", query=domain_name)
            )

        # Validate deletion prerequisites before proceeding
        alias_count = CustomDomainSearchHelpers.alias_count(domain)
        if alias_count > 100:
            LOG.warning(
                f"Admin {current_user.email} attempting to delete domain {domain_name} with {alias_count} aliases"
            )
            # Log warning but proceed - deletion should handle batches

        AdminAuditLog.create(
            admin_user_id=current_user.id,
            model="CustomDomain",
            model_id=domain_id,
            action=AuditLogActionEnum.delete_custom_domain.value,
            data={"domain": domain_name, "deleted_by": current_user.email},
        )
        Session.commit()

        LOG.warning(
            f"Admin {current_user.email} scheduled deletion of custom domain {domain_name} (id={domain_id})"
        )
        flash(f"Scheduled deletion of custom domain {domain_name}", "success")
        return redirect(url_for("admin.custom_domain_search.index", query=domain_name))
