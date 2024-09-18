from dataclasses import dataclass
from typing import Optional

from app import config
from app.constants import DMARC_RECORD
from app.db import Session
from app.dns_utils import (
    DNSClient,
    is_mx_equivalent,
    get_network_dns_client,
)
from app.models import CustomDomain


@dataclass
class DomainValidationResult:
    success: bool
    errors: [str]


class CustomDomainValidation:
    def __init__(
        self,
        dkim_domain: str,
        dns_client: DNSClient = get_network_dns_client(),
        partner_domains: Optional[dict[int, str]] = None,
        partner_domains_validation_prefixes: Optional[dict[int, str]] = None,
    ):
        self.dkim_domain = dkim_domain
        self._dns_client = dns_client
        self._partner_domains = partner_domains or config.PARTNER_DOMAINS
        self._partner_domain_validation_prefixes = (
            partner_domains_validation_prefixes
            or config.PARTNER_DOMAIN_VALIDATION_PREFIXES
        )

    def get_ownership_verification_record(self, domain: CustomDomain) -> str:
        prefix = "sl-verification"
        if (
            domain.partner_id is not None
            and domain.partner_id in self._partner_domain_validation_prefixes
        ):
            prefix = self._partner_domain_validation_prefixes[domain.partner_id]
        return f"{prefix}={domain.ownership_txt_token}"

    def get_dkim_records(self, domain: CustomDomain) -> {str: str}:
        """
        Get a list of dkim records to set up. Depending on the custom_domain, whether if it's from a partner or not,
        it will return the default ones or the partner ones.
        """

        # By default use the default domain
        dkim_domain = self.dkim_domain
        if domain.partner_id is not None:
            # Domain is from a partner. Retrieve the partner config and use that domain if exists
            partner_domain = self._partner_domains.get(domain.partner_id)
            if partner_domain is not None:
                dkim_domain = partner_domain

        return {
            f"{key}._domainkey": f"{key}._domainkey.{dkim_domain}"
            for key in ("dkim", "dkim02", "dkim03")
        }

    def validate_dkim_records(self, custom_domain: CustomDomain) -> dict[str, str]:
        """
        Check if dkim records are properly set for this custom domain.
        Returns empty list if all records are ok. Other-wise return the records that aren't properly configured
        """
        correct_records = {}
        invalid_records = {}
        expected_records = self.get_dkim_records(custom_domain)
        for prefix, expected_record in expected_records.items():
            custom_record = f"{prefix}.{custom_domain.domain}"
            dkim_record = self._dns_client.get_cname_record(custom_record)
            if dkim_record == expected_record:
                correct_records[prefix] = custom_record
            else:
                invalid_records[custom_record] = dkim_record or "empty"

        # HACK
        # As initially we only had one dkim record, we want to allow users that had only the original dkim record and
        # the domain validated to continue seeing it as validated (although showing them the missing records).
        # However, if not even the original dkim record is right, even if the domain was dkim_verified in the past,
        # we will remove the dkim_verified flag.
        # This is done in order to give users with the old dkim config (only one) to update their CNAMEs
        if custom_domain.dkim_verified:
            # Check if at least the original dkim is there
            if correct_records.get("dkim._domainkey") is not None:
                # Original dkim record is there. Return the missing records (if any) and don't clear the flag
                return invalid_records

            # Original DKIM record is not there, which means the DKIM config is not finished. Proceed with the
            # rest of the code path, returning the invalid records and clearing the flag
        custom_domain.dkim_verified = len(invalid_records) == 0
        Session.commit()
        return invalid_records

    def validate_domain_ownership(
        self, custom_domain: CustomDomain
    ) -> DomainValidationResult:
        """
        Check if the custom_domain has added the ownership verification records
        """
        txt_records = self._dns_client.get_txt_record(custom_domain.domain)
        expected_verification_record = self.get_ownership_verification_record(
            custom_domain
        )

        if expected_verification_record in txt_records:
            custom_domain.ownership_verified = True
            Session.commit()
            return DomainValidationResult(success=True, errors=[])
        else:
            return DomainValidationResult(success=False, errors=txt_records)

    def validate_mx_records(
        self, custom_domain: CustomDomain
    ) -> DomainValidationResult:
        mx_domains = self._dns_client.get_mx_domains(custom_domain.domain)

        if not is_mx_equivalent(mx_domains, config.EMAIL_SERVERS_WITH_PRIORITY):
            return DomainValidationResult(
                success=False,
                errors=[f"{priority} {domain}" for (priority, domain) in mx_domains],
            )
        else:
            custom_domain.verified = True
            Session.commit()
            return DomainValidationResult(success=True, errors=[])

    def validate_spf_records(
        self, custom_domain: CustomDomain
    ) -> DomainValidationResult:
        spf_domains = self._dns_client.get_spf_domain(custom_domain.domain)
        if config.EMAIL_DOMAIN in spf_domains:
            custom_domain.spf_verified = True
            Session.commit()
            return DomainValidationResult(success=True, errors=[])
        else:
            custom_domain.spf_verified = False
            Session.commit()
            return DomainValidationResult(
                success=False,
                errors=self._dns_client.get_txt_record(custom_domain.domain),
            )

    def validate_dmarc_records(
        self, custom_domain: CustomDomain
    ) -> DomainValidationResult:
        txt_records = self._dns_client.get_txt_record("_dmarc." + custom_domain.domain)
        if DMARC_RECORD in txt_records:
            custom_domain.dmarc_verified = True
            Session.commit()
            return DomainValidationResult(success=True, errors=[])
        else:
            custom_domain.dmarc_verified = False
            Session.commit()
            return DomainValidationResult(success=False, errors=txt_records)
