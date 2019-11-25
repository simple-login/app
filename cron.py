import arrow

from app import email_utils
from app.extensions import db
from app.log import LOG
from app.models import Subscription, User, GenEmail, ForwardEmailLog, ForwardEmail
from server import create_app


def late_payment():
    """check for late payment
    """
    for sub in Subscription.query.all():
        if (not sub.cancelled) and sub.next_bill_date < arrow.now().date():
            LOG.error(f"user {sub.user.email} has late payment. {sub}")


_ignored_emails = ["nguyenkims", "mbpcmeo", "son@simplelogin.io"]


def stats():
    """send admin stats everyday"""
    # nb user
    q = User.query
    for ie in _ignored_emails:
        q = q.filter(~User.email.contains(ie))

    nb_user = q.count()

    LOG.d("total number user %s", nb_user)

    # nb gen emails
    q = db.session.query(GenEmail, User).filter(GenEmail.user_id == User.id)
    for ie in _ignored_emails:
        q = q.filter(~User.email.contains(ie))

    nb_gen_email = q.count()
    LOG.d("total number alias %s", nb_gen_email)

    # nb mails forwarded
    q = db.session.query(ForwardEmailLog, ForwardEmail, GenEmail, User).filter(
        ForwardEmailLog.forward_id == ForwardEmail.id,
        ForwardEmail.gen_email_id == GenEmail.id,
        GenEmail.user_id == User.id,
    )
    for ie in _ignored_emails:
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

    today = arrow.now().format()

    email_utils.notify_admin(
        f"Stats for {today}",
        f"""
Stats for {today} <br>
nb_user: {nb_user} <br>
nb_alias: {nb_gen_email} <br>
nb_forward: {nb_forward} <br>
nb_reply: {nb_reply} <br>
nb_block: {nb_block} <br>
    """,
    )


if __name__ == "__main__":
    LOG.d("Start running cronjob")
    app = create_app()

    with app.app_context():
        late_payment()
        stats()
