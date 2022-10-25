import argparse
import asyncio
import urllib.parse
from typing import List, Tuple

import arrow
import requests
from sqlalchemy import func, desc, or_
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import ObjectDeletedError
from sqlalchemy.sql import Insert

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
    MONITORING_EMAIL,
)
from app.db import Session
from app.dns_utils import get_mx_domains, is_mx_equivalent
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
from app.errors import ProtonPartnerNotSetUp
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
    TransactionalEmail,
    Bounce,
    Metric2,
    SLDomain,
    DeletedAlias,
    DomainDeletedAlias,
    Hibp,
    HibpNotifiedAlias,
    Directory,
    DeletedDirectory,
    DeletedSubdomain,
    PartnerSubscription,
    PartnerUser,
    ApiToCookieToken,
)
from app.pgp_utils import load_public_key_and_check, PGPException
from app.proton.utils import get_proton_partner
from app.utils import sanitize_email
from server import create_light_app


def notify_trial_end():
    for user in User.filter(
        User.activated.is_(True), User.trial_end.isnot(None), User.lifetime.is_(False)
    ).all():
        try:
            if user.in_trial() and arrow.now().shift(
                days=3
            ) > user.trial_end >= arrow.now().shift(days=2):
                LOG.d("Send trial end email to user %s", user)
                send_trial_end_soon_email(user)
        # happens if user has been deleted in the meantime
        except ObjectDeletedError:
            LOG.i("user has been deleted")


def delete_logs():
    """delete everything that are considered logs"""
    delete_refused_emails()
    delete_old_monitoring()

    for t in TransactionalEmail.filter(
        TransactionalEmail.created_at < arrow.now().shift(days=-7)
    ):
        TransactionalEmail.delete(t.id)

    for b in Bounce.filter(Bounce.created_at < arrow.now().shift(days=-7)):
        Bounce.delete(b.id)

    Session.commit()

    LOG.d("Delete EmailLog older than 2 weeks")

    max_dt = arrow.now().shift(weeks=-2)
    nb_deleted = EmailLog.filter(EmailLog.created_at < max_dt).delete()
    Session.commit()

    LOG.i("Delete %s email logs", nb_deleted)


def delete_refused_emails():
    for refused_email in RefusedEmail.filter_by(deleted=False).all():
        if arrow.now().shift(days=1) > refused_email.delete_at >= arrow.now():
            LOG.d("Delete refused email %s", refused_email)
            if refused_email.path:
                s3.delete(refused_email.path)

            s3.delete(refused_email.full_report_path)

            # do not set path and full_report_path to null
            # so we can check later that the files are indeed deleted
            refused_email.delete_at = arrow.now()
            refused_email.deleted = True
            Session.commit()

    LOG.d("Finish delete_refused_emails")


def notify_premium_end():
    """sent to user who has canceled their subscription and who has their subscription ending soon"""
    for sub in Subscription.filter_by(cancelled=True).all():
        if (
            arrow.now().shift(days=3).date()
            > sub.next_bill_date
            >= arrow.now().shift(days=2).date()
        ):
            user = sub.user

            if user.lifetime:
                continue

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
                retries=3,
            )


def notify_manual_sub_end():
    for manual_sub in ManualSubscription.all():
        manual_sub: ManualSubscription
        need_reminder = False
        if arrow.now().shift(days=14) > manual_sub.end_at > arrow.now().shift(days=13):
            need_reminder = True
        elif arrow.now().shift(days=4) > manual_sub.end_at > arrow.now().shift(days=3):
            need_reminder = True

        user = manual_sub.user
        if user.lifetime:
            LOG.d("%s has a lifetime licence", user)
            continue

        paddle_sub: Subscription = user.get_paddle_subscription()
        if paddle_sub and not paddle_sub.cancelled:
            LOG.d("%s has an active Paddle subscription", user)
            continue

        if need_reminder:
            # user can have a (free) manual subscription but has taken a paid subscription via
            # Paddle, Coinbase or Apple since then
            if manual_sub.is_giveaway:
                if user.get_paddle_subscription():
                    LOG.d("%s has a active Paddle subscription", user)
                    continue

                coinbase_subscription: CoinbaseSubscription = (
                    CoinbaseSubscription.get_by(user_id=user.id)
                )
                if coinbase_subscription and coinbase_subscription.is_active():
                    LOG.d("%s has a active Coinbase subscription", user)
                    continue

                apple_sub: AppleSubscription = AppleSubscription.get_by(user_id=user.id)
                if apple_sub and apple_sub.is_valid():
                    LOG.d("%s has a active Apple subscription", user)
                    continue

            LOG.d("Remind user %s that their manual sub is ending soon", user)
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
                retries=3,
            )

    extend_subscription_url = URL + "/dashboard/coinbase_checkout"
    for coinbase_subscription in CoinbaseSubscription.all():
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
            if user.lifetime:
                continue

            LOG.d(
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
                retries=3,
            )


def poll_apple_subscription():
    """Poll Apple API to update AppleSubscription"""
    # todo: only near the end of the subscription
    for apple_sub in AppleSubscription.all():
        if not apple_sub.product_id:
            LOG.d("Ignore %s", apple_sub)
            continue

        user = apple_sub.user
        if "io.simplelogin.macapp.subscription" in apple_sub.product_id:
            verify_receipt(apple_sub.receipt_data, user, MACAPP_APPLE_API_SECRET)
        else:
            verify_receipt(apple_sub.receipt_data, user, APPLE_API_SECRET)

    LOG.d("Finish poll_apple_subscription")


def compute_metric2() -> Metric2:
    now = arrow.now()
    _24h_ago = now.shift(days=-1)

    nb_referred_user_paid = 0
    for user in User.filter(User.referral_id.isnot(None)):
        if user.is_paid():
            nb_referred_user_paid += 1

    # compute nb_proton_premium, nb_proton_user
    nb_proton_premium = nb_proton_user = 0
    try:
        proton_partner = get_proton_partner()
        nb_proton_premium = (
            Session.query(PartnerSubscription, PartnerUser)
            .filter(
                PartnerSubscription.partner_user_id == PartnerUser.id,
                PartnerUser.partner_id == proton_partner.id,
                PartnerSubscription.end_at > now,
            )
            .count()
        )
        nb_proton_user = (
            Session.query(PartnerUser)
            .filter(
                PartnerUser.partner_id == proton_partner.id,
            )
            .count()
        )
    except ProtonPartnerNotSetUp:
        LOG.d("Proton partner not set up")

    return Metric2.create(
        date=now,
        # user stats
        nb_user=User.count(),
        nb_activated_user=User.filter_by(activated=True).count(),
        nb_proton_user=nb_proton_user,
        # subscription stats
        nb_premium=Subscription.filter(Subscription.cancelled.is_(False)).count(),
        nb_cancelled_premium=Subscription.filter(
            Subscription.cancelled.is_(True)
        ).count(),
        # todo: filter by expires_date > now
        nb_apple_premium=AppleSubscription.count(),
        nb_manual_premium=ManualSubscription.filter(
            ManualSubscription.end_at > now,
            ManualSubscription.is_giveaway.is_(False),
        ).count(),
        nb_coinbase_premium=CoinbaseSubscription.filter(
            CoinbaseSubscription.end_at > now
        ).count(),
        nb_proton_premium=nb_proton_premium,
        # referral stats
        nb_referred_user=User.filter(User.referral_id.isnot(None)).count(),
        nb_referred_user_paid=nb_referred_user_paid,
        nb_alias=Alias.count(),
        # email log stats
        nb_forward_last_24h=EmailLog.filter(EmailLog.created_at > _24h_ago)
        .filter_by(bounced=False, is_spam=False, is_reply=False, blocked=False)
        .count(),
        nb_bounced_last_24h=EmailLog.filter(EmailLog.created_at > _24h_ago)
        .filter_by(bounced=True)
        .count(),
        nb_total_bounced_last_24h=Bounce.filter(Bounce.created_at > _24h_ago).count(),
        nb_reply_last_24h=EmailLog.filter(EmailLog.created_at > _24h_ago)
        .filter_by(is_reply=True)
        .count(),
        nb_block_last_24h=EmailLog.filter(EmailLog.created_at > _24h_ago)
        .filter_by(blocked=True)
        .count(),
        # other stats
        nb_verified_custom_domain=CustomDomain.filter_by(verified=True).count(),
        nb_subdomain=CustomDomain.filter_by(is_sl_subdomain=True).count(),
        nb_directory=Directory.count(),
        nb_deleted_directory=DeletedDirectory.count(),
        nb_deleted_subdomain=DeletedSubdomain.count(),
        nb_app=Client.count(),
        commit=True,
    )


def increase_percent(old, new) -> str:
    if old == 0:
        return "N/A"

    if not old or not new:
        return "N/A"

    increase = (new - old) / old * 100
    return f"{increase:.1f}%. Delta: {new - old}"


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
        Session.query(User.email, func.count(EmailLog.id).label("count"))
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


def all_bounce_report() -> str:
    """
    Return a report for all mailboxes that have most bounces. Using this query to get mailboxes that have bounces.
    For each mailbox in the list, return the first bounce info.

    ```
    SELECT
        email,
        count(*) AS nb_bounce
    FROM
        bounce
    WHERE
        created_at > '2021-10-16'
    GROUP BY
        email
    ORDER BY
        nb_bounce DESC
    ```

    """
    res = ""
    min_dt = arrow.now().shift(days=-1)
    query = (
        Session.query(Bounce.email, func.count(Bounce.id).label("nb_bounce"))
        .filter(Bounce.created_at > min_dt)
        .group_by(Bounce.email)
        # not return mailboxes that have too little bounces
        .having(func.count(Bounce.id) > 3)
        .order_by(desc("nb_bounce"))
    )

    for email, count in query:
        res += f"{email}: {count} bounces. "
        most_recent: Bounce = (
            Bounce.filter(Bounce.email == email)
            .order_by(Bounce.created_at.desc())
            .first()
        )
        # most_recent.info can be very verbose
        res += f"Most recent cause: \n{most_recent.info[:1000] if most_recent.info else 'N/A'}"
        res += "\n----\n"

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
        Session.query(
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
        LOG.w("ADMIN_EMAIL not set, nothing to do")
        return

    stats_today = compute_metric2()
    stats_yesterday = (
        Metric2.filter(Metric2.date < stats_today.date)
        .order_by(Metric2.date.desc())
        .first()
    )

    today = arrow.now().format()

    growth_stats = f"""
Growth Stats for {today}

nb_user: {stats_today.nb_user} - {increase_percent(stats_yesterday.nb_user, stats_today.nb_user)}
nb_proton_user: {stats_today.nb_proton_user} - {increase_percent(stats_yesterday.nb_proton_user, stats_today.nb_proton_user)}
nb_premium: {stats_today.nb_premium} - {increase_percent(stats_yesterday.nb_premium, stats_today.nb_premium)}
nb_cancelled_premium: {stats_today.nb_cancelled_premium} - {increase_percent(stats_yesterday.nb_cancelled_premium, stats_today.nb_cancelled_premium)}
nb_apple_premium: {stats_today.nb_apple_premium} - {increase_percent(stats_yesterday.nb_apple_premium, stats_today.nb_apple_premium)}
nb_manual_premium: {stats_today.nb_manual_premium} - {increase_percent(stats_yesterday.nb_manual_premium, stats_today.nb_manual_premium)}
nb_coinbase_premium: {stats_today.nb_coinbase_premium} - {increase_percent(stats_yesterday.nb_coinbase_premium, stats_today.nb_coinbase_premium)}
nb_proton_premium: {stats_today.nb_proton_premium} - {increase_percent(stats_yesterday.nb_proton_premium, stats_today.nb_proton_premium)}
nb_alias: {stats_today.nb_alias} - {increase_percent(stats_yesterday.nb_alias, stats_today.nb_alias)}

nb_forward_last_24h: {stats_today.nb_forward_last_24h} - {increase_percent(stats_yesterday.nb_forward_last_24h, stats_today.nb_forward_last_24h)}
nb_reply_last_24h: {stats_today.nb_reply_last_24h} - {increase_percent(stats_yesterday.nb_reply_last_24h, stats_today.nb_reply_last_24h)}
nb_block_last_24h: {stats_today.nb_block_last_24h} - {increase_percent(stats_yesterday.nb_block_last_24h, stats_today.nb_block_last_24h)}
nb_bounced_last_24h: {stats_today.nb_bounced_last_24h} - {increase_percent(stats_yesterday.nb_bounced_last_24h, stats_today.nb_bounced_last_24h)}

nb_custom_domain: {stats_today.nb_verified_custom_domain} - {increase_percent(stats_yesterday.nb_verified_custom_domain, stats_today.nb_verified_custom_domain)}
nb_subdomain: {stats_today.nb_subdomain} - {increase_percent(stats_yesterday.nb_subdomain, stats_today.nb_subdomain)}
nb_directory: {stats_today.nb_directory} - {increase_percent(stats_yesterday.nb_directory, stats_today.nb_directory)}
nb_deleted_directory: {stats_today.nb_deleted_directory} - {increase_percent(stats_yesterday.nb_deleted_directory, stats_today.nb_deleted_directory)}
nb_deleted_subdomain: {stats_today.nb_deleted_subdomain} - {increase_percent(stats_yesterday.nb_deleted_subdomain, stats_today.nb_deleted_subdomain)}

nb_app: {stats_today.nb_app} - {increase_percent(stats_yesterday.nb_app, stats_today.nb_app)}
nb_referred_user: {stats_today.nb_referred_user} - {increase_percent(stats_yesterday.nb_referred_user, stats_today.nb_referred_user)}
nb_referred_user_upgrade: {stats_today.nb_referred_user_paid} - {increase_percent(stats_yesterday.nb_referred_user_paid, stats_today.nb_referred_user_paid)}
    """

    LOG.d("growth_stats email: %s", growth_stats)

    send_email(
        ADMIN_EMAIL,
        subject=f"SimpleLogin Growth Stats for {today}",
        plaintext=growth_stats,
        retries=3,
    )

    monitoring_report = f"""
Monitoring Stats for {today}

nb_alias: {stats_today.nb_alias} - {increase_percent(stats_yesterday.nb_alias, stats_today.nb_alias)}

nb_forward_last_24h: {stats_today.nb_forward_last_24h} - {increase_percent(stats_yesterday.nb_forward_last_24h, stats_today.nb_forward_last_24h)}
nb_reply_last_24h: {stats_today.nb_reply_last_24h} - {increase_percent(stats_yesterday.nb_reply_last_24h, stats_today.nb_reply_last_24h)}
nb_block_last_24h: {stats_today.nb_block_last_24h} - {increase_percent(stats_yesterday.nb_block_last_24h, stats_today.nb_block_last_24h)}
nb_bounced_last_24h: {stats_today.nb_bounced_last_24h} - {increase_percent(stats_yesterday.nb_bounced_last_24h, stats_today.nb_bounced_last_24h)}
nb_total_bounced_last_24h: {stats_today.nb_total_bounced_last_24h} - {increase_percent(stats_yesterday.nb_total_bounced_last_24h, stats_today.nb_total_bounced_last_24h)}

    """

    monitoring_report += "\n====================================\n"
    monitoring_report += f"""
# Account bounce report:
"""

    for email, bounces in bounce_report():
        monitoring_report += f"{email}: {bounces}\n"

    monitoring_report += f"""\n
# Alias creation report:
"""

    for email, nb_alias, date in alias_creation_report():
        monitoring_report += f"{email}, {date}: {nb_alias}\n"

    monitoring_report += f"""\n
# Full bounce detail report:
"""
    monitoring_report += all_bounce_report()

    LOG.d("monitoring_report email: %s", monitoring_report)

    send_email(
        MONITORING_EMAIL,
        subject=f"SimpleLogin Monitoring Report for {today}",
        plaintext=monitoring_report,
        retries=3,
    )


def migrate_domain_trash():
    """Move aliases from global trash to domain trash if applicable"""

    # ignore duplicate when insert
    # copied from https://github.com/sqlalchemy/sqlalchemy/issues/5374
    @compiles(Insert, "postgresql")
    def postgresql_on_conflict_do_nothing(insert, compiler, **kw):
        statement = compiler.visit_insert(insert, **kw)
        # IF we have a "RETURNING" clause, we must insert before it
        returning_position = statement.find("RETURNING")
        if returning_position >= 0:
            return (
                statement[:returning_position]
                + "ON CONFLICT DO NOTHING "
                + statement[returning_position:]
            )
        else:
            return statement + " ON CONFLICT DO NOTHING"

    sl_domains = [sl.domain for sl in SLDomain.all()]
    count = 0
    domain_deleted_aliases = []
    deleted_alias_ids = []
    for deleted_alias in DeletedAlias.yield_per_query():
        if count % 1000 == 0:
            LOG.d("process %s", count)

        count += 1

        alias_domain = get_email_domain_part(deleted_alias.email)
        if alias_domain not in sl_domains:
            custom_domain = CustomDomain.get_by(domain=alias_domain)
            if custom_domain:
                LOG.w("move %s to domain %s trash", deleted_alias, custom_domain)
                domain_deleted_aliases.append(
                    DomainDeletedAlias(
                        user_id=custom_domain.user_id,
                        email=deleted_alias.email,
                        domain_id=custom_domain.id,
                        created_at=deleted_alias.created_at,
                    )
                )
                deleted_alias_ids.append(deleted_alias.id)

    LOG.d("create %s DomainDeletedAlias", len(domain_deleted_aliases))
    Session.bulk_save_objects(domain_deleted_aliases)

    LOG.d("delete %s DeletedAlias", len(deleted_alias_ids))
    DeletedAlias.filter(DeletedAlias.id.in_(deleted_alias_ids)).delete(
        synchronize_session=False
    )

    Session.commit()


def set_custom_domain_for_alias():
    """Go through all aliases and make sure custom_domain is correctly set"""
    sl_domains = [sl_domain.domain for sl_domain in SLDomain.all()]
    for alias in Alias.yield_per_query().filter(Alias.custom_domain_id.is_(None)):
        if (
            not any(alias.email.endswith(f"@{sl_domain}") for sl_domain in sl_domains)
            and not alias.custom_domain_id
        ):
            alias_domain = get_email_domain_part(alias.email)
            custom_domain = CustomDomain.get_by(domain=alias_domain)
            if custom_domain:
                LOG.e("set %s for %s", custom_domain, alias)
                alias.custom_domain_id = custom_domain.id
            else:  # phantom domain
                LOG.d("phantom domain %s %s %s", alias.user, alias, alias.enabled)

    Session.commit()


def sanitize_alias_address_name():
    count = 0
    # using Alias.all() will take all the memory
    for alias in Alias.yield_per_query():
        if count % 1000 == 0:
            LOG.d("process %s", count)

        count += 1
        if sanitize_email(alias.email) != alias.email:
            LOG.e("Alias %s email not sanitized", alias)

        if alias.name and "\n" in alias.name:
            alias.name = alias.name.replace("\n", "")
            Session.commit()
            LOG.e("Alias %s name contains linebreak %s", alias, alias.name)


def sanity_check():
    LOG.d("sanitize user email")
    for user in User.filter_by(activated=True).all():
        if sanitize_email(user.email) != user.email:
            LOG.e("%s does not have sanitized email", user)

    LOG.d("sanitize alias address & name")
    sanitize_alias_address_name()

    LOG.d("sanity contact address")
    contact_email_sanity_date = arrow.get("2021-01-12")
    for contact in Contact.yield_per_query():
        if sanitize_email(contact.reply_email) != contact.reply_email:
            LOG.e("Contact %s reply-email not sanitized", contact)

        if (
            sanitize_email(contact.website_email, not_lower=True)
            != contact.website_email
            and contact.created_at > contact_email_sanity_date
        ):
            LOG.e("Contact %s website-email not sanitized", contact)

        if not contact.invalid_email and not is_valid_email(contact.website_email):
            LOG.e("%s invalid email", contact)
            contact.invalid_email = True
    Session.commit()

    LOG.d("sanitize mailbox address")
    for mailbox in Mailbox.yield_per_query():
        if sanitize_email(mailbox.email) != mailbox.email:
            LOG.e("Mailbox %s address not sanitized", mailbox)

    LOG.d("normalize reverse alias")
    for contact in Contact.yield_per_query():
        if normalize_reply_email(contact.reply_email) != contact.reply_email:
            LOG.e(
                "Contact %s reply email is not normalized %s",
                contact,
                contact.reply_email,
            )

    LOG.d("clean domain name")
    for domain in CustomDomain.yield_per_query():
        if domain.name and "\n" in domain.name:
            LOG.e("Domain %s name contain linebreak %s", domain, domain.name)

    LOG.d("migrate domain trash if needed")
    migrate_domain_trash()

    LOG.d("fix custom domain for alias")
    set_custom_domain_for_alias()

    LOG.d("check mailbox valid domain")
    check_mailbox_valid_domain()

    LOG.d("check mailbox valid PGP keys")
    check_mailbox_valid_pgp_keys()

    LOG.d(
        """check if there's an email that starts with "\u200f" (right-to-left mark (RLM))"""
    )
    for contact in (
        Contact.yield_per_query()
        .filter(Contact.website_email.startswith("\u200f"))
        .all()
    ):
        contact.website_email = contact.website_email.replace("\u200f", "")
        LOG.e("remove right-to-left mark (RLM) from %s", contact)
    Session.commit()

    LOG.d("Finish sanity check")


def check_mailbox_valid_domain():
    """detect if there's mailbox that's using an invalid domain"""
    mailbox_ids = (
        Session.query(Mailbox.id)
        .filter(Mailbox.verified.is_(True), Mailbox.disabled.is_(False))
        .all()
    )
    mailbox_ids = [e[0] for e in mailbox_ids]
    # iterate over id instead of mailbox directly
    # as a mailbox can be deleted in the meantime
    for mailbox_id in mailbox_ids:
        mailbox = Mailbox.get(mailbox_id)
        # a mailbox has been deleted
        if not mailbox:
            continue

        if email_can_be_used_as_mailbox(mailbox.email):
            LOG.d("Mailbox %s valid", mailbox)
            mailbox.nb_failed_checks = 0
        else:
            mailbox.nb_failed_checks += 1
            nb_email_log = nb_email_log_for_mailbox(mailbox)

            LOG.w(
                "issue with mailbox %s domain. #alias %s, nb email log %s",
                mailbox,
                mailbox.nb_alias(),
                nb_email_log,
            )

            # send a warning
            if mailbox.nb_failed_checks == 5:
                if mailbox.user.email != mailbox.email:
                    send_email(
                        mailbox.user.email,
                        f"Mailbox {mailbox.email} is disabled",
                        render(
                            "transactional/disable-mailbox-warning.txt.jinja2",
                            mailbox=mailbox,
                        ),
                        render(
                            "transactional/disable-mailbox-warning.html",
                            mailbox=mailbox,
                        ),
                        retries=3,
                    )

            # alert if too much fail and nb_email_log > 100
            if mailbox.nb_failed_checks > 10 and nb_email_log > 100:
                mailbox.disabled = True

                if mailbox.user.email != mailbox.email:
                    send_email(
                        mailbox.user.email,
                        f"Mailbox {mailbox.email} is disabled",
                        render(
                            "transactional/disable-mailbox.txt.jinja2", mailbox=mailbox
                        ),
                        render("transactional/disable-mailbox.html", mailbox=mailbox),
                        retries=3,
                    )

        Session.commit()


def check_mailbox_valid_pgp_keys():
    mailbox_ids = (
        Session.query(Mailbox.id)
        .filter(
            Mailbox.verified.is_(True),
            Mailbox.pgp_public_key.isnot(None),
            Mailbox.disable_pgp.is_(False),
        )
        .all()
    )
    mailbox_ids = [e[0] for e in mailbox_ids]
    # iterate over id instead of mailbox directly
    # as a mailbox can be deleted in the meantime
    for mailbox_id in mailbox_ids:
        mailbox = Mailbox.get(mailbox_id)
        # a mailbox has been deleted
        if not mailbox:
            LOG.d(f"Mailbox {mailbox_id} not found")
            continue

        LOG.d(f"Checking PGP key for {mailbox}")

        try:
            load_public_key_and_check(mailbox.pgp_public_key)
        except PGPException:
            LOG.i(f"{mailbox} PGP key invalid")
            send_email(
                mailbox.user.email,
                f"Mailbox {mailbox.email}'s PGP Key is invalid",
                render(
                    "transactional/invalid-mailbox-pgp-key.txt.jinja2",
                    mailbox=mailbox,
                ),
                retries=3,
            )


def check_custom_domain():
    LOG.d("Check verified domain for DNS issues")

    for custom_domain in CustomDomain.filter_by(verified=True):  # type: CustomDomain
        try:
            check_single_custom_domain(custom_domain)
        except ObjectDeletedError:
            LOG.i("custom domain has been deleted")


def check_single_custom_domain(custom_domain):
    mx_domains = get_mx_domains(custom_domain.domain)
    if not is_mx_equivalent(mx_domains, EMAIL_SERVERS_WITH_PRIORITY):
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
            domain_dns_url = f"{URL}/dashboard/domains/{custom_domain.id}/dns"
            LOG.w("Alert domain MX check fails %s about %s", user, custom_domain)
            send_email_with_rate_control(
                user,
                AlERT_WRONG_MX_RECORD_CUSTOM_DOMAIN,
                user.email,
                f"Please update {custom_domain.domain} DNS on SimpleLogin",
                render(
                    "transactional/custom-domain-dns-issue.txt.jinja2",
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


def delete_old_monitoring():
    """
    Delete old monitoring records
    """
    max_time = arrow.now().shift(days=-30)
    nb_row = Monitoring.filter(Monitoring.created_at < max_time).delete()
    Session.commit()
    LOG.d("delete monitoring records older than %s, nb row %s", max_time, nb_row)


def delete_expired_tokens():
    """
    Delete old tokens
    """
    max_time = arrow.now().shift(hours=-1)
    nb_row = ApiToCookieToken.filter(ApiToCookieToken.created_at < max_time).delete()
    Session.commit()
    LOG.d("Delete api to cookie tokens older than %s, nb row %s", max_time, nb_row)


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
        Session.add(alias)
        Session.commit()

        LOG.d("Updated breaches info for %s", alias)

        await asyncio.sleep(1.6)


async def check_hibp():
    """
    Check all aliases on the HIBP (Have I Been Pwned) API
    """
    LOG.d("Checking HIBP API for aliases in breaches")

    if len(HIBP_API_KEYS) == 0:
        LOG.e("No HIBP API keys")
        return

    LOG.d("Updating list of known breaches")
    r = requests.get("https://haveibeenpwned.com/api/v3/breaches")
    for entry in r.json():
        hibp_entry = Hibp.get_or_create(name=entry["Name"])
        hibp_entry.date = arrow.get(entry["BreachDate"])
        hibp_entry.description = entry["Description"]

    Session.commit()
    LOG.d("Updated list of known breaches")

    LOG.d("Preparing list of aliases to check")
    queue = asyncio.Queue()
    max_date = arrow.now().shift(days=-HIBP_SCAN_INTERVAL_DAYS)
    for alias in (
        Alias.filter(
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


def notify_hibp():
    """
    Send aggregated email reports for HIBP breaches
    """
    # to get a list of users that have at least a breached alias
    alias_query = (
        Session.query(Alias)
        .options(joinedload(Alias.hibp_breaches))
        .filter(Alias.hibp_breaches.any())
        .filter(Alias.id.notin_(Session.query(HibpNotifiedAlias.alias_id)))
        .distinct(Alias.user_id)
        .all()
    )

    user_ids = [alias.user_id for alias in alias_query]

    for user in User.filter(User.id.in_(user_ids)):
        breached_aliases = (
            Session.query(Alias)
            .options(joinedload(Alias.hibp_breaches))
            .filter(Alias.hibp_breaches.any(), Alias.user_id == user.id)
            .all()
        )

        LOG.d(
            f"Send new breaches found email to %s for %s breaches aliases",
            user,
            len(breached_aliases),
        )

        send_email(
            user.email,
            f"You were in a data breach",
            render(
                "transactional/hibp-new-breaches.txt.jinja2",
                user=user,
                breached_aliases=breached_aliases,
            ),
            render(
                "transactional/hibp-new-breaches.html",
                user=user,
                breached_aliases=breached_aliases,
            ),
            retries=3,
        )

        # add the breached aliases to HibpNotifiedAlias to avoid sending another email
        for alias in breached_aliases:
            HibpNotifiedAlias.create(user_id=user.id, alias_id=alias.id)
        Session.commit()


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
            "notify_hibp",
            "cleanup_tokens",
        ],
    )
    args = parser.parse_args()
    # wrap in an app context to benefit from app setup like database cleanup, sentry integration, etc
    with create_light_app().app_context():
        if args.job == "stats":
            LOG.d("Compute growth and daily monitoring stats")
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
        elif args.job == "notify_hibp":
            LOG.d("Notify users about HIBP breaches")
            notify_hibp()
        elif args.job == "cleanup_tokens":
            LOG.d("Cleanup expired tokens")
            delete_expired_tokens()
