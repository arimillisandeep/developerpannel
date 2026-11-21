"""Build 29: 8 h regular schedule vs the separate Continue schedule, and recording retention.
Additive: nothing is changed or dropped."""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())   # a fresh 0001 builds tables from the current models, so check before adding

    def add(table, column, type_, **kw):
        cols = {c["name"] for c in insp.get_columns(table)}
        if table in insp.get_table_names() and column not in cols:
            op.add_column(table, sa.Column(column, type_, **kw))

    add("work_sessions", "schedule", sa.String(10), nullable=False, server_default="regular")
    add("attendance", "extra_seconds", sa.Integer, nullable=False, server_default="0")
    add("attendance", "regular_completed_at", sa.DateTime(timezone=True))
    add("screen_recordings", "retention_until", sa.DateTime(timezone=True))


def downgrade():
    insp = sa.inspect(op.get_bind())
    for table, column in (("work_sessions", "schedule"), ("attendance", "extra_seconds"),
                          ("attendance", "regular_completed_at"), ("screen_recordings", "retention_until")):
        cols = {c["name"] for c in insp.get_columns(table)}
        if table in insp.get_table_names() and column in cols:
            op.drop_column(table, column)
