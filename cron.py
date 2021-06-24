import argparse
import asyncio
import urllib.parse
from time import sleep
from typing import List, Tuple

import arrow
import requests
from sqlalchemy import func, desc, or_

from app import s3
from app.alias_utils import nb_email_log_for_mailbox
from app.api.views.apple import verify_receipt
from app.config import (
    ADMIN_EMAIL,
    MACAPP_APPLE_API_SECRET,
    APPLE_API_SECRET,
    EMAIL_SERVERS_WITH_PRIORITY,
    URL,
    AlERT_WRONG_MX_RECORD_CUSTOM_DOMAIN,
    HIBP_API_KEYS,
    HIBP_SCAN_INTERVAL_DAYS,
)
from app.dns_utils import get_mx_domains
from app.email_utils import (
    send_email,
    send_trial_end_soon_email,
    render,
    email_can_be_used_as_mailbox,
    send_email_with_rate_control,
    normalize_reply_email,
    is_valid_email,
    get_email_domain_part,
)
from app.extensions import db
from app.log import LOG
from app.models import (
    Subscription,
    User,
    Alias,
    EmailLog,
    CustomDomain,
    Client,
    ManualSubscription,
    RefusedEmail,
    AppleSubscription,
    Mailbox,
    Monitoring,
    Contact,
    CoinbaseSubscription,
    Metric,
    TransactionalEmail,
    Bounce,
    Metric2,
    SLDomain,
    DeletedAlias,
    DomainDeletedAlias,
    Hibp,
)
from app.utils import sanitize_email
from server import create_app


def notify_trial_end():
    for user in User.query.filter(
        User.activated.is_(True), User.trial_end.isnot(None), User.lifetime.is_(False)
    ).all():
        if user.in_trial() and arrow.now().shift(
            days=3
        ) > user.trial_end >= arrow.now().shift(days=2):
            LOG.d("Send trial end email to user %s", user)
            send_trial_end_soon_email(user)


def delete_logs():
    """delete everything that are considered logs"""
    delete_refused_emails()
    delete_old_monitoring()

    for t in TransactionalEmail.query.filter(
        TransactionalEmail.created_at < arrow.now().shift(days=-7)
    ):
        TransactionalEmail.delete(t.id)

    for b in Bounce.query.filter(Bounce.created_at < arrow.now().shift(days=-7)):
        Bounce.delete(b.id)

    db.session.commit()


def delete_refused_emails():
    for refused_email in RefusedEmail.query.filter_by(deleted=False).all():
        if arrow.now().shift(days=1) > refused_email.delete_at >= arrow.now():
            LOG.d("Delete refused email %s", refused_email)
            if refused_email.path:
                s3.delete(refused_email.path)

            s3.delete(refused_email.full_report_path)

            # do not set path and full_report_path to null
            # so we can check later that the files are indeed deleted
            refused_email.deleted = True
            db.session.commit()

    LOG.d("Finish delete_refused_emails")


def notify_premium_end():
    """sent to user who has canceled their subscription and who has their subscription ending soon"""
    for sub in Subscription.query.filter_by(cancelled=True).all():
        if (
            arrow.now().shift(days=3).date()
            > sub.next_bill_date
            >= arrow.now().shift(days=2).date()
        ):
            user = sub.user
            LOG.d(f"Send subscription ending soon email to user {user}")

            send_email(
                user.email,
                f"Your subscription will end soon",
                render(
                    "transactional/subscription-end.txt",
                    user=user,
                    next_bill_date=sub.next_bill_date.strftime("%Y-%m-%d"),
                ),
                render(
                    "transactional/subscription-end.html",
                    user=user,
                    next_bill_date=sub.next_bill_date.strftime("%Y-%m-%d"),
                ),
            )


def notify_manual_sub_end():
    for manual_sub in ManualSubscription.query.all():
        need_reminder = False
        if arrow.now().shift(days=14) > manual_sub.end_at > arrow.now().shift(days=13):
            need_reminder = True
        elif arrow.now().shift(days=4) > manual_sub.end_at > arrow.now().shift(days=3):
            need_reminder = True

        if need_reminder:
            user = manual_sub.user
            LOG.debug("Remind user %s that their manual sub is ending soon", user)
            send_email(
                user.email,
                f"Your subscription will end soon",
                render(
                    "transactional/manual-subscription-end.txt",
                    user=user,
                    manual_sub=manual_sub,
                ),
                render(
                    "transactional/manual-subscription-end.html",
                    user=user,
                    manual_sub=manual_sub,
                ),
            )

    extend_subscription_url = URL + "/dashboard/coinbase_checkout"
    for coinbase_subscription in CoinbaseSubscription.query.all():
        need_reminder = False
        if (
            arrow.now().shift(days=14)
            > coinbase_subscription.end_at
            > arrow.now().shift(days=13)
        ):
            need_reminder = True
        elif (
            arrow.now().shift(days=4)
            > coinbase_subscription.end_at
            > arrow.now().shift(days=3)
        ):
            need_reminder = True

        if need_reminder:
            user = coinbase_subscription.user
            LOG.debug(
                "Remind user %s that their coinbase subscription is ending soon", user
            )
            send_email(
                user.email,
                "Your SimpleLogin subscription will end soon",
                render(
                    "transactional/coinbase/reminder-subscription.txt",
                    coinbase_subscription=coinbase_subscription,
                    extend_subscription_url=extend_subscription_url,
                ),
                render(
                    "transactional/coinbase/reminder-subscription.html",
                    coinbase_subscription=coinbase_subscription,
                    extend_subscription_url=extend_subscription_url,
                ),
            )


def poll_apple_subscription():
    """Poll Apple API to update AppleSubscription"""
    # todo: only near the end of the subscription
    for apple_sub in AppleSubscription.query.all():
        user = apple_sub.user
        verify_receipt(apple_sub.receipt_data, user, APPLE_API_SECRET)
        verify_receipt(apple_sub.receipt_data, user, MACAPP_APPLE_API_SECRET)

    LOG.d("Finish poll_apple_subscription")


def compute_metrics():
    now = arrow.now()

    Metric.create(date=now, name=Metric.NB_USER, value=User.query.count(), commit=True)
    Metric.create(
        date=now,
        name=Metric.NB_ACTIVATED_USER,
        value=User.query.filter_by(activated=True).count(),
        commit=True,
    )

    Metric.create(
        date=now,
        name=Metric.NB_REFERRED_USER,
        value=User.query.filter(User.referral_id.isnot(None)).count(),
        commit=True,
    )

    nb_referred_user_paid = 0
    for user in User.query.filter(User.referral_id.isnot(None)):
        if user.is_paid():
            nb_referred_user_paid += 1

    Metric.create(
        date=now,
        name=Metric.NB_REFERRED_USER_PAID,
        value=nb_referred_user_paid,
        commit=True,
    )

    Metric.create(
        date=now, name=Metric.NB_ALIAS, value=Alias.query.count(), commit=True
    )

    Metric.create(
        date=now,
        name=Metric.NB_BOUNCED,
        value=EmailLog.query.filter_by(bounced=True).count(),
        commit=True,
    )
    Metric.create(
        date=now,
        name=Metric.NB_SPAM,
        value=EmailLog.query.filter_by(is_spam=True).count(),
        commit=True,
    )
    Metric.create(
        date=now,
        name=Metric.NB_REPLY,
        value=EmailLog.query.filter_by(is_reply=True).count(),
        commit=True,
    )
    Metric.create(
        date=now,
        name=Metric.NB_BLOCK,
        value=EmailLog.query.filter_by(blocked=True).count(),
        commit=True,
    )
    Metric.create(
        date=now,
        name=Metric.NB_FORWARD,
        value=EmailLog.query.filter_by(
            bounced=False, is_spam=False, is_reply=False, blocked=False
        ).count(),
        commit=True,
    )

    Metric.create(
        date=now,
        name=Metric.NB_PREMIUM,
        value=Subscription.query.filter(Subscription.cancelled.is_(False)).count(),
        commit=True,
    )

    Metric.create(
        date=now,
        name=Metric.NB_CANCELLED_PREMIUM,
        value=Subscription.query.filter(Subscription.cancelled.is_(True)).count(),
        commit=True,
    )

    Metric.create(
        date=now,
        name=Metric.NB_APPLE_PREMIUM,
        value=AppleSubscription.query.count(),
        commit=True,
    )

    Metric.create(
        date=now,
        name=Metric.NB_MANUAL_PREMIUM,
        value=ManualSubscription.query.filter(
            ManualSubscription.end_at > now,
            ManualSubscription.is_giveaway.is_(False),
        ).count(),
        commit=True,
    )

    Metric.create(
        date=now,
        name=Metric.NB_COINBASE_PREMIUM,
        value=CoinbaseSubscription.query.filter(
            CoinbaseSubscription.end_at > now
        ).count(),
        commit=True,
    )

    Metric.create(
        date=now,
        name=Metric.NB_VERIFIED_CUSTOM_DOMAIN,
        value=CustomDomain.query.filter_by(verified=True).count(),
        commit=True,
    )

    Metric.create(
        date=now,
        name=Metric.NB_APP,
        value=Client.query.count(),
        commit=True,
    )


def compute_metric2() -> Metric2:
    now = arrow.now()
    nb_referred_user_paid = 0
    for user in User.query.filter(User.referral_id.isnot(None)):
        if user.is_paid():
            nb_referred_user_paid += 1

    return Metric2.create(
        date=now,
        # user stats
        nb_user=User.query.count(),
        nb_activated_user=User.query.filter_by(activated=True).count(),
        # subscription stats
        nb_premium=Subscription.query.filter(Subscription.cancelled.is_(False)).count(),
        nb_cancelled_premium=Subscription.query.filter(
            Subscription.cancelled.is_(True)
        ).count(),
        # todo: filter by expires_date > now
        nb_apple_premium=AppleSubscription.query.count(),
        nb_manual_premium=ManualSubscription.query.filter(
            ManualSubscription.end_at > now,
            ManualSubscription.is_giveaway.is_(False),
        ).count(),
        nb_coinbase_premium=CoinbaseSubscription.query.filter(
            CoinbaseSubscription.end_at > now
        ).count(),
        # referral stats
        nb_referred_user=User.query.filter(User.referral_id.isnot(None)).count(),
        nb_referred_user_paid=nb_referred_user_paid,
        nb_alias=Alias.query.count(),
        # email log stats
        nb_bounced=EmailLog.query.filter_by(bounced=True).count(),
        nb_spam=EmailLog.query.filter_by(is_spam=True).count(),
        nb_reply=EmailLog.query.filter_by(is_reply=True).count(),
        nb_forward=EmailLog.query.filter_by(
            bounced=False, is_spam=False, is_reply=False, blocked=False
        ).count(),
        nb_block=EmailLog.query.filter_by(blocked=True).count(),
        nb_verified_custom_domain=CustomDomain.query.filter_by(verified=True).count(),
        nb_app=Client.query.count(),
        commit=True,
    )


def increase_percent(old, new) -> str:
    if old == 0:
        return "N/A"

    increase = (new - old) / old * 100
    return f"{increase:.1f}%. Delta: {new-old}"


def bounce_report() -> List[Tuple[str, int]]:
    """return the accounts that have most bounces, e.g.
    (email1, 30)
    (email2, 20)

    Produce this query

    ```
    SELECT
        count(*) AS c,
        users.email
    FROM
        email_log,
        users
    WHERE
        email_log.user_id = users.id
        AND email_log.created_at > '2021-3-20'
        and email_log.bounced = true
    GROUP BY
        users.email
    ORDER BY
        c DESC;
    ```

    """
    min_dt = arrow.now().shift(days=-1)
    query = (
        db.session.query(User.email, func.count(EmailLog.id).label("count"))
        .join(EmailLog, EmailLog.user_id == User.id)
        .filter(EmailLog.bounced, EmailLog.created_at > min_dt)
        .group_by(User.email)
        .having(func.count(EmailLog.id) > 5)
        .order_by(desc("count"))
    )

    res = []
    for email, count in query:
        res.append((email, count))

    return res


def alias_creation_report() -> List[Tuple[str, int]]:
    """return the accounts that have created most aliases in the last 7 days, e.g.
    (email1, 2021-3-21, 30)
    (email2, 2021-3-20, 20)

    Produce this query

    ```
    SELECT
        count(*) AS c,
        users.email,
        date(alias.created_at) AS d
    FROM
        alias,
        users
    WHERE
        alias.user_id = users.id
        AND alias.created_at > '2021-3-22'
    GROUP BY
        users.email,
        d
    HAVING
        count(*) > 50
    ORDER BY
        c DESC;
    ```

    """
    min_dt = arrow.now().shift(days=-7)
    query = (
        db.session.query(
            User.email,
            func.count(Alias.id).label("count"),
            func.date(Alias.created_at).label("date"),
        )
        .join(Alias, Alias.user_id == User.id)
        .filter(Alias.created_at > min_dt)
        .group_by(User.email, "date")
        .having(func.count(Alias.id) > 50)
        .order_by(desc("count"))
    )

    res = []
    for email, count, date in query:
        res.append((email, count, date))

    return res


def stats():
    """send admin stats everyday"""
    if not ADMIN_EMAIL:
        # nothing to do
        return

    # todo: remove metrics1
    compute_metrics()

    stats_today = compute_metric2()
    stats_yesterday = (
        Metric2.query.filter(Metric2.date < stats_today.date)
        .order_by(Metric2.date.desc())
        .first()
    )

    nb_user_increase = increase_percent(stats_yesterday.nb_user, stats_today.nb_user)
    nb_alias_increase = increase_percent(stats_yesterday.nb_alias, stats_today.nb_alias)
    nb_forward_increase = increase_percent(
        stats_yesterday.nb_forward, stats_today.nb_forward
    )

    today = arrow.now().format()

    html = f"""
Stats for {today} <br>

nb_user: {stats_today.nb_user} - {increase_percent(stats_yesterday.nb_user, stats_today.nb_user)}  <br>
nb_premium: {stats_today.nb_premium} - {increase_percent(stats_yesterday.nb_premium, stats_today.nb_premium)}  <br>
nb_cancelled_premium: {stats_today.nb_cancelled_premium} - {increase_percent(stats_yesterday.nb_cancelled_premium, stats_today.nb_cancelled_premium)}  <br>
nb_apple_premium: {stats_today.nb_apple_premium} - {increase_percent(stats_yesterday.nb_apple_premium, stats_today.nb_apple_premium)}  <br>
nb_manual_premium: {stats_today.nb_manual_premium} - {increase_percent(stats_yesterday.nb_manual_premium, stats_today.nb_manual_premium)}  <br>
nb_coinbase_premium: {stats_today.nb_coinbase_premium} - {increase_percent(stats_yesterday.nb_coinbase_premium, stats_today.nb_coinbase_premium)}  <br>
nb_alias: {stats_today.nb_alias} - {increase_percent(stats_yesterday.nb_alias, stats_today.nb_alias)}  <br>

nb_forward: {stats_today.nb_forward} - {increase_percent(stats_yesterday.nb_forward, stats_today.nb_forward)}  <br>
nb_reply: {stats_today.nb_reply} - {increase_percent(stats_yesterday.nb_reply, stats_today.nb_reply)}  <br>
nb_block: {stats_today.nb_block} - {increase_percent(stats_yesterday.nb_block, stats_today.nb_block)}  <br>
nb_bounced: {stats_today.nb_bounced} - {increase_percent(stats_yesterday.nb_bounced, stats_today.nb_bounced)}  <br>
nb_spam: {stats_today.nb_spam} - {increase_percent(stats_yesterday.nb_spam, stats_today.nb_spam)}  <br>

nb_custom_domain: {stats_today.nb_verified_custom_domain} - {increase_percent(stats_yesterday.nb_verified_custom_domain, stats_today.nb_verified_custom_domain)}  <br>
nb_app: {stats_today.nb_app} - {increase_percent(stats_yesterday.nb_app, stats_today.nb_app)}  <br>
nb_referred_user: {stats_today.nb_referred_user} - {increase_percent(stats_yesterday.nb_referred_user, stats_today.nb_referred_user)}  <br>
nb_referred_user_upgrade: {stats_today.nb_referred_user_paid} - {increase_percent(stats_yesterday.nb_referred_user_paid, stats_today.nb_referred_user_paid)}  <br>
    """

    html += f"""<br>
    Bounce report: <br>
    """

    for email, bounces in bounce_report():
        html += f"{email}: {bounces} <br>"

    html += f"""<br><br>
    Alias creation report: <br>
    """

    for email, nb_alias, date in alias_creation_report():
        html += f"{email}, {date}: {nb_alias} <br>"

    LOG.d("report email: %s", html)

    send_email(
        ADMIN_EMAIL,
        subject=f"SimpleLogin Stats for {today}, {nb_user_increase} users, {nb_alias_increase} aliases, {nb_forward_increase} forwards",
        plaintext="",
        html=html,
    )


def migrate_domain_trash():
    """Move aliases from global trash to domain trash if applicable"""
    for deleted_alias in DeletedAlias.query.all():
        alias_domain = get_email_domain_part(deleted_alias.email)
        if not SLDomain.get_by(domain=alias_domain):
            custom_domain = CustomDomain.get_by(domain=alias_domain)
            if custom_domain:
                LOG.exception(
                    "move %s to domain %s trash", deleted_alias, custom_domain
                )
                db.session.add(
                    DomainDeletedAlias(
                        user_id=custom_domain.user_id,
                        email=deleted_alias.email,
                        domain_id=custom_domain.id,
                        created_at=deleted_alias.created_at,
                    )
                )
                DeletedAlias.delete(deleted_alias.id)

    db.session.commit()


def set_custom_domain_for_alias():
    """Go through all aliases and make sure custom_domain is correctly set"""
    sl_domains = [sl_domain.domain for sl_domain in SLDomain.query.all()]
    for alias in Alias.query.filter(Alias.custom_domain_id.is_(None)):
        if (
            not any(alias.email.endswith(f"@{sl_domain}") for sl_domain in sl_domains)
            and not alias.custom_domain_id
        ):
            alias_domain = get_email_domain_part(alias.email)
            custom_domain = CustomDomain.get_by(domain=alias_domain)
            if custom_domain:
                LOG.exception("set %s for %s", custom_domain, alias)
                alias.custom_domain_id = custom_domain.id
            else:  # phantom domain
                LOG.d("phantom domain %s %s %s", alias.user, alias, alias.enabled)

    db.session.commit()


def sanity_check():
    """
    #TODO: investigate why DNS sometimes not working
    Different sanity checks
    - detect if there's mailbox that's using a invalid domain
    """
    mailbox_ids = (
        db.session.query(Mailbox.id)
        .filter(Mailbox.verified.is_(True), Mailbox.disabled.is_(False))
        .all()
    )
    mailbox_ids = [e[0] for e in mailbox_ids]

    # iterate over id instead of mailbox directly
    # as a mailbox can be deleted during the sleep time
    for mailbox_id in mailbox_ids:
        mailbox = Mailbox.get(mailbox_id)
        # a mailbox has been deleted
        if not mailbox:
            continue

        # hack to not query DNS too often
        sleep(1)

        if not email_can_be_used_as_mailbox(mailbox.email):
            mailbox.nb_failed_checks += 1
            nb_email_log = nb_email_log_for_mailbox(mailbox)

            # send a warning
            if mailbox.nb_failed_checks == 5:
                if mailbox.user.email != mailbox.email:
                    send_email(
                        mailbox.user.email,
                        f"Mailbox {mailbox.email} is disabled",
                        render(
                            "transactional/disable-mailbox-warning.txt", mailbox=mailbox
                        ),
                        render(
                            "transactional/disable-mailbox-warning.html",
                            mailbox=mailbox,
                        ),
                    )

            # alert if too much fail and nb_email_log > 100
            if mailbox.nb_failed_checks > 10 and nb_email_log > 100:
                mailbox.disabled = True

                if mailbox.user.email != mailbox.email:
                    send_email(
                        mailbox.user.email,
                        f"Mailbox {mailbox.email} is disabled",
                        render("transactional/disable-mailbox.txt", mailbox=mailbox),
                        render("transactional/disable-mailbox.html", mailbox=mailbox),
                    )

            LOG.warning(
                "issue with mailbox %s domain. #alias %s, nb email log %s",
                mailbox,
                mailbox.nb_alias(),
                nb_email_log,
            )
        else:  # reset nb check
            mailbox.nb_failed_checks = 0

        db.session.commit()

    for user in User.filter_by(activated=True).all():
        if sanitize_email(user.email) != user.email:
            LOG.exception("%s does not have sanitized email", user)

    for alias in Alias.query.all():
        if sanitize_email(alias.email) != alias.email:
            LOG.exception("Alias %s email not sanitized", alias)

        if alias.name and "\n" in alias.name:
            alias.name = alias.name.replace("\n", "")
            db.session.commit()
            LOG.exception("Alias %s name contains linebreak %s", alias, alias.name)

    contact_email_sanity_date = arrow.get("2021-01-12")
    for contact in Contact.query.all():
        if sanitize_email(contact.reply_email) != contact.reply_email:
            LOG.exception("Contact %s reply-email not sanitized", contact)

        if (
            sanitize_email(contact.website_email) != contact.website_email
            and contact.created_at > contact_email_sanity_date
        ):
            LOG.exception("Contact %s website-email not sanitized", contact)

        if not contact.invalid_email and not is_valid_email(contact.website_email):
            LOG.exception("%s invalid email", contact)
            contact.invalid_email = True
            db.session.commit()

    for mailbox in Mailbox.query.all():
        if sanitize_email(mailbox.email) != mailbox.email:
            LOG.exception("Mailbox %s address not sanitized", mailbox)

    for contact in Contact.query.all():
        if normalize_reply_email(contact.reply_email) != contact.reply_email:
            LOG.exception(
                "Contact %s reply email is not normalized %s",
                contact,
                contact.reply_email,
            )

    for domain in CustomDomain.query.all():
        if domain.name and "\n" in domain.name:
            LOG.exception("Domain %s name contain linebreak %s", domain, domain.name)

    migrate_domain_trash()
    set_custom_domain_for_alias()

    LOG.d("Finish sanity check")


def check_custom_domain():
    LOG.d("Check verified domain for DNS issues")

    for custom_domain in CustomDomain.query.filter_by(
        verified=True
    ):  # type: CustomDomain
        mx_domains = get_mx_domains(custom_domain.domain)

        if sorted(mx_domains) != sorted(EMAIL_SERVERS_WITH_PRIORITY):
            user = custom_domain.user
            LOG.warning(
                "The MX record is not correctly set for %s %s %s",
                custom_domain,
                user,
                mx_domains,
            )

            custom_domain.nb_failed_checks += 1

            # send alert if fail for 5 consecutive days
            if custom_domain.nb_failed_checks > 5:
                domain_dns_url = f"{URL}/dashboard/domains/{custom_domain.id}/dns"
                LOG.warning(
                    "Alert domain MX check fails %s about %s", user, custom_domain
                )
                send_email_with_rate_control(
                    user,
                    AlERT_WRONG_MX_RECORD_CUSTOM_DOMAIN,
                    user.email,
                    f"Please update {custom_domain.domain} DNS on SimpleLogin",
                    render(
                        "transactional/custom-domain-dns-issue.txt",
                        custom_domain=custom_domain,
                        domain_dns_url=domain_dns_url,
                    ),
                    render(
                        "transactional/custom-domain-dns-issue.html",
                        custom_domain=custom_domain,
                        domain_dns_url=domain_dns_url,
                    ),
                    max_nb_alert=1,
                    nb_day=30,
                )
                # reset checks
                custom_domain.nb_failed_checks = 0
        else:
            # reset checks
            custom_domain.nb_failed_checks = 0

        db.session.commit()


def delete_old_monitoring():
    """
    Delete old monitoring records
    """
    max_time = arrow.now().shift(days=-30)
    nb_row = Monitoring.query.filter(Monitoring.created_at < max_time).delete()
    db.session.commit()
    LOG.d("delete monitoring records older than %s, nb row %s", max_time, nb_row)


async def _hibp_check(api_key, queue):
    """
    Uses a single API key to check the queue as fast as possible.

    This function to be ran simultaneously (multiple _hibp_check functions with different keys on the same queue) to make maximum use of multiple API keys.
    """
    while True:
        try:
            alias_id = queue.get_nowait()
        except asyncio.QueueEmpty:
            return

        alias = Alias.get(alias_id)
        # an alias can be deleted in the meantime
        if not alias:
            return

        LOG.d("Checking HIBP for %s", alias)

        request_headers = {
            "user-agent": "SimpleLogin",
            "hibp-api-key": api_key,
        }
        r = requests.get(
            f"https://haveibeenpwned.com/api/v3/breachedaccount/{urllib.parse.quote(alias.email)}",
            headers=request_headers,
        )

        if r.status_code == 200:
            # Breaches found
            alias.hibp_breaches = [
                Hibp.get_by(name=entry["Name"]) for entry in r.json()
            ]
            if len(alias.hibp_breaches) > 0:
                LOG.w("%s appears in HIBP breaches %s", alias, alias.hibp_breaches)
        elif r.status_code == 404:
            # No breaches found
            alias.hibp_breaches = []
        elif r.status_code == 429:
            # rate limited
            LOG.w("HIBP rate limited, check alias %s in the next run", alias)
            await asyncio.sleep(1.6)
            return
        elif r.status_code > 500:
            LOG.w("HIBP server 5** error %s", r.status_code)
            return
        else:
            LOG.error(
                "An error occured while checking alias %s: %s - %s",
                alias,
                r.status_code,
                r.text,
            )
            return

        alias.hibp_last_check = arrow.utcnow()
        db.session.add(alias)
        db.session.commit()

        LOG.d("Updated breaches info for %s", alias)

        await asyncio.sleep(1.6)


async def check_hibp():
    """
    Check all aliases on the HIBP (Have I Been Pwned) API
    """
    LOG.d("Checking HIBP API for aliases in breaches")

    if len(HIBP_API_KEYS) == 0:
        LOG.exception("No HIBP API keys")
        return

    LOG.d("Updating list of known breaches")
    r = requests.get("https://haveibeenpwned.com/api/v3/breaches")
    for entry in r.json():
        Hibp.get_or_create(name=entry["Name"])

    db.session.commit()
    LOG.d("Updated list of known breaches")

    LOG.d("Preparing list of aliases to check")
    queue = asyncio.Queue()
    max_date = arrow.now().shift(days=-HIBP_SCAN_INTERVAL_DAYS)
    for alias in (
        Alias.query.filter(
            or_(Alias.hibp_last_check.is_(None), Alias.hibp_last_check < max_date)
        )
        .filter(Alias.enabled)
        .order_by(Alias.hibp_last_check.asc())
        .all()
    ):
        await queue.put(alias.id)

    LOG.d("Need to check about %s aliases", queue.qsize())

    # Start one checking process per API key
    # Each checking process will take one alias from the queue, get the info
    # and then sleep for 1.5 seconds (due to HIBP API request limits)
    checkers = []
    for i in range(len(HIBP_API_KEYS)):
        checker = asyncio.create_task(
            _hibp_check(
                HIBP_API_KEYS[i],
                queue,
            )
        )
        checkers.append(checker)

    # Wait until all checking processes are done
    for checker in checkers:
        await checker

    LOG.d("Done checking HIBP API for aliases in breaches")


if __name__ == "__main__":
    LOG.d("Start running cronjob")
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-j",
        "--job",
        help="Choose a cron job to run",
        type=str,
        choices=[
            "stats",
            "notify_trial_end",
            "notify_manual_subscription_end",
            "notify_premium_end",
            "delete_logs",
            "poll_apple_subscription",
            "sanity_check",
            "delete_old_monitoring",
            "check_custom_domain",
            "check_hibp",
        ],
    )
    args = parser.parse_args()

    app = create_app()

    with app.app_context():
        if args.job == "stats":
            LOG.d("Compute Stats")
            stats()
        elif args.job == "notify_trial_end":
            LOG.d("Notify users with trial ending soon")
            notify_trial_end()
        elif args.job == "notify_manual_subscription_end":
            LOG.d("Notify users with manual subscription ending soon")
            notify_manual_sub_end()
        elif args.job == "notify_premium_end":
            LOG.d("Notify users with premium ending soon")
            notify_premium_end()
        elif args.job == "delete_logs":
            LOG.d("Deleted Logs")
            delete_logs()
        elif args.job == "poll_apple_subscription":
            LOG.d("Poll Apple Subscriptions")
            poll_apple_subscription()
        elif args.job == "sanity_check":
            LOG.d("Check data consistency")
            sanity_check()
        elif args.job == "delete_old_monitoring":
            LOG.d("Delete old monitoring records")
            delete_old_monitoring()
        elif args.job == "check_custom_domain":
            LOG.d("Check custom domain")
            check_custom_domain()
        elif args.job == "check_hibp":
            LOG.d("Check HIBP")
            asyncio.run(check_hibp())
