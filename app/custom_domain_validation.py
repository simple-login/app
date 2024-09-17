from app.config import EMAIL_SERVERS_WITH_PRIORITY, EMAIL_DOMAIN
from app.constants import DMARC_RECORD
from app.db import Session
from app.dns_utils import (
    DNSClient,
    is_mx_equivalent,
    get_network_dns_client,
)
from app.models import CustomDomain
from dataclasses import dataclass


@dataclass
class DomainValidationResult:
    success: bool
    errors: [str]


class CustomDomainValidation:
    def __init__(
        self, dkim_domain: str, dns_client: DNSClient = get_network_dns_client()
    ):
        self.dkim_domain = dkim_domain
        self._dns_client = dns_client
        self._dkim_records = {
            f"{key}._domainkey": f"{key}._domainkey.{self.dkim_domain}"
            for key in ("dkim", "dkim02", "dkim03")
        }

    def get_dkim_records(self) -> {str: str}:
        """
        Get a list of dkim records to set up. It will be

        """
        return self._dkim_records

    def validate_dkim_records(self, custom_domain: CustomDomain) -> dict[str, str]:
        """
        Check if dkim records are properly set for this custom domain.
        Returns empty list if all records are ok. Other-wise return the records that aren't properly configured
        """
        invalid_records = {}
        for prefix, expected_record in self.get_dkim_records().items():
            custom_record = f"{prefix}.{custom_domain.domain}"
            dkim_record = self._dns_client.get_cname_record(custom_record)
            if dkim_record != expected_record:
                invalid_records[custom_record] = dkim_record or "empty"
        # HACK: If dkim is enabled, don't disable it to give users time to update their CNAMES
        if custom_domain.dkim_verified:
            return invalid_records
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

        if custom_domain.get_ownership_dns_txt_value() in txt_records:
            custom_domain.ownership_verified = True
            Session.commit()
            return DomainValidationResult(success=True, errors=[])
        else:
            return DomainValidationResult(success=False, errors=txt_records)

    def validate_mx_records(
        self, custom_domain: CustomDomain
    ) -> DomainValidationResult:
        mx_domains = self._dns_client.get_mx_domains(custom_domain.domain)

        if not is_mx_equivalent(mx_domains, EMAIL_SERVERS_WITH_PRIORITY):
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
        if EMAIL_DOMAIN in spf_domains:
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
