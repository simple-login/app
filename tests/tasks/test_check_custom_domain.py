import arrow
from unittest.mock import patch

from app.db import Session
from app.dns_utils import DNSLookupError
from app.models import CustomDomain
from tasks.check_custom_domains import (
    check_all_custom_domains,
    check_single_custom_domain,
)
from tests.utils import create_new_user, random_string


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

    with patch("tasks.check_custom_domains.get_mx_domains", return_value=[]), patch(
        "tasks.check_custom_domains.is_mx_equivalent", return_value=False
    ), patch("tasks.check_custom_domains.send_email_with_rate_control"):
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

    with patch("tasks.check_custom_domains.get_mx_domains", return_value=[]), patch(
        "tasks.check_custom_domains.is_mx_equivalent", return_value=False
    ), patch("tasks.check_custom_domains.send_email_with_rate_control"):
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
    with patch("tasks.check_custom_domains.get_mx_domains", return_value=[]), patch(
        "tasks.check_custom_domains.is_mx_equivalent", return_value=True
    ):
        check_single_custom_domain(custom_domain)
    assert custom_domain.nb_failed_checks == 0
    assert custom_domain.verified is True


def test_check_custom_domain_deletes_old_domains(flask_client):
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
    # The DNS check of verified domains is covered by the tests above. Stub it
    # so this test doesn't do a real DNS lookup per verified domain in the DB.
    with patch("tasks.check_custom_domains.check_single_custom_domain"):
        check_all_custom_domains()
    assert CustomDomain.get(cd_to_delete) is None
    assert CustomDomain.get(cd_to_keep) is not None


def test_check_custom_domain_deletes_unverified_domains_after_five_days(flask_client):
    user = create_new_user()
    now = arrow.utcnow()
    stale = CustomDomain.create(
        user_id=user.id,
        domain=random_string(),
        verified=False,
        created_at=now.shift(days=-6),
    ).id
    recent = CustomDomain.create(
        user_id=user.id,
        domain=random_string(),
        verified=False,
        created_at=now.shift(days=-4),
    ).id
    with patch("tasks.check_custom_domains.check_single_custom_domain"):
        check_all_custom_domains()
    assert CustomDomain.get(stale) is None
    assert CustomDomain.get(recent) is not None


def test_check_single_custom_domain_ignores_dns_lookup_errors(flask_client):
    user = create_new_user()
    custom_domain = CustomDomain.create(
        user_id=user.id,
        domain=random_string(),
        verified=True,
        spf_verified=True,
        nb_failed_checks=4,
        commit=True,
    )
    custom_domain.updated_at = arrow.now().shift(days=-2)
    Session.commit()

    with patch(
        "tasks.check_custom_domains.get_mx_domains",
        side_effect=DNSLookupError(custom_domain.domain, "MX", "Timeout"),
    ), patch("tasks.check_custom_domains.send_email_with_rate_control") as send_mock:
        check_single_custom_domain(custom_domain)
    send_mock.assert_not_called()
    assert custom_domain.verified is True
    assert custom_domain.spf_verified is True
    assert custom_domain.nb_failed_checks == 4
