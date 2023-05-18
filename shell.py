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
            .all()
        )
        batch_codes = len(recovery_codes)
        old_codes = 0
        new_codes = 0
        last_code = None
        last_code_id = None
        for recovery_code in recovery_codes:
            if len(recovery_code.code) == models._RECOVERY_CODE_LENGTH:
                last_code = recovery_code.code
                last_code_id = recovery_code.id
                recovery_code.code = RecoveryCode._hash_code(recovery_code.code)
                old_codes += 1
                Session.flush()
            else:
                new_codes += 1
            last_id = recovery_code.id
        Session.commit()
        LOG.i(
            f"Updated {old_codes}/{batch_codes} for this batch ({new_codes} already updated)"
        )
        if last_code is not None:
            recovery_code = RecoveryCode.get_by(id=last_code_id)
            assert RecoveryCode._hash_code(last_code) == recovery_code.code
            LOG.i("Check is Good")

        if len(recovery_codes) == 0:
            break


if __name__ == "__main__":
    embed()
