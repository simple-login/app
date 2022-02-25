from app.dns_utils import (
    get_mx_domains,
    get_spf_domain,
    get_txt_record,
    is_mx_equivalent,
)

# use our own domain for test
_DOMAIN = "simplelogin.io"


def test_get_mx_domains():
    r = get_mx_domains(_DOMAIN)

    assert len(r) > 0

    for x in r:
        assert x[0] > 0
        assert x[1]


def test_get_spf_domain():
    r = get_spf_domain(_DOMAIN)
    assert r == ["simplelogin.co"]


def test_get_txt_record():
    r = get_txt_record(_DOMAIN)
    assert len(r) > 0


def test_is_mx_equivalent():
    assert is_mx_equivalent([], [])
    assert is_mx_equivalent([(1, "domain")], [(1, "domain")])
    assert is_mx_equivalent(
        [(10, "domain1"), (20, "domain2")], [(10, "domain1"), (20, "domain2")]
    )
    assert is_mx_equivalent(
        [(5, "domain1"), (10, "domain2")], [(10, "domain1"), (20, "domain2")]
    )
    assert is_mx_equivalent(
        [(5, "domain1"), (10, "domain2"), (20, "domain3")],
        [(10, "domain1"), (20, "domain2")],
    )
    assert not is_mx_equivalent(
        [(5, "domain1"), (10, "domain2")],
        [(10, "domain1"), (20, "domain2"), (20, "domain3")],
    )
