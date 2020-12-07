from app.dns_utils import get_mx_domains, get_spf_domain, get_txt_record

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
