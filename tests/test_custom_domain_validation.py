from typing import Optional

from app import config
from app.constants import DMARC_RECORD
from app.custom_domain_validation import CustomDomainValidation
from app.db import Session
from app.models import CustomDomain, User
from app.dns_utils import InMemoryDNSClient
from app.utils import random_string
from tests.utils import create_new_user, random_domain

user: Optional[User] = None


def setup_module():
    global user
    config.SKIP_MX_LOOKUP_ON_CHECK = True
    user = create_new_user()
    user.trial_end = None
    user.lifetime = True
    Session.commit()


def create_custom_domain(domain: str) -> CustomDomain:
    return CustomDomain.create(user_id=user.id, domain=domain, commit=True)


def test_custom_domain_validation_get_dkim_records():
    domain = random_domain()
    validator = CustomDomainValidation(domain)
    records = validator.get_dkim_records()

    assert len(records) == 3
    assert records["dkim02._domainkey"] == f"dkim02._domainkey.{domain}"
    assert records["dkim03._domainkey"] == f"dkim03._domainkey.{domain}"
    assert records["dkim._domainkey"] == f"dkim._domainkey.{domain}"


# validate_dkim_records
def test_custom_domain_validation_validate_dkim_records_empty_records_failure():
    dns_client = InMemoryDNSClient()
    validator = CustomDomainValidation(random_domain(), dns_client)

    domain = create_custom_domain(random_domain())
    res = validator.validate_dkim_records(domain)

    assert len(res) == 3
    for record_value in res.values():
        assert record_value == "empty"

    db_domain = CustomDomain.get_by(id=domain.id)
    assert db_domain.dkim_verified is False


def test_custom_domain_validation_validate_dkim_records_wrong_records_failure():
    dkim_domain = random_domain()
    dns_client = InMemoryDNSClient()
    validator = CustomDomainValidation(dkim_domain, dns_client)

    user_domain = random_domain()

    # One domain right, two domains wrong
    dns_client.set_cname_record(
        f"dkim._domainkey.{user_domain}", f"dkim._domainkey.{dkim_domain}"
    )
    dns_client.set_cname_record(f"dkim02._domainkey.{user_domain}", "wrong")
    dns_client.set_cname_record(f"dkim03._domainkey.{user_domain}", "wrong")

    domain = create_custom_domain(user_domain)
    res = validator.validate_dkim_records(domain)

    assert len(res) == 2
    for record_value in res.values():
        assert record_value == "wrong"

    db_domain = CustomDomain.get_by(id=domain.id)
    assert db_domain.dkim_verified is False


def test_custom_domain_validation_validate_dkim_records_success():
    dkim_domain = random_domain()
    dns_client = InMemoryDNSClient()
    validator = CustomDomainValidation(dkim_domain, dns_client)

    user_domain = random_domain()

    # One domain right, two domains wrong
    dns_client.set_cname_record(
        f"dkim._domainkey.{user_domain}", f"dkim._domainkey.{dkim_domain}"
    )
    dns_client.set_cname_record(
        f"dkim02._domainkey.{user_domain}", f"dkim02._domainkey.{dkim_domain}"
    )
    dns_client.set_cname_record(
        f"dkim03._domainkey.{user_domain}", f"dkim03._domainkey.{dkim_domain}"
    )

    domain = create_custom_domain(user_domain)
    res = validator.validate_dkim_records(domain)
    assert len(res) == 0

    db_domain = CustomDomain.get_by(id=domain.id)
    assert db_domain.dkim_verified is True


# validate_ownership
def test_custom_domain_validation_validate_ownership_empty_records_failure():
    dns_client = InMemoryDNSClient()
    validator = CustomDomainValidation(random_domain(), dns_client)

    domain = create_custom_domain(random_domain())
    res = validator.validate_domain_ownership(domain)

    assert res.success is False
    assert len(res.errors) == 0

    db_domain = CustomDomain.get_by(id=domain.id)
    assert db_domain.ownership_verified is False


def test_custom_domain_validation_validate_ownership_wrong_records_failure():
    dns_client = InMemoryDNSClient()
    validator = CustomDomainValidation(random_domain(), dns_client)

    domain = create_custom_domain(random_domain())

    wrong_records = [random_string()]
    dns_client.set_txt_record(domain.domain, wrong_records)
    res = validator.validate_domain_ownership(domain)

    assert res.success is False
    assert res.errors == wrong_records

    db_domain = CustomDomain.get_by(id=domain.id)
    assert db_domain.ownership_verified is False


def test_custom_domain_validation_validate_ownership_success():
    dns_client = InMemoryDNSClient()
    validator = CustomDomainValidation(random_domain(), dns_client)

    domain = create_custom_domain(random_domain())

    dns_client.set_txt_record(domain.domain, [domain.get_ownership_dns_txt_value()])
    res = validator.validate_domain_ownership(domain)

    assert res.success is True
    assert len(res.errors) == 0

    db_domain = CustomDomain.get_by(id=domain.id)
    assert db_domain.ownership_verified is True


# validate_mx_records
def test_custom_domain_validation_validate_mx_records_empty_failure():
    dns_client = InMemoryDNSClient()
    validator = CustomDomainValidation(random_domain(), dns_client)

    domain = create_custom_domain(random_domain())
    res = validator.validate_mx_records(domain)

    assert res.success is False
    assert len(res.errors) == 0

    db_domain = CustomDomain.get_by(id=domain.id)
    assert db_domain.verified is False


def test_custom_domain_validation_validate_mx_records_wrong_records_failure():
    dns_client = InMemoryDNSClient()
    validator = CustomDomainValidation(random_domain(), dns_client)

    domain = create_custom_domain(random_domain())

    wrong_record_1 = random_string()
    wrong_record_2 = random_string()
    wrong_records = [(10, wrong_record_1), (20, wrong_record_2)]
    dns_client.set_mx_records(domain.domain, wrong_records)
    res = validator.validate_mx_records(domain)

    assert res.success is False
    assert res.errors == [f"10 {wrong_record_1}", f"20 {wrong_record_2}"]

    db_domain = CustomDomain.get_by(id=domain.id)
    assert db_domain.verified is False


def test_custom_domain_validation_validate_mx_records_success():
    dns_client = InMemoryDNSClient()
    validator = CustomDomainValidation(random_domain(), dns_client)

    domain = create_custom_domain(random_domain())

    dns_client.set_mx_records(domain.domain, config.EMAIL_SERVERS_WITH_PRIORITY)
    res = validator.validate_mx_records(domain)

    assert res.success is True
    assert len(res.errors) == 0

    db_domain = CustomDomain.get_by(id=domain.id)
    assert db_domain.verified is True


# validate_spf_records
def test_custom_domain_validation_validate_spf_records_empty_failure():
    dns_client = InMemoryDNSClient()
    validator = CustomDomainValidation(random_domain(), dns_client)

    domain = create_custom_domain(random_domain())
    res = validator.validate_spf_records(domain)

    assert res.success is False
    assert len(res.errors) == 0

    db_domain = CustomDomain.get_by(id=domain.id)
    assert db_domain.spf_verified is False


def test_custom_domain_validation_validate_spf_records_wrong_records_failure():
    dns_client = InMemoryDNSClient()
    validator = CustomDomainValidation(random_domain(), dns_client)

    domain = create_custom_domain(random_domain())

    wrong_records = [random_string()]
    dns_client.set_txt_record(domain.domain, wrong_records)
    res = validator.validate_spf_records(domain)

    assert res.success is False
    assert res.errors == wrong_records

    db_domain = CustomDomain.get_by(id=domain.id)
    assert db_domain.spf_verified is False


def test_custom_domain_validation_validate_spf_records_success():
    dns_client = InMemoryDNSClient()
    validator = CustomDomainValidation(random_domain(), dns_client)

    domain = create_custom_domain(random_domain())

    dns_client.set_txt_record(domain.domain, [f"v=spf1 include:{config.EMAIL_DOMAIN}"])
    res = validator.validate_spf_records(domain)

    assert res.success is True
    assert len(res.errors) == 0

    db_domain = CustomDomain.get_by(id=domain.id)
    assert db_domain.spf_verified is True


# validate_dmarc_records
def test_custom_domain_validation_validate_dmarc_records_empty_failure():
    dns_client = InMemoryDNSClient()
    validator = CustomDomainValidation(random_domain(), dns_client)

    domain = create_custom_domain(random_domain())
    res = validator.validate_dmarc_records(domain)

    assert res.success is False
    assert len(res.errors) == 0

    db_domain = CustomDomain.get_by(id=domain.id)
    assert db_domain.dmarc_verified is False


def test_custom_domain_validation_validate_dmarc_records_wrong_records_failure():
    dns_client = InMemoryDNSClient()
    validator = CustomDomainValidation(random_domain(), dns_client)

    domain = create_custom_domain(random_domain())

    wrong_records = [random_string()]
    dns_client.set_txt_record(f"_dmarc.{domain.domain}", wrong_records)
    res = validator.validate_dmarc_records(domain)

    assert res.success is False
    assert res.errors == wrong_records

    db_domain = CustomDomain.get_by(id=domain.id)
    assert db_domain.dmarc_verified is False


def test_custom_domain_validation_validate_dmarc_records_success():
    dns_client = InMemoryDNSClient()
    validator = CustomDomainValidation(random_domain(), dns_client)

    domain = create_custom_domain(random_domain())

    dns_client.set_txt_record(f"_dmarc.{domain.domain}", [DMARC_RECORD])
    res = validator.validate_dmarc_records(domain)

    assert res.success is True
    assert len(res.errors) == 0

    db_domain = CustomDomain.get_by(id=domain.id)
    assert db_domain.dmarc_verified is True
