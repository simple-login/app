import arrow
from sqlalchemy.orm.exc import ObjectDeletedError

from app import config
from app.custom_domain_validation import CustomDomainValidation, is_mx_equivalent
from app.db import Session
from app.dns_utils import get_mx_domains
from app.email_utils import send_email_with_rate_control, render
from app.log import LOG
from app.models import CustomDomain, Alias


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


def check_single_custom_domain(custom_domain: CustomDomain):
    if custom_domain.user.disabled:
        return
    mx_domains = get_mx_domains(custom_domain.domain)
    validator = CustomDomainValidation(
        dkim_domain=config.EMAIL_DOMAIN,
        partner_domains=config.PARTNER_DNS_CUSTOM_DOMAINS,
        partner_domains_validation_prefixes=config.PARTNER_CUSTOM_DOMAIN_VALIDATION_PREFIXES,
    )
    expected_custom_domains = validator.get_expected_mx_records(custom_domain)
    if not is_mx_equivalent(mx_domains, expected_custom_domains):
        user = custom_domain.user
        LOG.w(
            "The MX record is not correctly set for %s %s %s",
            custom_domain,
            user,
            mx_domains,
        )

        custom_domain.nb_failed_checks += 1

        # send alert if fail for 5 consecutive days
        if custom_domain.nb_failed_checks > 5:
            domain_dns_url = f"{config.URL}/dashboard/domains/{custom_domain.id}/dns"
            LOG.w("Alert domain MX check fails %s about %s", user, custom_domain)
            send_email_with_rate_control(
                user,
                config.AlERT_WRONG_MX_RECORD_CUSTOM_DOMAIN,
                user.email,
                f"Please update {custom_domain.domain} DNS on SimpleLogin",
                render(
                    "transactional/custom-domain-dns-issue.txt.jinja2",
                    user=user,
                    custom_domain=custom_domain,
                    domain_dns_url=domain_dns_url,
                ),
                max_nb_alert=1,
                nb_day=30,
                retries=3,
            )
            # reset checks
            custom_domain.nb_failed_checks = 0
    else:
        # reset checks
        custom_domain.nb_failed_checks = 0
    Session.commit()
