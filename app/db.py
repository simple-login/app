from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session
from sqlalchemy.orm import sessionmaker

from app.config import DB_URI

engine = create_engine(DB_URI)
connection = engine.connect()

Session = scoped_session(sessionmaker(bind=connection))
