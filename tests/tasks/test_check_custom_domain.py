import arrow
from unittest.mock import patch

from app.models import CustomDomain
from tasks.check_custom_domains import (
    check_all_custom_domains,
    check_single_custom_domain,
)
from tests.utils import create_new_user, random_string


def test_check_single_custom_domain_increments_failed_checks(flask_client):
    user = create_new_user()
    custom_domain = CustomDomain.create(
        user_id=user.id,
        domain=random_string(),
        verified=True,
        nb_failed_checks=0,
        commit=True,
    )
    with patch("tasks.check_custom_domains.get_mx_domains", return_value=[]), patch(
        "tasks.check_custom_domains.is_mx_equivalent", return_value=False
    ), patch("tasks.check_custom_domains.send_email_with_rate_control"):
        check_single_custom_domain(custom_domain)
    assert custom_domain.nb_failed_checks == 1
    assert custom_domain.verified is True


def test_check_single_custom_domain_deactivates_after_threshold(flask_client):
    user = create_new_user()
    custom_domain = CustomDomain.create(
        user_id=user.id,
        domain=random_string(),
        verified=True,
        nb_failed_checks=2,
        commit=True,
    )
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
