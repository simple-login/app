"""This ad-hoc script is to be run when upgrading from 1.0.5 to 1.1.0
"""
from app.extensions import db
from app.log import LOG
from app.models import Mailbox, GenEmail, User


def convert_user_full_mailbox(user):
    # create a default mailbox
    default_mb = Mailbox.get_by(user_id=user.id, email=user.email)
    if not default_mb:
        LOG.d("create default mailbox for user %s", user)
        default_mb = Mailbox.create(user_id=user.id, email=user.email, verified=True)
        db.session.commit()

    # assign existing alias to this mailbox
    for gen_email in GenEmail.query.filter_by(user_id=user.id):
        if not gen_email.mailbox_id:
            LOG.d("Set alias  %s mailbox to default mailbox", gen_email)
            gen_email.mailbox_id = default_mb.id

    # finally set user to full_mailbox
    user.full_mailbox = True
    user.default_mailbox_id = default_mb.id
    db.session.commit()


if __name__ == "__main__":
    for user in User.query.all():
        if not user.full_mailbox:
            convert_user_full_mailbox(user)
