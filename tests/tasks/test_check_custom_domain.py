import arrow
from unittest.mock import patch

from app import config
from app.constants import DMARC_RECORD
from app.custom_domain_validation import DomainValidationResult
from app.db import Session
from app.dns_utils import InMemoryDNSClient, set_global_dns_client
from app.models import CustomDomain, SentAlert
from app.proton.proton_partner import get_proton_partner
from tasks.check_custom_domains import (
    DKIM_ALERT,
    DMARC_ALERT,
    check_all_custom_domains,
    check_single_custom_domain,
)
from tests.utils import create_partner_linked_user, create_new_user, random_string

DKIM_KEYS = ("dkim", "dkim02", "dkim03")


def make_dns_client(custom_domain: CustomDomain) -> InMemoryDNSClient:
    """DNS client with correct MX, DKIM and DMARC records."""
    dns_client = InMemoryDNSClient()
    dns_client.set_mx_records(
        custom_domain.domain, {10: [config.EMAIL_SERVERS_WITH_PRIORITY[0][1]]}
    )
    for key in DKIM_KEYS:
        dns_client.set_cname_record(
            f"{key}._domainkey.{custom_domain.domain}",
            f"{key}._domainkey.{config.EMAIL_DOMAIN}",
        )
    dns_client.set_txt_record(f"_dmarc.{custom_domain.domain}", [DMARC_RECORD])
    return dns_client


def run_check(custom_domain: CustomDomain, dns_client: InMemoryDNSClient):
    with patch("tasks.check_custom_domains.get_mx_domains") as mx_mock:
        mx_mock.return_value = dns_client.get_mx_domains(custom_domain.domain)
        set_global_dns_client(dns_client)
        try:
            check_single_custom_domain(custom_domain)
        finally:
            set_global_dns_client(None)


def test_check_single_custom_domain_increments_failed_checks(flask_client):
    user = create_new_user()
    # Set updated_at to 2 days ago so the increment logic runs
    custom_domain = CustomDomain.create(
        user_id=user.id,
        domain=random_string(),
        verified=True,
        nb_failed_checks=0,
        commit=True,
    )
    # Manually set updated_at to simulate an old update
    custom_domain.updated_at = arrow.now().shift(days=-2)
    Session.commit()

    with (
        patch("tasks.check_custom_domains.get_mx_domains", return_value=[]),
        patch("tasks.check_custom_domains.is_mx_equivalent", return_value=False),
        patch("tasks.check_custom_domains.send_email_with_rate_control"),
        patch(
            "tasks.check_custom_domains.get_network_dns_client",
            return_value=InMemoryDNSClient(),
        ),
    ):
        check_single_custom_domain(custom_domain)
    assert custom_domain.nb_failed_checks == 1
    assert custom_domain.verified is True


def test_check_single_custom_domain_deactivates_after_threshold(flask_client):
    user = create_new_user()
    # Start at 4 so that after one increment (4->5), 5 > MAX_DOMAIN_CHECKS (4) triggers deactivation
    custom_domain = CustomDomain.create(
        user_id=user.id,
        domain=random_string(),
        verified=True,
        nb_failed_checks=4,
        commit=True,
    )
    # Set updated_at to 2 days ago so the increment logic runs
    custom_domain.updated_at = arrow.now().shift(days=-2)
    Session.commit()

    with (
        patch("tasks.check_custom_domains.get_mx_domains", return_value=[]),
        patch("tasks.check_custom_domains.is_mx_equivalent", return_value=False),
        patch("tasks.check_custom_domains.send_email_with_rate_control"),
        patch(
            "tasks.check_custom_domains.get_network_dns_client",
            return_value=InMemoryDNSClient(),
        ),
    ):
        check_single_custom_domain(custom_domain)
    assert custom_domain.verified is False
    assert custom_domain.dkim_verified is False
    assert custom_domain.dmarc_verified is False
    assert custom_domain.spf_verified is False
    assert custom_domain.nb_failed_checks == 0


def test_check_single_custom_domain_resets_on_success(flask_client):
    user = create_new_user()
    custom_domain = CustomDomain.create(
        user_id=user.id,
        domain=random_string(),
        verified=True,
        nb_failed_checks=2,
        commit=True,
    )
    with (
        patch("tasks.check_custom_domains.get_mx_domains", return_value=[]),
        patch("tasks.check_custom_domains.is_mx_equivalent", return_value=True),
        patch(
            "app.custom_domain_validation.CustomDomainValidation.validate_dkim_records",
            return_value=[],
        ),
        patch(
            "app.custom_domain_validation.CustomDomainValidation.validate_dmarc_records",
            return_value=DomainValidationResult(success=True, errors=[]),
        ),
    ):
        check_single_custom_domain(custom_domain)
    assert custom_domain.nb_failed_checks == 0
    assert custom_domain.verified is True


def test_check_single_custom_domain_dkim_failure_is_independent_of_mx(flask_client):
    user = create_new_user()
    custom_domain = CustomDomain.create(
        user_id=user.id,
        domain=random_string(),
        verified=True,
        dkim_verified=True,
        dmarc_verified=True,
        nb_failed_checks=0,
        dkim_nb_failed_checks=0,
        commit=True,
    )
    custom_domain.dkim_nb_failed_checks_updated_at = arrow.now().shift(days=-2)
    Session.commit()

    with (
        patch("tasks.check_custom_domains.get_mx_domains", return_value=[]),
        patch("tasks.check_custom_domains.is_mx_equivalent", return_value=True),
        patch(
            "app.custom_domain_validation.CustomDomainValidation.validate_dkim_records",
            return_value=["bad dkim"],
        ),
        patch(
            "app.custom_domain_validation.CustomDomainValidation.validate_dmarc_records",
            return_value=DomainValidationResult(success=True, errors=[]),
        ),
        patch("tasks.check_custom_domains.send_email_with_rate_control"),
        patch(
            "tasks.check_custom_domains.get_network_dns_client",
            return_value=InMemoryDNSClient(),
        ),
    ):
        check_single_custom_domain(custom_domain)

    assert custom_domain.dkim_nb_failed_checks == 1
    assert custom_domain.nb_failed_checks == 0
    assert custom_domain.verified is True
    assert custom_domain.dkim_verified is True
    assert custom_domain.dmarc_verified is True


def test_check_single_custom_domain_dkim_deactivates_only_dkim_after_threshold(
    flask_client,
):
    user = create_new_user()
    custom_domain = CustomDomain.create(
        user_id=user.id,
        domain=random_string(),
        verified=True,
        dkim_verified=True,
        dmarc_verified=True,
        spf_verified=True,
        nb_failed_checks=0,
        dkim_nb_failed_checks=4,
        commit=True,
    )
    custom_domain.dkim_nb_failed_checks_updated_at = arrow.now().shift(days=-2)
    Session.commit()

    with (
        patch("tasks.check_custom_domains.get_mx_domains", return_value=[]),
        patch("tasks.check_custom_domains.is_mx_equivalent", return_value=True),
        patch(
            "app.custom_domain_validation.CustomDomainValidation.validate_dkim_records",
            return_value=["bad dkim"],
        ),
        patch(
            "app.custom_domain_validation.CustomDomainValidation.validate_dmarc_records",
            return_value=DomainValidationResult(success=True, errors=[]),
        ),
        patch("tasks.check_custom_domains.send_email_with_rate_control"),
        patch(
            "tasks.check_custom_domains.get_network_dns_client",
            return_value=InMemoryDNSClient(),
        ),
    ):
        check_single_custom_domain(custom_domain)

    assert custom_domain.dkim_nb_failed_checks == 0
    assert custom_domain.dkim_verified is False
    assert custom_domain.verified is True
    assert custom_domain.spf_verified is True
    assert custom_domain.dmarc_verified is True
    assert custom_domain.nb_failed_checks == 0


def test_check_single_custom_domain_dkim_throttled_within_a_day(flask_client):
    user = create_new_user()
    custom_domain = CustomDomain.create(
        user_id=user.id,
        domain=random_string(),
        verified=True,
        dkim_verified=True,
        dmarc_verified=True,
        nb_failed_checks=0,
        dkim_nb_failed_checks=1,
        commit=True,
    )
    custom_domain.dkim_nb_failed_checks_updated_at = arrow.now()
    Session.commit()

    with (
        patch("tasks.check_custom_domains.get_mx_domains", return_value=[]),
        patch("tasks.check_custom_domains.is_mx_equivalent", return_value=True),
        patch(
            "app.custom_domain_validation.CustomDomainValidation.validate_dkim_records",
            return_value=["bad dkim"],
        ),
        patch(
            "app.custom_domain_validation.CustomDomainValidation.validate_dmarc_records",
            return_value=DomainValidationResult(success=True, errors=[]),
        ),
        patch("tasks.check_custom_domains.send_email_with_rate_control"),
        patch(
            "tasks.check_custom_domains.get_network_dns_client",
            return_value=InMemoryDNSClient(),
        ),
    ):
        check_single_custom_domain(custom_domain)

    assert custom_domain.dkim_nb_failed_checks == 1


def test_check_single_custom_domain_provider_follows_domain_partner_not_user(
    flask_client,
):
    user, _ = create_partner_linked_user()
    custom_domain = CustomDomain.create(
        user_id=user.id,
        domain=random_string(),
        verified=True,
        partner_id=None,
        nb_failed_checks=4,
        commit=True,
    )
    custom_domain.updated_at = arrow.now().shift(days=-2)
    Session.commit()

    with (
        patch("tasks.check_custom_domains.get_mx_domains", return_value=[]),
        patch("tasks.check_custom_domains.is_mx_equivalent", return_value=False),
        patch(
            "app.custom_domain_validation.CustomDomainValidation.validate_dkim_records",
            return_value=[],
        ),
        patch(
            "app.custom_domain_validation.CustomDomainValidation.validate_dmarc_records",
            return_value=DomainValidationResult(success=True, errors=[]),
        ),
        patch(
            "tasks.check_custom_domains.send_email_with_rate_control"
        ) as send_email_mock,
        patch(
            "tasks.check_custom_domains.get_network_dns_client",
            return_value=InMemoryDNSClient(),
        ),
    ):
        check_single_custom_domain(custom_domain)

    subject = send_email_mock.call_args.args[3]
    assert "SimpleLogin" in subject
    assert "Proton" not in subject


def test_check_single_custom_domain_provider_uses_proton_when_domain_partner_is_proton(
    flask_client,
):
    user = create_new_user()
    custom_domain = CustomDomain.create(
        user_id=user.id,
        domain=random_string(),
        verified=True,
        partner_id=get_proton_partner().id,
        nb_failed_checks=4,
        commit=True,
    )
    custom_domain.updated_at = arrow.now().shift(days=-2)
    Session.commit()

    with (
        patch("tasks.check_custom_domains.get_mx_domains", return_value=[]),
        patch("tasks.check_custom_domains.is_mx_equivalent", return_value=False),
        patch(
            "app.custom_domain_validation.CustomDomainValidation.validate_dkim_records",
            return_value=[],
        ),
        patch(
            "app.custom_domain_validation.CustomDomainValidation.validate_dmarc_records",
            return_value=DomainValidationResult(success=True, errors=[]),
        ),
        patch(
            "tasks.check_custom_domains.send_email_with_rate_control"
        ) as send_email_mock,
        patch(
            "tasks.check_custom_domains.get_network_dns_client",
            return_value=InMemoryDNSClient(),
        ),
    ):
        check_single_custom_domain(custom_domain)

    subject = send_email_mock.call_args.args[3]
    assert "Proton" in subject


def test_check_custom_domain_deletes_old_domains():
    user = create_new_user()
    now = arrow.utcnow()
    cd_to_delete = CustomDomain.create(
        user_id=user.id,
        domain=random_string(),
        verified=False,
        created_at=now.shift(months=-3),
    ).id
    cd_to_keep = CustomDomain.create(
        user_id=user.id,
        domain=random_string(),
        verified=True,
        created_at=now.shift(months=-3),
    ).id
    check_all_custom_domains()
    assert CustomDomain.get(cd_to_delete) is None
    assert CustomDomain.get(cd_to_keep) is not None


def _alert_count(user, alert_type: str, domain: str) -> int:
    return SentAlert.filter_by(
        alert_type=f"{alert_type}:{domain}", to_email=user.email
    ).count()


def test_never_configured_dkim_dmarc_never_alerts(flask_client):
    """A domain that never had DKIM/DMARC set up must not be counted or alerted."""
    user = create_new_user()
    custom_domain = CustomDomain.create(
        user_id=user.id,
        domain=random_string(),
        verified=True,
        dkim_verified=False,
        dmarc_verified=False,
        commit=True,
    )
    dns_client = InMemoryDNSClient()
    dns_client.set_mx_records(
        custom_domain.domain, {10: [config.EMAIL_SERVERS_WITH_PRIORITY[0][1]]}
    )
    # no DKIM CNAMEs, no DMARC TXT record, and the counters already over the limit
    custom_domain.dkim_nb_failed_checks = config.MAX_DOMAIN_CHECKS + 1
    custom_domain.dmarc_nb_failed_checks = config.MAX_DOMAIN_CHECKS + 1
    Session.commit()

    for _ in range(3):
        run_check(custom_domain, dns_client)

    assert custom_domain.dkim_nb_failed_checks == 0
    assert custom_domain.dmarc_nb_failed_checks == 0
    assert custom_domain.dkim_verified is False
    assert custom_domain.dmarc_verified is False
    assert _alert_count(user, DKIM_ALERT.alert_type, custom_domain.domain) == 0
    assert _alert_count(user, DMARC_ALERT.alert_type, custom_domain.domain) == 0


def test_legacy_single_dkim_record_keeps_flag_and_does_not_alert(flask_client):
    """Domains signed only with the original dkim._domainkey CNAME are still fine."""
    user = create_new_user()
    custom_domain = CustomDomain.create(
        user_id=user.id,
        domain=random_string(),
        verified=True,
        dkim_verified=True,
        dmarc_verified=True,
        commit=True,
    )
    dns_client = make_dns_client(custom_domain)
    for key in ("dkim02", "dkim03"):
        del dns_client.cname_records[f"{key}._domainkey.{custom_domain.domain}"]
    custom_domain.dkim_nb_failed_checks = config.MAX_DOMAIN_CHECKS + 1
    Session.commit()

    for _ in range(3):
        run_check(custom_domain, dns_client)

    assert custom_domain.dkim_nb_failed_checks == 0
    assert custom_domain.dkim_verified is True
    assert _alert_count(user, DKIM_ALERT.alert_type, custom_domain.domain) == 0


def test_transient_dns_failure_keeps_flag_until_threshold(flask_client):
    """One failed lookup must not clear dkim_verified; only the threshold may."""
    user = create_new_user()
    custom_domain = CustomDomain.create(
        user_id=user.id,
        domain=random_string(),
        verified=True,
        dkim_verified=True,
        dmarc_verified=True,
        commit=True,
    )
    dns_client = make_dns_client(custom_domain)

    # a single transient DNS failure (all DKIM lookups come back empty)
    dns_client.cname_records.clear()
    run_check(custom_domain, dns_client)
    assert custom_domain.dkim_nb_failed_checks == 1
    assert custom_domain.dkim_verified is True
    assert _alert_count(user, DKIM_ALERT.alert_type, custom_domain.domain) == 0

    # records recover before the threshold: counter resets, nothing happens
    for key in DKIM_KEYS:
        dns_client.set_cname_record(
            f"{key}._domainkey.{custom_domain.domain}",
            f"{key}._domainkey.{config.EMAIL_DOMAIN}",
        )
    run_check(custom_domain, dns_client)
    assert custom_domain.dkim_nb_failed_checks == 0
    assert custom_domain.dkim_verified is True

    # the failure lasts past the threshold: alert sent, then the flag flips
    dns_client.cname_records.clear()
    for _ in range(config.MAX_DOMAIN_CHECKS + 1):
        custom_domain.dkim_nb_failed_checks_updated_at = None
        Session.commit()
        run_check(custom_domain, dns_client)

    assert custom_domain.dkim_verified is False
    assert custom_domain.dkim_nb_failed_checks == 0
    assert _alert_count(user, DKIM_ALERT.alert_type, custom_domain.domain) == 1


def test_check_is_read_only_on_flags(flask_client):
    """The cron check must never mutate dkim/dmarc flags by itself."""
    user = create_new_user()
    custom_domain = CustomDomain.create(
        user_id=user.id,
        domain=random_string(),
        verified=True,
        dkim_verified=True,
        dmarc_verified=True,
        commit=True,
    )
    dns_client = make_dns_client(custom_domain)
    run_check(custom_domain, dns_client)
    assert custom_domain.dkim_verified is True
    assert custom_domain.dmarc_verified is True

    dns_client.cname_records.clear()
    dns_client.txt_records.clear()
    dns_client.set_mx_records(
        custom_domain.domain, {10: [config.EMAIL_SERVERS_WITH_PRIORITY[0][1]]}
    )
    run_check(custom_domain, dns_client)
    assert custom_domain.dkim_verified is True
    assert custom_domain.dmarc_verified is True


def test_alert_rate_limit_is_per_domain(flask_client):
    """A second failing domain must still get its own alert and de-verification."""
    user = create_new_user()
    domains = [
        CustomDomain.create(
            user_id=user.id,
            domain=random_string(),
            verified=True,
            dkim_verified=True,
            dmarc_verified=True,
            dkim_nb_failed_checks=config.MAX_DOMAIN_CHECKS,
            commit=True,
        )
        for _ in range(2)
    ]
    dns_client = InMemoryDNSClient()
    for custom_domain in domains:
        dns_client.set_mx_records(
            custom_domain.domain, {10: [config.EMAIL_SERVERS_WITH_PRIORITY[0][1]]}
        )
    Session.commit()

    for custom_domain in domains:
        custom_domain.dkim_nb_failed_checks_updated_at = None
        Session.commit()
        run_check(custom_domain, dns_client)

    for custom_domain in domains:
        assert custom_domain.dkim_verified is False
        assert custom_domain.dkim_nb_failed_checks == 0
        assert _alert_count(user, DKIM_ALERT.alert_type, custom_domain.domain) == 1


def test_alerted_domain_gets_no_further_alerts(flask_client):
    """Once a domain has been alerted, it stays flagged and is not alerted again."""
    user = create_new_user()
    custom_domain = CustomDomain.create(
        user_id=user.id,
        domain=random_string(),
        verified=True,
        dkim_verified=True,
        dmarc_verified=True,
        dkim_nb_failed_checks=config.MAX_DOMAIN_CHECKS,
        commit=True,
    )
    dns_client = InMemoryDNSClient()
    dns_client.set_mx_records(
        custom_domain.domain, {10: [config.EMAIL_SERVERS_WITH_PRIORITY[0][1]]}
    )
    Session.commit()

    custom_domain.dkim_nb_failed_checks_updated_at = None
    Session.commit()
    run_check(custom_domain, dns_client)
    assert custom_domain.dkim_verified is False
    assert _alert_count(user, DKIM_ALERT.alert_type, custom_domain.domain) == 1

    # further runs must neither re-alert nor re-count the now-unverified domain
    for _ in range(3):
        custom_domain.dkim_nb_failed_checks_updated_at = None
        Session.commit()
        run_check(custom_domain, dns_client)

    assert _alert_count(user, DKIM_ALERT.alert_type, custom_domain.domain) == 1
    assert custom_domain.dkim_nb_failed_checks == 0


def test_counter_timestamp_resets_after_alert(flask_client):
    """After the alert goes out, the debounce timestamp must not throttle a new cycle."""
    user = create_new_user()
    custom_domain = CustomDomain.create(
        user_id=user.id,
        domain=random_string(),
        verified=True,
        dkim_verified=True,
        dmarc_verified=True,
        dkim_nb_failed_checks=config.MAX_DOMAIN_CHECKS,
        commit=True,
    )
    dns_client = InMemoryDNSClient()
    dns_client.set_mx_records(
        custom_domain.domain, {10: [config.EMAIL_SERVERS_WITH_PRIORITY[0][1]]}
    )
    Session.commit()

    custom_domain.dkim_nb_failed_checks_updated_at = None
    Session.commit()
    run_check(custom_domain, dns_client)

    assert custom_domain.dkim_verified is False
    assert custom_domain.dkim_nb_failed_checks == 0
    assert custom_domain.dkim_nb_failed_checks_updated_at is None
