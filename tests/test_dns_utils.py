from app.dns_utils import (
    get_mx_domains,
    get_network_dns_client,
    is_mx_equivalent,
    InMemoryDNSClient,
    MxRecord,
)

from tests.utils import random_domain

# use our own domain for test
_DOMAIN = "simplelogin.io"


def test_get_mx_domains():
    r = get_mx_domains(_DOMAIN)

    assert len(r) > 0

    for x in r:
        assert x.priority > 0
        assert x.domain


def test_get_spf_domain():
    r = get_network_dns_client().get_spf_domain(_DOMAIN)
    assert r == ["simplelogin.co"]


def test_get_txt_record():
    r = get_network_dns_client().get_txt_record(_DOMAIN)
    assert len(r) > 0


def test_is_mx_equivalent():
    assert is_mx_equivalent([], [])
    assert is_mx_equivalent(
        mx_domains=[MxRecord(1, "domain")], ref_mx_domains=[MxRecord(1, "domain")]
    )
    assert is_mx_equivalent(
        mx_domains=[MxRecord(10, "domain1"), MxRecord(20, "domain2")],
        ref_mx_domains=[MxRecord(10, "domain1"), MxRecord(20, "domain2")],
    )
    assert is_mx_equivalent(
        mx_domains=[MxRecord(5, "domain1"), MxRecord(10, "domain2")],
        ref_mx_domains=[MxRecord(10, "domain1"), MxRecord(20, "domain2")],
    )
    assert is_mx_equivalent(
        mx_domains=[
            MxRecord(5, "domain1"),
            MxRecord(10, "domain2"),
            MxRecord(20, "domain3"),
        ],
        ref_mx_domains=[MxRecord(10, "domain1"), MxRecord(20, "domain2")],
    )
    assert not is_mx_equivalent(
        mx_domains=[MxRecord(5, "domain1"), MxRecord(10, "domain2")],
        ref_mx_domains=[
            MxRecord(10, "domain1"),
            MxRecord(20, "domain2"),
            MxRecord(20, "domain3"),
        ],
    )


def test_get_spf_record():
    client = InMemoryDNSClient()

    sl_domain = random_domain()
    domain = random_domain()

    spf_record = f"v=spf1 include:{sl_domain}"
    client.set_txt_record(domain, [spf_record, "another record"])
    res = client.get_spf_domain(domain)
    assert res == [sl_domain]
