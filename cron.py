import argparse
from dataclasses import dataclass
from time import sleep

import arrow
from arrow import Arrow

from app import s3
from app.alias_utils import nb_email_log_for_mailbox
from app.api.views.apple import verify_receipt
from app.config import (
    IGNORED_EMAILS,
    ADMIN_EMAIL,
    MACAPP_APPLE_API_SECRET,
    APPLE_API_SECRET,
    EMAIL_SERVERS_WITH_PRIORITY,
    URL,
    AlERT_WRONG_MX_RECORD_CUSTOM_DOMAIN,
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
)
from app.utils import sanitize_email
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
)
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


@dataclass
class Stats:
    nb_user: int
    nb_alias: int

    nb_forward: int
    nb_block: int
    nb_reply: int
    nb_bounced: int
    nb_spam: int

    nb_custom_domain: int
    nb_app: int

    nb_premium: int
    nb_apple_premium: int
    nb_cancelled_premium: int
    nb_manual_premium: int
    nb_coinbase_premium: int

    # nb users who have been referred
    nb_referred_user: int
    nb_referred_user_upgrade: int


def stats_before(moment: Arrow) -> Stats:
    """return the stats before a specific moment, ignoring all stats come from users in IGNORED_EMAILS"""
    # nb user
    q = User.query
    for ie in IGNORED_EMAILS:
        q = q.filter(~User.email.contains(ie), User.created_at < moment)

    nb_user = q.count()
    LOG.d("total number user %s", nb_user)

    nb_referred_user = q.filter(User.referral_id.isnot(None)).count()
    nb_referred_user_upgrade = 0
    for user in q.filter(User.referral_id.isnot(None)):
        if user.is_premium():
            nb_referred_user_upgrade += 1

    LOG.d(
        "%s nb_referred_user:%s nb_referred_user_upgrade:%s",
        moment,
        nb_referred_user,
        nb_referred_user_upgrade,
    )

    # nb alias
    q = db.session.query(Alias, User).filter(
        Alias.user_id == User.id, Alias.created_at < moment
    )
    for ie in IGNORED_EMAILS:
        q = q.filter(~User.email.contains(ie))

    nb_alias = q.count()
    LOG.d("total number alias %s", nb_alias)

    # email log stats
    q = (
        db.session.query(EmailLog)
        .join(User, EmailLog.user_id == User.id)
        .filter(
            EmailLog.created_at < moment,
        )
    )
    for ie in IGNORED_EMAILS:
        q = q.filter(~User.email.contains(ie))

    nb_spam = nb_bounced = nb_forward = nb_block = nb_reply = 0
    for email_log in q.yield_per(500):
        if email_log.bounced:
            nb_bounced += 1
        elif email_log.is_spam:
            nb_spam += 1
        elif email_log.is_reply:
            nb_reply += 1
        elif email_log.blocked:
            nb_block += 1
        else:
            nb_forward += 1

    LOG.d(
        "nb_forward %s, nb_block %s, nb_reply %s, nb_bounced %s, nb_spam %s",
        nb_forward,
        nb_block,
        nb_reply,
        nb_bounced,
        nb_spam,
    )

    nb_premium = Subscription.query.filter(
        Subscription.created_at < moment, Subscription.cancelled.is_(False)
    ).count()
    nb_apple_premium = AppleSubscription.query.filter(
        AppleSubscription.created_at < moment
    ).count()
    nb_cancelled_premium = Subscription.query.filter(
        Subscription.created_at < moment, Subscription.cancelled.is_(True)
    ).count()

    now = arrow.now()
    nb_manual_premium = ManualSubscription.query.filter(
        ManualSubscription.created_at < moment,
        ManualSubscription.end_at > now,
        ManualSubscription.is_giveaway.is_(False),
    ).count()

    nb_coinbase_premium = CoinbaseSubscription.query.filter(
        CoinbaseSubscription.created_at < moment, CoinbaseSubscription.end_at > now
    ).count()

    nb_custom_domain = CustomDomain.query.filter(
        CustomDomain.created_at < moment
    ).count()

    nb_app = Client.query.filter(Client.created_at < moment).count()

    data = locals()
    # to keep only Stats field
    data = {
        k: v
        for (k, v) in data.items()
        if k in vars(Stats)["__dataclass_fields__"].keys()
    }
    return Stats(**data)


def increase_percent(old, new) -> str:
    if old == 0:
        return "N/A"

    increase = (new - old) / old * 100
    return f"{increase:.1f}%. Delta: {new-old}"


def stats():
    """send admin stats everyday"""
    if not ADMIN_EMAIL:
        # nothing to do
        return

    stats_today = stats_before(arrow.now())
    stats_yesterday = stats_before(arrow.now().shift(days=-1))

    nb_user_increase = increase_percent(stats_yesterday.nb_user, stats_today.nb_user)
    nb_alias_increase = increase_percent(stats_yesterday.nb_alias, stats_today.nb_alias)
    nb_forward_increase = increase_percent(
        stats_yesterday.nb_forward, stats_today.nb_forward
    )

    today = arrow.now().format()

    send_email(
        ADMIN_EMAIL,
        subject=f"SimpleLogin Stats for {today}, {nb_user_increase} users, {nb_alias_increase} aliases, {nb_forward_increase} forwards",
        plaintext="",
        html=f"""
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

nb_custom_domain: {stats_today.nb_custom_domain} - {increase_percent(stats_yesterday.nb_custom_domain, stats_today.nb_custom_domain)}  <br>
nb_app: {stats_today.nb_app} - {increase_percent(stats_yesterday.nb_app, stats_today.nb_app)}  <br>
nb_referred_user: {stats_today.nb_referred_user} - {increase_percent(stats_yesterday.nb_referred_user, stats_today.nb_referred_user)}  <br>
nb_referred_user_upgrade: {stats_today.nb_referred_user_upgrade} - {increase_percent(stats_yesterday.nb_referred_user_upgrade, stats_today.nb_referred_user_upgrade)}  <br>
    """,
    )


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
                LOG.warning("Alert %s about %s", user, custom_domain)
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
            "delete_refused_emails",
            "poll_apple_subscription",
            "sanity_check",
            "delete_old_monitoring",
            "check_custom_domain",
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
        elif args.job == "delete_refused_emails":
            LOG.d("Deleted refused emails")
            delete_refused_emails()
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
