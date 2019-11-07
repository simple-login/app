from email_handler import parse_srs_email


def test_parse_srs_email():
    assert parse_srs_email("srs0=8lgw=y6=outlook.com=abcd@sl.co") == "abcd@outlook.com"
