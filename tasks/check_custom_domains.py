from dataclasses import dataclass

import arrow
from sqlalchemy.orm.exc import ObjectDeletedError

from app import config
from app.custom_domain_validation import CustomDomainValidation, is_mx_equivalent
from app.db import Session
from app.dns_utils import get_mx_domains
from app.email_utils import send_email_with_rate_control, render
from app.log import LOG
from app.models import CustomDomain, Alias


@dataclass
class RecordAlertConfig:
    record_name: str
    alert_type: str
    template: str
    subject_infix: str


MX_ALERT = RecordAlertConfig(
    record_name="MX",
    alert_type=config.AlERT_WRONG_MX_RECORD_CUSTOM_DOMAIN,
    template="transactional/custom-domain-dns-issue.txt.jinja2",
    subject_infix="",
)
DKIM_ALERT = RecordAlertConfig(
    record_name="DKIM",
    alert_type=config.ALERT_WRONG_DKIM_RECORD_CUSTOM_DOMAIN,
    template="transactional/custom-domain-dkim-issue.txt.jinja2",
    subject_infix="DKIM ",
)
DMARC_ALERT = RecordAlertConfig(
    record_name="DMARC",
    alert_type=config.ALERT_WRONG_DMARC_RECORD_CUSTOM_DOMAIN,
    template="transactional/custom-domain-dmarc-issue.txt.jinja2",
    subject_infix="DMARC ",
)


def check_all_custom_domains():
    # Delete custom domains that haven't been verified in a month
    for custom_domain in (
        CustomDomain.filter(
            CustomDomain.verified == False,  # noqa: E712
            CustomDomain.created_at < arrow.now().shift(months=-1),
        )
        .enable_eagerloads(False)
        .yield_per(100)
    ):
        alias_count = Alias.filter(Alias.custom_domain_id == custom_domain.id).count()
        if alias_count > 0:
            LOG.warning(
                f"Custom Domain {custom_domain} has {alias_count} aliases. Won't delete"
            )
        else:
            LOG.i(f"Deleting unverified old custom domain {custom_domain}")
            CustomDomain.delete(custom_domain.id)

    LOG.d("Check verified domain for DNS issues")

    last_custom_domain_id = 0
    while True:
        custom_domains = (
            CustomDomain.filter(
                CustomDomain.verified == True,  # noqa: E712
                CustomDomain.id > last_custom_domain_id,
            )
            .order_by(CustomDomain.id.asc())
            .limit(100)
            .all()
        )
        if len(custom_domains) == 0:
            break
        for custom_domain in custom_domains:
            last_custom_domain_id = max(last_custom_domain_id, custom_domain.id)
            try:
                check_single_custom_domain(custom_domain)
            except ObjectDeletedError:
                LOG.i("custom domain has been deleted")
        # This may be a long running process. Refetch a conn periodically
        Session.close()


def _send_alert(
    custom_domain: CustomDomain,
    user,
    domain_dns_url: str,
    provider: str,
    cfg: RecordAlertConfig,
):
    LOG.w(
        "Alert domain %s check fails %s about %s", cfg.record_name, user, custom_domain
    )
    send_email_with_rate_control(
        user,
        cfg.alert_type,
        user.email,
        f"Please update {custom_domain.domain} {cfg.subject_infix}DNS on {provider}",
        render(
            cfg.template,
            user=user,
            custom_domain=custom_domain,
            domain_dns_url=domain_dns_url,
        ),
        max_nb_alert=1,
        nb_day=30,
        retries=3,
    )


def check_single_custom_domain(custom_domain: CustomDomain):
    if custom_domain.is_sl_subdomain:
        return
    if custom_domain.user.disabled:
        return
    user = custom_domain.user
    # snapshot before validate_dkim_records()/validate_dmarc_records() below can commit
    # and bump these, which would otherwise throw off the once-a-day throttles
    mx_last_updated_at = custom_domain.updated_at
    dkim_last_updated_at = custom_domain.dkim_nb_failed_checks_updated_at
    dmarc_last_updated_at = custom_domain.dmarc_nb_failed_checks_updated_at

    mx_domains = get_mx_domains(custom_domain.domain)
    validator = CustomDomainValidation(
        dkim_domain=config.EMAIL_DOMAIN,
        partner_domains=config.PARTNER_DNS_CUSTOM_DOMAINS,
        partner_domains_validation_prefixes=config.PARTNER_CUSTOM_DOMAIN_VALIDATION_PREFIXES,
    )
    expected_custom_domains = validator.get_expected_mx_records(custom_domain)
    mx_ok = is_mx_equivalent(mx_domains, expected_custom_domains)

    dkim_errors = validator.validate_dkim_records(custom_domain)
    dkim_ok = len(dkim_errors) == 0
    dmarc_ok = validator.validate_dmarc_records(custom_domain).success

    domain_dns_url = f"{config.URL}/dashboard/domains/{custom_domain.id}/dns"
    provider = "Proton" if user.has_used_alias_from_partner() else "SimpleLogin"
    now = arrow.now()

    if mx_ok:
        custom_domain.nb_failed_checks = 0
    else:
        LOG.w(
            f"MX check failed for domain {custom_domain} of user {user}. "
            f"Retried {custom_domain.nb_failed_checks} days",
        )
        if not mx_last_updated_at or mx_last_updated_at <= now.shift(days=-1):
            custom_domain.nb_failed_checks += 1

        if custom_domain.nb_failed_checks > config.MAX_DOMAIN_CHECKS:
            _send_alert(custom_domain, user, domain_dns_url, provider, MX_ALERT)
            LOG.w(
                "De-verifying domain %s after %d failed MX checks",
                custom_domain,
                custom_domain.nb_failed_checks,
            )
            custom_domain.verified = False
            custom_domain.spf_verified = False
            custom_domain.nb_failed_checks = 0

    if dkim_ok:
        custom_domain.dkim_nb_failed_checks = 0
    else:
        LOG.w(
            f"DKIM check failed for domain {custom_domain} of user {user}. "
            f"Retried {custom_domain.dkim_nb_failed_checks} days",
        )
        if not dkim_last_updated_at or dkim_last_updated_at <= now.shift(days=-1):
            custom_domain.dkim_nb_failed_checks += 1
            custom_domain.dkim_nb_failed_checks_updated_at = now

        if custom_domain.dkim_nb_failed_checks > config.MAX_DOMAIN_CHECKS:
            _send_alert(custom_domain, user, domain_dns_url, provider, DKIM_ALERT)
            LOG.w(
                "Un-verifying DKIM for domain %s after %d failed checks",
                custom_domain,
                custom_domain.dkim_nb_failed_checks,
            )
            custom_domain.dkim_verified = False
            custom_domain.dkim_nb_failed_checks = 0

    if dmarc_ok:
        custom_domain.dmarc_nb_failed_checks = 0
    else:
        LOG.w(
            f"DMARC check failed for domain {custom_domain} of user {user}. "
            f"Retried {custom_domain.dmarc_nb_failed_checks} days",
        )
        if not dmarc_last_updated_at or dmarc_last_updated_at <= now.shift(days=-1):
            custom_domain.dmarc_nb_failed_checks += 1
            custom_domain.dmarc_nb_failed_checks_updated_at = now

        if custom_domain.dmarc_nb_failed_checks > config.MAX_DOMAIN_CHECKS:
            _send_alert(custom_domain, user, domain_dns_url, provider, DMARC_ALERT)
            LOG.w(
                "Un-verifying DMARC for domain %s after %d failed checks",
                custom_domain,
                custom_domain.dmarc_nb_failed_checks,
            )
            custom_domain.dmarc_verified = False
            custom_domain.dmarc_nb_failed_checks = 0

    Session.commit()
