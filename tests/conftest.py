import os

# use in-memory database
# need to set before importing any other module as DB_URI is init at import time
os.environ["DB_URI"] = "sqlite://"

import pytest

from app.extensions import db
from server import create_app


@pytest.fixture
def flask_app():
    app = create_app()

    app.config["TESTING"] = True

    with app.app_context():
        db.create_all()

    yield app


@pytest.fixture
def flask_client():
    app = create_app()

    # use in-memory database
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
    app.config["TESTING"] = True

    client = app.test_client()

    with app.app_context():
        db.create_all()
        yield client
