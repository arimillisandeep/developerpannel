from alembic import context
from sqlalchemy import create_engine

from app.core.config import settings
from app.database import models  # noqa: F401  (registers tables)
from app.database.connection import Base

target_metadata = Base.metadata


def run():
    engine = create_engine(settings.DATABASE_URL)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


run()
