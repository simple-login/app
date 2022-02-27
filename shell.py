from time import sleep

import flask_migrate
from IPython import embed
from sqlalchemy_utils import create_database, database_exists, drop_database

from app.config import DB_URI
from app.db import Session
from app.email_utils import send_email, render
from app.log import LOG
from app.models import *
from job_runner import (
    onboarding_pgp,
    onboarding_browser_extension,
    onboarding_mailbox,
    onboarding_send_from_alias,
)


def create_db():
    if not database_exists(DB_URI):
        LOG.d("db not exist, create database")
        create_database(DB_URI)

        # Create all tables
        # Use flask-migrate instead of db.create_all()
        flask_migrate.upgrade()


def change_password(user_id, new_password):
    user = User.get(user_id)
    user.set_password(new_password)
    Session.commit()


def reset_db():
    if database_exists(DB_URI):
        drop_database(DB_URI)
    create_db()


if __name__ == "__main__":
    embed()
