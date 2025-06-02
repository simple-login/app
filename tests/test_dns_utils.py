from app.custom_domain_validation import is_mx_equivalent, ExpectedValidationRecords
from app.dns_utils import (
    get_mx_domains,
    get_network_dns_client,
    InMemoryDNSClient,
)

from tests.utils import random_domain

# use our own domain for test
_DOMAIN = "simplelogin.io"


def test_get_mx_domains():
    r = get_mx_domains(_DOMAIN)

    assert len(r) > 0

    for prio in r:
        assert prio > 0
        assert len(r[prio]) > 0


def test_get_spf_domain():
    r = get_network_dns_client().get_spf_domain(_DOMAIN)
    assert r == ["simplelogin.co"]


def test_get_txt_record():
    r = get_network_dns_client().get_txt_record(_DOMAIN)
    assert len(r) > 0


def test_is_mx_equivalent():
    assert is_mx_equivalent({}, {})
    assert is_mx_equivalent(
        mx_domains={1: ["domain"]},
        expected_mx_domains={
            1: ExpectedValidationRecords(recommended="nop", allowed=["domain"])
        },
    )
    assert is_mx_equivalent(
        mx_domains={10: ["domain10"], 20: ["domain20"]},
        expected_mx_domains={
            10: ExpectedValidationRecords(recommended="nop", allowed=["domain10"]),
            20: ExpectedValidationRecords(recommended="nop", allowed=["domain20"]),
        },
    )

    assert is_mx_equivalent(
        mx_domains={5: ["domain1"], 10: ["domain2"]},
        expected_mx_domains={
            10: ExpectedValidationRecords(recommended="nop", allowed=["domain1"]),
            20: ExpectedValidationRecords(recommended="nop", allowed=["domain2"]),
        },
    )

    assert not is_mx_equivalent(
        mx_domains={10: ["domain10", "domain11"], 20: ["domain20"]},
        expected_mx_domains={
            10: ExpectedValidationRecords(recommended="nop", allowed=["domain10"]),
            20: ExpectedValidationRecords(recommended="nop", allowed=["domain20"]),
        },
    )
    assert not is_mx_equivalent(
        mx_domains={5: ["domain1"], 10: ["domain2"], 20: ["domain3"]},
        expected_mx_domains={
            10: ExpectedValidationRecords(recommended="nop", allowed=["domain1"]),
            20: ExpectedValidationRecords(recommended="nop", allowed=["domain2"]),
        },
    )
    assert not is_mx_equivalent(
        mx_domains={10: ["domain1"]},
        expected_mx_domains={
            10: ExpectedValidationRecords(recommended="nop", allowed=["domain1"]),
            20: ExpectedValidationRecords(recommended="nop", allowed=["domain2"]),
        },
    )


def test_get_spf_record():
    client = InMemoryDNSClient()

    sl_domain = random_domain()
    domain = random_domain()

    spf_record = f"v=spf1 include:{sl_domain}"
    client.set_txt_record(domain, [spf_record, "another record"])
    res = client.get_spf_domain(domain)
    assert res == [sl_domain]
