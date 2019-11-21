from email_handler import get_email_name


def test_get_email_name():
    assert get_email_name("First Last <ab@cd.com>") == "First Last"
    assert get_email_name("First Last<ab@cd.com>") == "First Last"
    assert get_email_name("  First Last   <ab@cd.com>") == "First Last"
    assert get_email_name("ab@cd.com") == ""
