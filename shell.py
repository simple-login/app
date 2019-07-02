import flask_migrate
import stripe
from IPython import embed
from sqlalchemy_utils import create_database, database_exists, drop_database

from app.config import DB_URI
from app.models import *
from app.oauth_models import ScopeE
from server import create_app


def create_db():
    if not database_exists(DB_URI):
        LOG.debug("db not exist, create database")
        create_database(DB_URI)

        # Create all tables
        # Use flask-migrate instead of db.create_all()
        flask_migrate.upgrade()

        scope_name = Scope.create(name=ScopeE.NAME.value)
        db.session.add(scope_name)
        scope_email = Scope.create(name=ScopeE.EMAIL.value)
        db.session.add(scope_email)
        db.session.commit()


def add_real_data():
    """after the db is reset, add some accounts
    TODO: remove this after adding alembic"""
    user = User.create(email="nguyenkims@gmail.com", name="Son GM", activated=True)
    user.set_password("password")
    db.session.commit()

    # Create a client
    client1 = Client.create_new(name="Demo", user_id=user.id)
    client1.oauth_client_id = "client-id"
    client1.oauth_client_secret = "client-secret"
    db.session.commit()

    RedirectUri.create(client_id=client1.id, uri="http://demo.sl.meo.ovh/callback")
    db.session.commit()

    user2 = User.create(email="nguyenkims@hotmail.com", name="Son HM", activated=True)
    user2.set_password("password")
    db.session.commit()


def change_password(user_id, new_password):
    user = User.get(user_id)
    user.set_password(new_password)
    db.session.commit()


def reset_db():
    if database_exists(DB_URI):
        drop_database(DB_URI)
    create_db()
    add_real_data()


app = create_app()

with app.app_context():
    embed()
