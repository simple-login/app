import argparse

import arrow

from app import s3
from app.config import IGNORED_EMAILS, ADMIN_EMAIL
from app.email_utils import send_email, send_trial_end_soon_email, render
from app.extensions import db
from app.log import LOG
from app.models import (
    Subscription,
    User,
    Alias,
    EmailLog,
    Contact,
    CustomDomain,
    Client,
    ManualSubscription,
    RefusedEmail,
)
from server import create_app


def notify_trial_end():
    for user in User.query.filter(
        User.activated == True, User.trial_end.isnot(None), User.lifetime == False
    ).all():
        if user.in_trial() and arrow.now().shift(
            days=3
        ) > user.trial_end >= arrow.now().shift(days=2):
            LOG.d("Send trial end email to user %s", user)
            send_trial_end_soon_email(user)


def delete_refused_emails():
    for refused_email in RefusedEmail.query.filter(RefusedEmail.deleted == False).all():
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
    for sub in Subscription.query.filter(Subscription.cancelled == True).all():
        if (
            arrow.now().shift(days=3).date()
            > sub.next_bill_date
            >= arrow.now().shift(days=2).date()
        ):
            user = sub.user
            LOG.d(f"Send subscription ending soon email to user {user}")

            send_email(
                user.email,
                f"Your subscription will end soon {user.name}",
                render("transactional/subscription-end.txt", user=user),
                render("transactional/subscription-end.html", user=user),
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
                f"Your trial will end soon {user.name}",
                render(
                    "transactional/manual-subscription-end.txt",
                    name=user.name,
                    user=user,
                    manual_sub=manual_sub,
                ),
                render(
                    "transactional/manual-subscription-end.html",
                    name=user.name,
                    user=user,
                    manual_sub=manual_sub,
                ),
            )


def stats():
    """send admin stats everyday"""
    if not ADMIN_EMAIL:
        # nothing to do
        return

    # nb user
    q = User.query
    for ie in IGNORED_EMAILS:
        q = q.filter(~User.email.contains(ie))

    nb_user = q.count()

    LOG.d("total number user %s", nb_user)

    # nb gen emails
    q = db.session.query(Alias, User).filter(Alias.user_id == User.id)
    for ie in IGNORED_EMAILS:
        q = q.filter(~User.email.contains(ie))

    nb_alias = q.count()
    LOG.d("total number alias %s", nb_alias)

    # nb mails forwarded
    q = db.session.query(EmailLog, Contact, Alias, User).filter(
        EmailLog.contact_id == Contact.id,
        Contact.alias_id == Alias.id,
        Alias.user_id == User.id,
    )
    for ie in IGNORED_EMAILS:
        q = q.filter(~User.email.contains(ie))

    nb_forward = nb_block = nb_reply = 0
    for email_log, _, _, _ in q:
        if email_log.is_reply:
            nb_reply += 1
        elif email_log.blocked:
            nb_block += 1
        else:
            nb_forward += 1

    LOG.d("nb forward %s, nb block %s, nb reply %s", nb_forward, nb_block, nb_reply)

    nb_premium = Subscription.query.count()
    nb_custom_domain = CustomDomain.query.count()

    nb_custom_domain_alias = Alias.query.filter(
        Alias.custom_domain_id.isnot(None)
    ).count()

    nb_disabled_alias = Alias.query.filter(Alias.enabled == False).count()

    nb_app = Client.query.count()

    nb_bounced_email = EmailLog.query.filter(EmailLog.bounced).count()
    nb_spam = EmailLog.query.filter(EmailLog.is_spam).count()

    today = arrow.now().format()

    send_email(
        ADMIN_EMAIL,
        subject=f"SimpleLogin Stats for {today}, {nb_user} users, {nb_alias} aliases, {nb_forward} forwards",
        plaintext="",
        html=f"""
Stats for {today} <br>

nb_user: {nb_user} <br>
nb_premium: {nb_premium} <br>

nb_alias: {nb_alias} <br>
nb_disabled_alias: {nb_disabled_alias} <br>

nb_custom_domain: {nb_custom_domain} <br>
nb_custom_domain_alias: {nb_custom_domain_alias} <br>

nb_forward: {nb_forward} <br>
nb_reply: {nb_reply} <br>
nb_block: {nb_block} <br>

nb_app: {nb_app} <br>

nb_bounced_email: {nb_bounced_email} <br>
nb_spam: {nb_spam} <br>
    """,
    )


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
