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


# DNS lookup error detection


def _network_client_raising(exc):
    from unittest.mock import MagicMock
    from app.dns_utils import NetworkDNSClient

    client = NetworkDNSClient(["127.0.0.1"])
    client._resolver = MagicMock()
    client._resolver.resolve.side_effect = exc
    return client


def test_network_client_lookup_error_is_swallowed_by_default():
    import dns.resolver

    client = _network_client_raising(
        dns.resolver.LifetimeTimeout(timeout=5.0, errors=[])
    )
    assert client.get_mx_domains("example.com") == {}
    assert client.get_txt_record("example.com") == []
    assert client.get_cname_record("example.com") is None
    assert client.get_spf_domain("example.com") == []


def test_network_client_lookup_error_raises_when_asked():
    import dns.resolver
    import pytest
    from app.dns_utils import DNSLookupError

    for exc in (
        dns.resolver.LifetimeTimeout(timeout=5.0, errors=[]),
        dns.resolver.NoNameservers(),
    ):
        client = _network_client_raising(exc)
        with pytest.raises(DNSLookupError):
            client.get_mx_domains("example.com", raise_on_error=True)
        with pytest.raises(DNSLookupError):
            client.get_txt_record("example.com", raise_on_error=True)
        with pytest.raises(DNSLookupError):
            client.get_cname_record("example.com", raise_on_error=True)
        with pytest.raises(DNSLookupError):
            client.get_spf_domain("example.com", raise_on_error=True)


def test_network_client_missing_record_is_not_an_error():
    import dns.resolver

    for exc in (dns.resolver.NXDOMAIN(), dns.resolver.NoAnswer()):
        client = _network_client_raising(exc)
        assert client.get_mx_domains("example.com", raise_on_error=True) == {}
        assert client.get_txt_record("example.com", raise_on_error=True) == []
        assert client.get_cname_record("example.com", raise_on_error=True) is None


def test_in_memory_client_lookup_error():
    import pytest
    from app.dns_utils import DNSLookupError

    client = InMemoryDNSClient()
    client.set_mx_records("example.com", {10: ["mx.example.com."]})
    client.set_lookup_error("example.com", "MX")
    assert client.get_mx_domains("example.com") == {}
    with pytest.raises(DNSLookupError):
        client.get_mx_domains("example.com", raise_on_error=True)
