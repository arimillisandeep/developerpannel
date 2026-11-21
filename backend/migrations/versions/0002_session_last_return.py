"""work_sessions.last_return_at (additive, nullable)"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("work_sessions")}
    if "last_return_at" not in columns:  # a fresh 0001 already creates it
        op.add_column("work_sessions", sa.Column("last_return_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    pass  # additive only; nothing is dropped
