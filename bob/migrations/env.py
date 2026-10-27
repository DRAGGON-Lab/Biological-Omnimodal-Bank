from alembic import context
from sqlalchemy import create_engine

from bob import models  # noqa: F401  (registers tables on Base.metadata)
from bob.db import Base

config = context.config
target_metadata = Base.metadata


def _run(connection) -> None:
    # Batch mode lets ALTER-style migrations work on SQLite, which cannot alter columns in place.
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


connection = config.attributes.get("connection")
if connection is not None:
    _run(connection)
else:
    with create_engine(config.get_main_option("sqlalchemy.url")).connect() as conn:
        _run(conn)
