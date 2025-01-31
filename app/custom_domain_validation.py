from dataclasses import dataclass
from typing import List, Optional

from app import config
from app.constants import DMARC_RECORD
from app.db import Session
from app.dns_utils import (
    DNSClient,
    get_network_dns_client,
)
from app.models import CustomDomain
from app.user_audit_log_utils import emit_user_audit_log, UserAuditLogAction
from app.utils import random_string


@dataclass
class DomainValidationResult:
    success: bool
    errors: [str]


@dataclass
class ExpectedValidationRecords:
    recommended: str
    valid: list[str]


def is_mx_equivalent(
    mx_domains: dict[int, list[str]],
    expected_mx_domains: dict[int, ExpectedValidationRecords],
) -> bool:
    """
    Compare mx_domains with ref_mx_domains to see if they are equivalent.
    mx_domains and ref_mx_domains are list of (priority, domain)

    The priority order is taken into account but not the priority number.
    For example, [(1, domain1), (2, domain2)] is equivalent to [(10, domain1), (20, domain2)]
    """

    expected_prios = []
    for prio in expected_mx_domains:
        expected_prios.append(prio)

    if len(expected_prios) != len(mx_domains):
        return False

    for prio_position, prio_value in enumerate(sorted(mx_domains.keys())):
        for domain in mx_domains[prio_value]:
            if domain not in expected_mx_domains[expected_prios[prio_position]].valid:
                return False

    return True


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
        self._partner_domains = partner_domains or config.PARTNER_DNS_CUSTOM_DOMAINS
        self._partner_domain_validation_prefixes = (
            partner_domains_validation_prefixes
            or config.PARTNER_CUSTOM_DOMAIN_VALIDATION_PREFIXES
        )

    def get_ownership_verification_record(
        self, domain: CustomDomain
    ) -> ExpectedValidationRecords:
        prefixes = ["sl"]
        if (
            domain.partner_id is not None
            and domain.partner_id in self._partner_domain_validation_prefixes
        ):
            prefixes.insert(
                0, self._partner_domain_validation_prefixes[domain.partner_id]
            )

        if not domain.ownership_txt_token:
            domain.ownership_txt_token = random_string(30)
            Session.commit()

        valid = [
            f"{prefix}-verification={domain.ownership_txt_token}" for prefix in prefixes
        ]
        return ExpectedValidationRecords(recommended=valid[0], valid=valid)

    def get_expected_mx_records(
        self, domain: CustomDomain
    ) -> dict[int, ExpectedValidationRecords]:
        records = {}
        if domain.partner_id is not None and domain.partner_id in self._partner_domains:
            domain = self._partner_domains[domain.partner_id]
            records[10] = [f"mx1.{domain}."]
            records[20] = [f"mx2.{domain}."]
        # Default ones
        for priority, domain in config.EMAIL_SERVERS_WITH_PRIORITY:
            if priority not in records:
                records[priority] = []
            records[priority].append(domain)

        return {
            priority: ExpectedValidationRecords(
                recommended=records[priority][0], valid=records[priority]
            )
            for priority in records
        }

    def get_expected_spf_domain(
        self, domain: CustomDomain
    ) -> ExpectedValidationRecords:
        records = []
        if domain.partner_id is not None and domain.partner_id in self._partner_domains:
            records.append(self._partner_domains[domain.partner_id])
        else:
            records.append(config.EMAIL_DOMAIN)
        return ExpectedValidationRecords(recommended=records[0], valid=records)

    def get_expected_spf_record(self, domain: CustomDomain) -> str:
        spf_domain = self.get_expected_spf_domain(domain)
        return f"v=spf1 include:{spf_domain.recommended} ~all"

    def get_dkim_records(
        self, domain: CustomDomain
    ) -> {str: ExpectedValidationRecords}:
        """
        Get a list of dkim records to set up. Depending on the custom_domain, whether if it's from a partner or not,
        it will return the default ones or the partner ones.
        """

        # By default use the default domain
        dkim_domains = [self.dkim_domain]
        if domain.partner_id is not None:
            # Domain is from a partner. Retrieve the partner config and use that domain as preferred if it exists
            partner_domain = self._partner_domains.get(domain.partner_id, None)
            if partner_domain is not None:
                dkim_domains.insert(0, partner_domain)

        output = {}
        for key in ("dkim", "dkim02", "dkim03"):
            records = [
                f"{key}._domainkey.{dkim_domain}" for dkim_domain in dkim_domains
            ]
            output[f"{key}._domainkey"] = ExpectedValidationRecords(
                recommended=records[0], valid=records
            )

        return output

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
            if dkim_record in expected_record.valid:
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
        if custom_domain.dkim_verified:
            emit_user_audit_log(
                user=custom_domain.user,
                action=UserAuditLogAction.VerifyCustomDomain,
                message=f"Verified DKIM records for custom domain {custom_domain.id} ({custom_domain.domain})",
            )
        Session.commit()
        return invalid_records

    def validate_domain_ownership(
        self, custom_domain: CustomDomain
    ) -> DomainValidationResult:
        """
        Check if the custom_domain has added the ownership verification records
        """
        txt_records = self._dns_client.get_txt_record(custom_domain.domain)
        expected_verification_records = self.get_ownership_verification_record(
            custom_domain
        )
        found = False
        for verification_record in expected_verification_records.valid:
            if verification_record in txt_records:
                found = True
                break
        if found:
            custom_domain.ownership_verified = True
            emit_user_audit_log(
                user=custom_domain.user,
                action=UserAuditLogAction.VerifyCustomDomain,
                message=f"Verified ownership for custom domain {custom_domain.id} ({custom_domain.domain})",
            )
            Session.commit()
            return DomainValidationResult(success=True, errors=[])
        else:
            return DomainValidationResult(success=False, errors=txt_records)

    def validate_mx_records(
        self, custom_domain: CustomDomain
    ) -> DomainValidationResult:
        mx_domains = self._dns_client.get_mx_domains(custom_domain.domain)
        expected_mx_records = self.get_expected_mx_records(custom_domain)

        if not is_mx_equivalent(mx_domains, expected_mx_records):
            errors = []
            for prio in mx_domains:
                errors.extend([f"{prio} {domain}" for domain in mx_domains[prio]])
            return DomainValidationResult(success=False, errors=errors)
        else:
            custom_domain.verified = True
            emit_user_audit_log(
                user=custom_domain.user,
                action=UserAuditLogAction.VerifyCustomDomain,
                message=f"Verified MX records for custom domain {custom_domain.id} ({custom_domain.domain})",
            )
            Session.commit()
            return DomainValidationResult(success=True, errors=[])

    def validate_spf_records(
        self, custom_domain: CustomDomain
    ) -> DomainValidationResult:
        spf_domains = self._dns_client.get_spf_domain(custom_domain.domain)
        expected_spf_domain = self.get_expected_spf_domain(custom_domain)
        if len(set(expected_spf_domain.valid).intersection(set(spf_domains))) > 0:
            custom_domain.spf_verified = True
            emit_user_audit_log(
                user=custom_domain.user,
                action=UserAuditLogAction.VerifyCustomDomain,
                message=f"Verified SPF records for custom domain {custom_domain.id} ({custom_domain.domain})",
            )
            Session.commit()
            return DomainValidationResult(success=True, errors=[])
        else:
            custom_domain.spf_verified = False
            Session.commit()
            txt_records = self._dns_client.get_txt_record(custom_domain.domain)
            cleaned_records = self.__clean_spf_records(txt_records, custom_domain)
            return DomainValidationResult(
                success=False,
                errors=cleaned_records,
            )

    def validate_dmarc_records(
        self, custom_domain: CustomDomain
    ) -> DomainValidationResult:
        txt_records = self._dns_client.get_txt_record("_dmarc." + custom_domain.domain)
        if DMARC_RECORD in txt_records:
            custom_domain.dmarc_verified = True
            emit_user_audit_log(
                user=custom_domain.user,
                action=UserAuditLogAction.VerifyCustomDomain,
                message=f"Verified DMARC records for custom domain {custom_domain.id} ({custom_domain.domain})",
            )
            Session.commit()
            return DomainValidationResult(success=True, errors=[])
        else:
            custom_domain.dmarc_verified = False
            Session.commit()
            return DomainValidationResult(success=False, errors=txt_records)

    def __clean_spf_records(
        self, txt_records: List[str], custom_domain: CustomDomain
    ) -> List[str]:
        final_records = []
        verification_records = self.get_ownership_verification_record(custom_domain)
        for record in txt_records:
            if record not in verification_records.valid:
                final_records.append(record)
        return final_records
