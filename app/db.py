import sqlalchemy
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session
from sqlalchemy.orm import sessionmaker

from app import config


engine = create_engine(
    config.DB_URI,
    connect_args={"application_name": config.DB_CONN_NAME},
    # Test pooled connections on checkout so a connection dropped while idle
    # (DB restart, failover, pgbouncer) is replaced instead of failing a request.
    pool_pre_ping=True,
)

# Bind to the engine rather than one long-lived Connection: a shared Connection
# can get stuck holding a dead DBAPI connection after a disconnect, failing every
# later query with "'NoneType' object has no attribute 'cursor'".
Session = scoped_session(sessionmaker(bind=engine))

# Session is actually a proxy, more info on
# https://docs.sqlalchemy.org/en/14/orm/contextual.html?highlight=scoped_session#implicit-method-access
Session: sqlalchemy.orm.Session
