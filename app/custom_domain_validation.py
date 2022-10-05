from app.db import Session
from app.dns_utils import get_cname_record
from app.models import CustomDomain


class CustomDomainValidation:
    def __init__(self, dkim_domain: str):
        self.dkim_domain = dkim_domain

    def get_dkim_records(self, custom_domain: CustomDomain) -> {str: str}:
        """
        Get a list of dkim records to set up. It will be

        """
        return {
            (f"{key}._domainkey", f"{key}._domainkey.{self.dkim_domain}")
            for key in ("dkim", "dkim02", "dkim03")
        }

    def validate_dkim_records(self, custom_domain: CustomDomain) -> {str: str}:
        """
        Check if dkim records are properly set for this custom domain.
        Returns empty list if all records are ok. Otherwise return the records that aren't properly configured
        """
        invalid_records = {}
        for prefix, expected_record in self.get_dkim_records(custom_domain):
            custom_record = f"{prefix}.{custom_domain.domain}"
            dkim_record = get_cname_record(custom_record)
            if dkim_record != expected_record:
                invalid_records[custom_record] = dkim_record or "empty"
        custom_domain.verified = len(invalid_records) == 0
        Session.commit()
        return invalid_records
