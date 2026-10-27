from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> Engine:
    is_sqlite = url.startswith("sqlite")
    if is_sqlite:
        engine = create_engine(url, connect_args={"check_same_thread": False})
    else:
        # A database server restart leaves pooled connections dead; test each one before use.
        engine = create_engine(url, pool_pre_ping=True)
    if is_sqlite:
        # SQLite ignores ON DELETE CASCADE unless foreign keys are switched on per connection.
        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def make_sessionmaker(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)
