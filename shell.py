import flask_migrate
from IPython import embed
from sqlalchemy_utils import create_database, database_exists, drop_database

from app.config import DB_URI
from app.email_utils import send_email, render
from app.models import *
from server import create_app


def create_db():
    if not database_exists(DB_URI):
        LOG.debug("db not exist, create database")
        create_database(DB_URI)

        # Create all tables
        # Use flask-migrate instead of db.create_all()
        flask_migrate.upgrade()


def change_password(user_id, new_password):
    user = User.get(user_id)
    user.set_password(new_password)
    db.session.commit()


def reset_db():
    if database_exists(DB_URI):
        drop_database(DB_URI)
    create_db()


def send_safari_extension_newsletter():
    for user in User.query.all():
        send_email(
            user.email,
            "Quickly create alias with our Safari extension",
            render("com/safari-extension.txt", user=user),
            render("com/safari-extension.html", user=user),
        )


def convert_user_full_mailbox(user):
    # create a default mailbox
    default_mb = Mailbox.get_by(user_id=user.id, email=user.email)
    if not default_mb:
        LOG.d("create default mailbox for user %s", user)
        default_mb = Mailbox.create(user_id=user.id, email=user.email, verified=True)
        db.session.commit()

    # assign existing alias to this mailbox
    for gen_email in GenEmail.query.filter_by(user_id=user.id):
        gen_email.mailbox_id = default_mb.id

    # finally set user to full_mailbox
    user.full_mailbox = True
    user.default_mailbox_id = default_mb.id
    db.session.commit()


app = create_app()

with app.app_context():
    # to test email template
    # with open("/tmp/email.html", "w") as f:
    #     user = User.get(1)
    #     f.write(
    #         render(
    #             "transactional/reset-password.html",
    #             email=user.email,
    #             user=user,
    #             name=user.name,
    #             activation_link="https://ab.cd",
    #             alias="alias@ab.cd",
    #             directory="dir",
    #             domain="domain",
    #             new_email="new@email.com",
    #             current_email="current@email.com",
    #             link="https://link.com",
    #             mailbox_email="mailbox_email@email.com",
    #             sender="sender@example.com",
    #             reset_password_link="http://reset_password_link",
    #         )
    #     )

    embed()
