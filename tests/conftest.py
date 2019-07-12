import os

os.environ["CONFIG"] = os.path.abspath(
    os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env.example")
)


# use in-memory database
# need to set before importing any other module as DB_URI is init at import time
os.environ["DB_URI"] = "sqlite://"

import pytest

from app.extensions import db
from server import create_app


@pytest.fixture
def flask_app():
    app = create_app()

    # use in-memory database
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        db.create_all()

    yield app


@pytest.fixture
def flask_client():
    app = create_app()

    # use in-memory database
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    client = app.test_client()

    with app.app_context():
        db.create_all()
        yield client
