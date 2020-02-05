import argparse

import arrow

from app.config import IGNORED_EMAILS, ADMIN_EMAIL
from app.email_utils import send_email, send_trial_end_soon_email
from app.extensions import db
from app.log import LOG
from app.models import (
    Subscription,
    User,
    GenEmail,
    ForwardEmailLog,
    ForwardEmail,
    CustomDomain,
    Client,
)
from server import create_app


def notify_trial_end():
    for user in User.query.filter(
        User.activated == True, User.trial_end.isnot(None)
    ).all():
        if arrow.now().shift(days=3) > user.trial_end >= arrow.now().shift(days=2):
            LOG.d("Send trial end email to user %s", user)
            send_trial_end_soon_email(user)


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
    q = db.session.query(GenEmail, User).filter(GenEmail.user_id == User.id)
    for ie in IGNORED_EMAILS:
        q = q.filter(~User.email.contains(ie))

    nb_gen_email = q.count()
    LOG.d("total number alias %s", nb_gen_email)

    # nb mails forwarded
    q = db.session.query(ForwardEmailLog, ForwardEmail, GenEmail, User).filter(
        ForwardEmailLog.forward_id == ForwardEmail.id,
        ForwardEmail.gen_email_id == GenEmail.id,
        GenEmail.user_id == User.id,
    )
    for ie in IGNORED_EMAILS:
        q = q.filter(~User.email.contains(ie))

    nb_forward = nb_block = nb_reply = 0
    for fel, _, _, _ in q:
        if fel.is_reply:
            nb_reply += 1
        elif fel.blocked:
            nb_block += 1
        else:
            nb_forward += 1

    LOG.d("nb forward %s, nb block %s, nb reply %s", nb_forward, nb_block, nb_reply)

    nb_premium = Subscription.query.count()
    nb_custom_domain = CustomDomain.query.count()

    nb_custom_domain_alias = GenEmail.query.filter(
        GenEmail.custom_domain_id.isnot(None)
    ).count()

    nb_disabled_alias = GenEmail.query.filter(GenEmail.enabled == False).count()

    nb_app = Client.query.count()

    today = arrow.now().format()

    send_email(
        ADMIN_EMAIL,
        subject=f"SimpleLogin Stats for {today}, {nb_user} users, {nb_gen_email} aliases, {nb_forward} forwards",
        plaintext="",
        html=f"""
Stats for {today} <br>

nb_user: {nb_user} <br>
nb_premium: {nb_premium} <br>

nb_alias: {nb_gen_email} <br>
nb_disabled_alias: {nb_disabled_alias} <br>

nb_custom_domain: {nb_custom_domain} <br>
nb_custom_domain_alias: {nb_custom_domain_alias} <br>

nb_forward: {nb_forward} <br>
nb_reply: {nb_reply} <br>
nb_block: {nb_block} <br>

nb_app: {nb_app} <br>
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
        choices=["stats", "notify_trial_end",],
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
