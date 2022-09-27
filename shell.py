from time import sleep

import flask_migrate
from IPython import embed
from sqlalchemy_utils import create_database, database_exists, drop_database

from app import models
from app.config import DB_URI
from app.models import *


if False:
    # noinspection PyUnreachableCode
    def create_db():
        if not database_exists(DB_URI):
            LOG.d("db not exist, create database")
            create_database(DB_URI)

            # Create all tables
            # Use flask-migrate instead of db.create_all()
            flask_migrate.upgrade()

    # noinspection PyUnreachableCode
    def reset_db():
        if database_exists(DB_URI):
            drop_database(DB_URI)
        create_db()


def change_password(user_id, new_password):
    user = User.get(user_id)
    user.set_password(new_password)
    Session.commit()


def migrate_recovery_codes():
    last_id = -1
    while True:
        recovery_codes = (
            RecoveryCode.filter(RecoveryCode.id > last_id)
            .order_by(RecoveryCode.id)
            .limit(100)
        )
        users_by_id = {}
        for recovery_code in recovery_codes:
            if len(recovery_code.code) == models._RECOVERY_CODE_LENGTH:
                if recovery_code.user_id not in users_by_id:
                    users_by_id[recovery_code.user_id] = recovery_code.user
                recovery_code.code = RecoveryCode._hash_code(
                    users_by_id[recovery_code.user_id], recovery_code.code
                )
            last_id = recovery_code.id
        Session.commit()
        if len(recovery_codes) == 0:
            break


if __name__ == "__main__":
    embed()
