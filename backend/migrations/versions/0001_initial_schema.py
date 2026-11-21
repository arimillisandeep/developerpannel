"""initial schema (29 tables)

Creates only tables that do not exist yet (checkfirst). It never drops, truncates or
alters an existing table. Later schema changes get their own revision:
    alembic revision --autogenerate -m "describe change"
"""
from alembic import op

from app.database import models  # noqa: F401
from app.database.connection import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade():
    # Deliberately a no-op: this project never drops tables that may hold company records.
    pass
