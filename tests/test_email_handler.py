from email_handler import parse_srs_email, get_email_name


def test_parse_srs_email():
    assert parse_srs_email("srs0=8lgw=y6=outlook.com=abcd@sl.co") == "abcd@outlook.com"


def test_get_email_name():
    assert get_email_name("First Last <ab@cd.com>") == "First Last"
    assert get_email_name("First Last<ab@cd.com>") == "First Last"
    assert get_email_name("  First Last   <ab@cd.com>") == "First Last"
    assert get_email_name("ab@cd.com") == ""
