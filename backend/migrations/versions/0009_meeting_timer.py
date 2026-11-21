"""Meeting timer (build 27): table for join / leave times of external meetings. Additive: nothing is changed or dropped."""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())      # a fresh 0001 builds the tables from the current models, so check before adding
    if "meeting_attendance" in insp.get_table_names():
        return
    op.create_table(
        "meeting_attendance",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("meeting_id", sa.Integer, sa.ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("left_at", sa.DateTime(timezone=True)),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(15), nullable=False, server_default="manual"),
        sa.Column("end_reason", sa.String(20)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_meeting_attendance_meeting_id", "meeting_attendance", ["meeting_id"])
    op.create_index("ix_meeting_attendance_user_id", "meeting_attendance", ["user_id"])
    op.create_index("ix_meeting_attendance_joined_at", "meeting_attendance", ["joined_at"])


def downgrade():
    op.drop_table("meeting_attendance")
