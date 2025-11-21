import os

from flask import testing

# use the tests/test.env config fle
# flake8: noqa: E402

os.environ["CONFIG"] = os.path.abspath(
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "tests/test.env")
)
import sqlalchemy

from app.db import Session, engine, connection
from app.rate_limiter import set_rate_limit_enabled

from psycopg2 import errors
from psycopg2.errorcodes import DEPENDENT_OBJECTS_STILL_EXIST

import pytest

from server import create_app
from init_app import add_sl_domains, add_proton_partner

# Disable rate limit for tests
set_rate_limit_enabled(False)

app = create_app()
app.config["TESTING"] = True
app.config["WTF_CSRF_ENABLED"] = False
app.config["SERVER_NAME"] = "sl.lan"

# enable pg_trgm extension
with engine.connect() as conn:
    try:
        conn.execute("DROP EXTENSION if exists pg_trgm")
        conn.execute("CREATE EXTENSION pg_trgm")
    except sqlalchemy.exc.InternalError as e:
        if isinstance(e.orig, errors.lookup(DEPENDENT_OBJECTS_STILL_EXIST)):
            print(">>> pg_trgm can't be dropped, ignore")
        conn.execute("Rollback")

add_sl_domains()
add_proton_partner()


@pytest.fixture
def flask_app():
    yield app


from app import config, constants


class CustomTestClient(testing.FlaskClient):
    def open(self, *args, **kwargs):
        if isinstance(args[0], str):
            headers = kwargs.pop("headers", {})
            headers.update({constants.HEADER_ALLOW_API_COOKIES: "allow"})
            kwargs["headers"] = headers
        return super().open(*args, **kwargs)


@pytest.fixture
def flask_client():
    transaction = connection.begin()

    with app.app_context():
        # disable rate limit during test
        config.DISABLE_RATE_LIMIT = True
        try:
            app.test_client_class = CustomTestClient
            client = app.test_client()
            client.environ_base[constants.HEADER_ALLOW_API_COOKIES] = "allow"
            yield client
        finally:
            # disable rate limit again as some tests might enable rate limit
            config.DISABLE_RATE_LIMIT = True
            # roll back all commits made during a test
            transaction.rollback()
            Session.rollback()
            Session.close()
