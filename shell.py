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


def send_mailbox_newsletter():
    for user in User.query.order_by(User.id).all():
        if user.notification and user.activated:
            try:
                LOG.d("Send newsletter to %s", user)
                send_email(
                    user.email,
                    "Introducing Mailbox - our most requested feature",
                    render("com/newsletter/mailbox.txt", user=user),
                    render("com/newsletter/mailbox.html", user=user),
                )
            except Exception:
                LOG.warning("Cannot send to user %s", user)


def send_pgp_newsletter():
    for user in User.query.order_by(User.id).all():
        if user.notification and user.activated:
            try:
                LOG.d("Send PGP newsletter to %s", user)
                send_email(
                    user.email,
                    "Introducing PGP - encrypt your emails so only you can read them",
                    render("com/newsletter/pgp.txt", user=user),
                    render("com/newsletter/pgp.html", user=user),
                )
            except Exception:
                LOG.warning("Cannot send to user %s", user)


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
