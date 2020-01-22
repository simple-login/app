from app.email_utils import (
    get_email_name,
    get_email_part,
    get_email_local_part,
    get_email_domain_part,
    email_belongs_to_alias_domains,
)


def test_get_email_name():
    assert get_email_name("First Last <ab@cd.com>") == "First Last"
    assert get_email_name("First Last<ab@cd.com>") == "First Last"
    assert get_email_name("  First Last   <ab@cd.com>") == "First Last"
    assert get_email_name("ab@cd.com") == ""


def test_get_email_part():
    assert get_email_part("First Last <ab@cd.com>") == "ab@cd.com"
    assert get_email_part("First Last<ab@cd.com>") == "ab@cd.com"
    assert get_email_part("  First Last   <ab@cd.com>") == "ab@cd.com"
    assert get_email_part("ab@cd.com") == "ab@cd.com"


def test_get_email_local_part():
    assert get_email_local_part("ab@cd.com") == "ab"


def test_get_email_domain_part():
    assert get_email_domain_part("ab@cd.com") == "cd.com"


def test_email_belongs_to_alias_domains():
    # default alias domain
    assert email_belongs_to_alias_domains("ab@sl.local")
    assert not email_belongs_to_alias_domains("ab@not-exist.local")

    assert email_belongs_to_alias_domains("hey@d1.test")
    assert not email_belongs_to_alias_domains("hey@d3.test")
