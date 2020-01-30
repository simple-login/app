import flask_migrate
from IPython import embed
from sqlalchemy_utils import create_database, database_exists, drop_database

from app.config import DB_URI
from app.email_utils import _render
from app.models import *
from server import create_app
from app import email_utils


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


app = create_app()

with app.app_context():
    # to test email template
    # with open("/tmp/email.html", "w") as f:
    #     user = User.get(1)
    #     f.write(_render("welcome.html", user=user, name=user.name))

    embed()
