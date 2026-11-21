"""automatic timer: session mode + extension fields, timer_events, website_allowlist (additive only)"""
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

DEFAULT_SITES = [("meet.google.com", "Google Meet", True), ("chatgpt.com", "ChatGPT", False), ("www.chatgpt.com", "ChatGPT", False)]


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    have = {c["name"] for c in insp.get_columns("work_sessions")}
    new_columns = [
        sa.Column("mode", sa.String(20), nullable=False, server_default="RUNNING"),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ext_category", sa.String(12), nullable=True),
        sa.Column("ext_domain", sa.String(120), nullable=True),
        sa.Column("ext_idle", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ext_at", sa.DateTime(timezone=True), nullable=True),
    ]
    for col in new_columns:                      # a fresh 0001 already creates them
        if col.name not in have:
            op.add_column("work_sessions", col)
    stamps = lambda: [sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
                      sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]
    if "timer_events" not in tables:
        op.create_table(
            "timer_events",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("session_id", sa.Integer, sa.ForeignKey("work_sessions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("from_state", sa.String(20)), sa.Column("to_state", sa.String(20), nullable=False),
            sa.Column("reason", sa.String(30), nullable=False), sa.Column("category", sa.String(20)), *stamps())
        op.create_index("ix_timer_events_user_id", "timer_events", ["user_id"])
        op.create_index("ix_timer_events_session_id", "timer_events", ["session_id"])
        op.create_index("ix_timer_events_at", "timer_events", ["at"])
    if "website_allowlist" not in tables:
        op.create_table(
            "website_allowlist",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("domain", sa.String(120), nullable=False, unique=True),
            sa.Column("label", sa.String(80)),
            sa.Column("ignore_inactivity", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")), *stamps())
    # default approved sites, only when the list has never been filled
    t = sa.table("website_allowlist", sa.column("domain"), sa.column("label"), sa.column("ignore_inactivity"),
                 sa.column("created_at", sa.DateTime(timezone=True)), sa.column("updated_at", sa.DateTime(timezone=True)))
    if bind.execute(sa.select(sa.func.count()).select_from(t)).scalar() == 0:
        now = datetime.now(timezone.utc)
        op.bulk_insert(t, [{"domain": d, "label": l, "ignore_inactivity": i, "created_at": now, "updated_at": now}
                           for d, l, i in DEFAULT_SITES])
    # existing rows: give old sessions the state they really have
    op.execute("UPDATE work_sessions SET mode = 'STOPPED' WHERE state = 'ended' AND mode = 'RUNNING' AND (end_reason IS NULL OR end_reason <> 'stale')")
    op.execute("UPDATE work_sessions SET mode = 'SESSION_EXPIRED' WHERE state = 'ended' AND mode = 'RUNNING' AND end_reason = 'stale'")
    op.execute("UPDATE work_sessions SET mode = 'PAUSED_MANUAL' WHERE state = 'paused' AND mode = 'RUNNING'")


def downgrade():
    pass  # additive only; nothing is dropped
