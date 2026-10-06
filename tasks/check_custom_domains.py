from dataclasses import dataclass

import arrow
from sqlalchemy.orm.exc import ObjectDeletedError

from app import config
from app.custom_domain_validation import CustomDomainValidation, is_mx_equivalent
from app.db import Session
from app.dns_utils import get_mx_domains, get_network_dns_client
from app.email_utils import send_email_with_rate_control, render
from app.errors import ProtonPartnerNotSetUp
from app.log import LOG
from app.models import CustomDomain, Alias
from app.proton.proton_partner import get_proton_partner


@dataclass
class RecordAlertConfig:
    record_name: str
    alert_type: str
    template: str
    subject_infix: str
    verified_field: str
    counter_field: str
    counter_updated_at_field: str


MX_ALERT = RecordAlertConfig(
    record_name="MX",
    alert_type=config.AlERT_WRONG_MX_RECORD_CUSTOM_DOMAIN,
    template="transactional/custom-domain-dns-issue.txt.jinja2",
    subject_infix="",
    verified_field="verified",
    counter_field="nb_failed_checks",
    counter_updated_at_field="updated_at",
)
DKIM_ALERT = RecordAlertConfig(
    record_name="DKIM",
    alert_type=config.ALERT_WRONG_DKIM_RECORD_CUSTOM_DOMAIN,
    template="transactional/custom-domain-dkim-issue.txt.jinja2",
    subject_infix="DKIM ",
    verified_field="dkim_verified",
    counter_field="dkim_nb_failed_checks",
    counter_updated_at_field="dkim_nb_failed_checks_updated_at",
)
DMARC_ALERT = RecordAlertConfig(
    record_name="DMARC",
    alert_type=config.ALERT_WRONG_DMARC_RECORD_CUSTOM_DOMAIN,
    template="transactional/custom-domain-dmarc-issue.txt.jinja2",
    subject_infix="DMARC ",
    verified_field="dmarc_verified",
    counter_field="dmarc_nb_failed_checks",
    counter_updated_at_field="dmarc_nb_failed_checks_updated_at",
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
) -> bool:
    LOG.w(
        "Alert domain %s check fails %s about %s", cfg.record_name, user, custom_domain
    )
    return send_email_with_rate_control(
        user,
        # the domain is part of the alert key so each domain has its own rate limit
        f"{cfg.alert_type}:{custom_domain.domain}",
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


def _check_record(
    custom_domain: CustomDomain,
    user,
    record_ok: bool,
    was_verified: bool,
    failed_checks: int,
    last_updated_at,
    now,
    cfg: RecordAlertConfig,
    domain_dns_url: str,
    provider: str,
) -> None:
    """
    Debounce a read-only DNS record check. The verification flag is only cleared
    once the failure counter crosses the threshold and the alert is actually sent,
    so a transient DNS failure never disables the feature and a rate-limited alert
    never de-verifies a domain without telling the user.
    """
    if record_ok or not was_verified:
        # Nothing to warn about: the record is fine, or it was never set up so the
        # user cannot be asked to fix it.
        if failed_checks != 0:
            setattr(custom_domain, cfg.counter_field, 0)
        return

    LOG.w(
        f"{cfg.record_name} check failed for domain {custom_domain} of user {user}. "
        f"Retried {failed_checks} days",
    )
    if last_updated_at and last_updated_at > now.shift(days=-1):
        # already counted today
        return

    failed_checks += 1
    setattr(custom_domain, cfg.counter_field, failed_checks)
    setattr(custom_domain, cfg.counter_updated_at_field, now)

    if failed_checks <= config.MAX_DOMAIN_CHECKS:
        return

    if not _send_alert(custom_domain, user, domain_dns_url, provider, cfg):
        # Alert rate-limited: keep counting and retry the alert on a later run
        # instead of silently de-verifying the domain.
        LOG.w(
            "Alert for %s on domain %s was rate-limited; keeping it verified and retrying later",
            cfg.record_name,
            custom_domain,
        )
        return

    LOG.w(
        "Un-verifying %s for domain %s after %d failed checks",
        cfg.record_name,
        custom_domain,
        failed_checks,
    )
    setattr(custom_domain, cfg.verified_field, False)
    setattr(custom_domain, cfg.counter_field, 0)


def check_single_custom_domain(custom_domain: CustomDomain):
    if custom_domain.is_sl_subdomain:
        return
    if custom_domain.user.disabled:
        return
    user = custom_domain.user
    # snapshot before any mutation below, which would otherwise throw off the
    # once-a-day throttles and hide whether the records were verified beforehand
    mx_last_updated_at = custom_domain.updated_at
    dkim_last_updated_at = custom_domain.dkim_nb_failed_checks_updated_at
    dmarc_last_updated_at = custom_domain.dmarc_nb_failed_checks_updated_at
    was_dkim_verified = custom_domain.dkim_verified
    was_dmarc_verified = custom_domain.dmarc_verified

    mx_domains = get_mx_domains(custom_domain.domain)
    validator = CustomDomainValidation(
        dkim_domain=config.EMAIL_DOMAIN,
        dns_client=get_network_dns_client(),
        partner_domains=config.PARTNER_DNS_CUSTOM_DOMAINS,
        partner_domains_validation_prefixes=config.PARTNER_CUSTOM_DOMAIN_VALIDATION_PREFIXES,
    )
    expected_custom_domains = validator.get_expected_mx_records(custom_domain)
    mx_ok = is_mx_equivalent(mx_domains, expected_custom_domains)
    # read-only checks: unlike validate_dkim_records/validate_dmarc_records these
    # never flip dkim_verified/dmarc_verified nor write audit log entries
    dkim_ok = len(validator.check_dkim_records(custom_domain)) == 0
    dmarc_ok = validator.check_dmarc_record(custom_domain)

    domain_dns_url = f"{config.URL}/dashboard/domains/{custom_domain.id}/dns"
    try:
        is_proton_domain = custom_domain.partner_id == get_proton_partner().id
    except ProtonPartnerNotSetUp:
        is_proton_domain = False
    provider = "Proton" if is_proton_domain else "SimpleLogin"
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

    _check_record(
        custom_domain,
        user,
        record_ok=dkim_ok,
        was_verified=was_dkim_verified,
        failed_checks=custom_domain.dkim_nb_failed_checks,
        last_updated_at=dkim_last_updated_at,
        now=now,
        cfg=DKIM_ALERT,
        domain_dns_url=domain_dns_url,
        provider=provider,
    )

    _check_record(
        custom_domain,
        user,
        record_ok=dmarc_ok,
        was_verified=was_dmarc_verified,
        failed_checks=custom_domain.dmarc_nb_failed_checks,
        last_updated_at=dmarc_last_updated_at,
        now=now,
        cfg=DMARC_ALERT,
        domain_dns_url=domain_dns_url,
        provider=provider,
    )

    Session.commit()
