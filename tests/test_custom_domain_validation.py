from typing import Optional

from app import config
from app.constants import DMARC_RECORD
from app.custom_domain_validation import CustomDomainValidation
from app.db import Session
from app.dns_utils import InMemoryDNSClient
from app.models import CustomDomain, User
from app.proton.utils import get_proton_partner
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
    custom_domain = create_custom_domain(domain)
    validator = CustomDomainValidation(domain)
    records = validator.get_dkim_records(custom_domain)

    assert len(records) == 3
    assert records["dkim02._domainkey"].recommended == f"dkim02._domainkey.{domain}"
    assert records["dkim02._domainkey"].valid == [f"dkim02._domainkey.{domain}"]
    assert records["dkim03._domainkey"].recommended == f"dkim03._domainkey.{domain}"
    assert records["dkim03._domainkey"].valid == [f"dkim03._domainkey.{domain}"]
    assert records["dkim._domainkey"].recommended == f"dkim._domainkey.{domain}"
    assert records["dkim._domainkey"].valid == [f"dkim._domainkey.{domain}"]


def test_custom_domain_validation_get_dkim_records_for_partner():
    domain = random_domain()
    custom_domain = create_custom_domain(domain)

    partner_id = get_proton_partner().id
    custom_domain.partner_id = partner_id
    Session.commit()

    dkim_domain = random_domain()
    validator = CustomDomainValidation(
        domain, partner_domains={partner_id: dkim_domain}
    )
    records = validator.get_dkim_records(custom_domain)

    assert len(records) == 3
    assert (
        records["dkim02._domainkey"].recommended == f"dkim02._domainkey.{dkim_domain}"
    )
    assert records["dkim02._domainkey"].valid == [
        f"dkim02._domainkey.{dkim_domain}",
        f"dkim02._domainkey.{domain}",
    ]
    assert (
        records["dkim03._domainkey"].recommended == f"dkim03._domainkey.{dkim_domain}"
    )
    assert records["dkim03._domainkey"].valid == [
        f"dkim03._domainkey.{dkim_domain}",
        f"dkim03._domainkey.{domain}",
    ]
    assert records["dkim._domainkey"].recommended == f"dkim._domainkey.{dkim_domain}"
    assert records["dkim._domainkey"].valid == [
        f"dkim._domainkey.{dkim_domain}",
        f"dkim._domainkey.{domain}",
    ]


# get_expected_mx_records
def test_custom_domain_validation_get_expected_mx_records_regular_domain():
    domain = random_domain()
    custom_domain = create_custom_domain(domain)

    partner_id = get_proton_partner().id

    dkim_domain = random_domain()
    validator = CustomDomainValidation(
        domain, partner_domains={partner_id: dkim_domain}
    )
    records = validator.get_expected_mx_records(custom_domain)
    # As the domain is not a partner_domain,default records should be used even if
    # there is a config for the partner
    assert len(records) == len(config.EMAIL_SERVERS_WITH_PRIORITY)
    for i in range(len(config.EMAIL_SERVERS_WITH_PRIORITY)):
        config_record = config.EMAIL_SERVERS_WITH_PRIORITY[i]
        assert records[config_record[0]].recommended == config_record[1]
        assert records[config_record[0]].valid == [config_record[1]]


def test_custom_domain_validation_get_expected_mx_records_domain_from_partner():
    domain = random_domain()
    custom_domain = create_custom_domain(domain)

    partner_id = get_proton_partner().id
    custom_domain.partner_id = partner_id
    Session.commit()

    dkim_domain = random_domain()
    validator = CustomDomainValidation(dkim_domain)
    expected_records = validator.get_expected_mx_records(custom_domain)
    # As the domain is a partner_domain but there is no custom config for partner, default records
    # should be used
    assert len(expected_records) == len(config.EMAIL_SERVERS_WITH_PRIORITY)
    for i in range(len(config.EMAIL_SERVERS_WITH_PRIORITY)):
        config_record = config.EMAIL_SERVERS_WITH_PRIORITY[i]
        expected = expected_records[config_record[0]]
        assert expected.recommended == config_record[1]
        assert expected.valid == [config_record[1]]


def test_custom_domain_validation_get_expected_mx_records_domain_from_partner_with_custom_config():
    domain = random_domain()
    custom_domain = create_custom_domain(domain)

    partner_id = get_proton_partner().id
    custom_domain.partner_id = partner_id
    Session.commit()

    dkim_domain = random_domain()
    expected_mx_domain = random_domain()
    validator = CustomDomainValidation(
        dkim_domain, partner_domains={partner_id: expected_mx_domain}
    )
    expected_records = validator.get_expected_mx_records(custom_domain)
    # As the domain is a partner_domain and there is a custom config for partner, partner records
    # should be used
    assert len(expected_records) == 2

    assert expected_records[10].recommended == f"mx1.{expected_mx_domain}."
    assert expected_records[10].valid == [f"mx1.{expected_mx_domain}.", "ms1.a"]
    assert expected_records[20].recommended == f"mx2.{expected_mx_domain}."
    assert expected_records[20].valid == [f"mx2.{expected_mx_domain}.", "mx2.b"]


# get_expected_spf_records
def test_custom_domain_validation_get_expected_spf_record_regular_domain():
    domain = random_domain()
    custom_domain = create_custom_domain(domain)

    partner_id = get_proton_partner().id

    dkim_domain = random_domain()
    validator = CustomDomainValidation(
        domain, partner_domains={partner_id: dkim_domain}
    )
    record = validator.get_expected_spf_record(custom_domain)
    # As the domain is not a partner_domain, default records should be used even if
    # there is a config for the partner
    assert record == f"v=spf1 include:{config.EMAIL_DOMAIN} ~all"


def test_custom_domain_validation_get_expected_spf_record_domain_from_partner():
    domain = random_domain()
    custom_domain = create_custom_domain(domain)

    partner_id = get_proton_partner().id
    custom_domain.partner_id = partner_id
    Session.commit()

    dkim_domain = random_domain()
    validator = CustomDomainValidation(dkim_domain)
    record = validator.get_expected_spf_record(custom_domain)
    # As the domain is a partner_domain but there is no custom config for partner, default records
    # should be used
    assert record == f"v=spf1 include:{config.EMAIL_DOMAIN} ~all"


def test_custom_domain_validation_get_expected_spf_record_domain_from_partner_with_custom_config():
    domain = random_domain()
    custom_domain = create_custom_domain(domain)

    partner_id = get_proton_partner().id
    custom_domain.partner_id = partner_id
    Session.commit()

    dkim_domain = random_domain()
    expected_mx_domain = random_domain()
    validator = CustomDomainValidation(
        dkim_domain, partner_domains={partner_id: expected_mx_domain}
    )
    record = validator.get_expected_spf_record(custom_domain)
    # As the domain is a partner_domain and there is a custom config for partner, partner records
    # should be used
    assert record == f"v=spf1 include:{expected_mx_domain} ~all"


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


def test_custom_domain_validation_validate_dkim_records_success_with_old_system():
    dkim_domain = random_domain()
    dns_client = InMemoryDNSClient()
    validator = CustomDomainValidation(dkim_domain, dns_client)

    user_domain = random_domain()

    # One domain right, other domains missing
    dns_client.set_cname_record(
        f"dkim._domainkey.{user_domain}", f"dkim._domainkey.{dkim_domain}"
    )

    domain = create_custom_domain(user_domain)

    # DKIM is verified
    domain.dkim_verified = True
    Session.commit()

    res = validator.validate_dkim_records(domain)
    assert len(res) == 2
    assert f"dkim02._domainkey.{user_domain}" in res
    assert f"dkim03._domainkey.{user_domain}" in res

    # Flag is not cleared
    db_domain = CustomDomain.get_by(id=domain.id)
    assert db_domain.dkim_verified is True


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

    dns_client.set_txt_record(
        domain.domain, validator.get_ownership_verification_record(domain).valid
    )
    res = validator.validate_domain_ownership(domain)

    assert res.success is True
    assert len(res.errors) == 0

    db_domain = CustomDomain.get_by(id=domain.id)
    assert db_domain.ownership_verified is True


def test_custom_domain_validation_validate_ownership_from_partner_success():
    dns_client = InMemoryDNSClient()
    partner_id = get_proton_partner().id

    prefix = random_string()
    validator = CustomDomainValidation(
        random_domain(),
        dns_client,
        partner_domains_validation_prefixes={partner_id: prefix},
    )

    domain = create_custom_domain(random_domain())
    domain.partner_id = partner_id
    Session.commit()

    dns_client.set_txt_record(
        domain.domain, validator.get_ownership_verification_record(domain).valid
    )
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
    wrong_records = {10: [wrong_record_1], 20: [wrong_record_2]}
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

    mx_records_by_prio = validator.get_expected_mx_records(domain)
    dns_records = {
        priority: mx_records_by_prio[priority].valid for priority in mx_records_by_prio
    }
    dns_client.set_mx_records(domain.domain, dns_records)
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


def test_custom_domain_validation_validate_spf_records_partner_domain_success():
    dns_client = InMemoryDNSClient()
    proton_partner_id = get_proton_partner().id

    expected_domain = random_domain()
    validator = CustomDomainValidation(
        dkim_domain=random_domain(),
        dns_client=dns_client,
        partner_domains={proton_partner_id: expected_domain},
    )

    domain = create_custom_domain(random_domain())
    domain.partner_id = proton_partner_id
    Session.commit()

    dns_client.set_txt_record(domain.domain, [f"v=spf1 include:{expected_domain}"])
    res = validator.validate_spf_records(domain)

    assert res.success is True
    assert len(res.errors) == 0

    db_domain = CustomDomain.get_by(id=domain.id)
    assert db_domain.spf_verified is True


def test_custom_domain_validation_validate_spf_cleans_verification_record():
    dns_client = InMemoryDNSClient()
    proton_partner_id = get_proton_partner().id

    expected_domain = random_domain()
    validator = CustomDomainValidation(
        dkim_domain=random_domain(),
        dns_client=dns_client,
        partner_domains={proton_partner_id: expected_domain},
    )

    domain = create_custom_domain(random_domain())
    domain.partner_id = proton_partner_id
    Session.commit()

    ownership_records = validator.get_ownership_verification_record(domain)

    for ownership_record in ownership_records.valid:
        wrong_record = random_string()
        dns_client.set_txt_record(
            hostname=domain.domain,
            txt_list=[wrong_record, ownership_record],
        )
        res = validator.validate_spf_records(domain)

        assert res.success is False
        assert len(res.errors) == 1
        assert res.errors[0] == wrong_record


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
