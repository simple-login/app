from app.handler.spamd_result import DmarcCheckResult, SpamdResult
from tests.utils import load_eml_file


def test_dmarc_result_softfail():
    msg = load_eml_file("dmarc_gmail_softfail.eml")
    assert DmarcCheckResult.soft_fail == SpamdResult.extract_from_headers(msg).dmarc
    assert SpamdResult.extract_from_headers(msg).rspamd_score == 0.5


def test_dmarc_result_quarantine():
    msg = load_eml_file("dmarc_quarantine.eml")
    assert DmarcCheckResult.quarantine == SpamdResult.extract_from_headers(msg).dmarc


def test_dmarc_result_reject():
    msg = load_eml_file("dmarc_reject.eml")
    assert DmarcCheckResult.reject == SpamdResult.extract_from_headers(msg).dmarc


def test_dmarc_result_allow():
    msg = load_eml_file("dmarc_allow.eml")
    assert DmarcCheckResult.allow == SpamdResult.extract_from_headers(msg).dmarc


def test_dmarc_result_na():
    msg = load_eml_file("dmarc_na.eml")
    assert DmarcCheckResult.not_available == SpamdResult.extract_from_headers(msg).dmarc


def test_dmarc_result_bad_policy():
    msg = load_eml_file("dmarc_bad_policy.eml")
    assert SpamdResult._get_from_message(msg) is None
    assert DmarcCheckResult.bad_policy == SpamdResult.extract_from_headers(msg).dmarc
    assert SpamdResult._get_from_message(msg) is not None


def test_parse_rspamd_score():
    msg = load_eml_file("dmarc_gmail_softfail.eml")
    assert SpamdResult.extract_from_headers(msg).rspamd_score == 0.5


def test_cannot_parse_rspamd_score():
    msg = load_eml_file("dmarc_cannot_parse_rspamd_score.eml")
    # use the default score when cannot parse
    assert SpamdResult.extract_from_headers(msg).rspamd_score == -1
