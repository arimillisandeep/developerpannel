"""task workflow: reviewer, acceptance, 16 statuses, version labels, task history, attachments,
file events, task time; Developer role retired (developers become On-Roll). Additive: nothing is dropped."""
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def _stamps():
    return [sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False)]


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    def add(table, *cols):
        have = {c["name"] for c in insp.get_columns(table)}
        for col in cols:
            if col.name not in have:            # a fresh 0001 already creates them
                op.add_column(table, col)

    add("tasks", sa.Column("reviewer_id", sa.Integer), sa.Column("deliverables", sa.Text),
        sa.Column("group_code", sa.String(20)), sa.Column("accepted_at", TS), sa.Column("started_at", TS),
        sa.Column("cancelled_at", TS), sa.Column("archived_at", TS), sa.Column("reminded_on", sa.Date))
    add("submissions", sa.Column("version_label", sa.String(12)), sa.Column("note", sa.Text),
        sa.Column("changes", sa.JSON), sa.Column("authors", sa.JSON), sa.Column("decided_at", TS))
    add("work_sessions", sa.Column("task_id", sa.Integer))

    if "task_history" not in tables:
        op.create_table(
            "task_history", sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("task_id", sa.Integer, sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("user_role", sa.String(20)), sa.Column("action", sa.String(40), nullable=False),
            sa.Column("from_status", sa.String(30)), sa.Column("to_status", sa.String(30)),
            sa.Column("comment", sa.Text), sa.Column("submission_id", sa.Integer), *_stamps())
        op.create_index("ix_task_history_task_id", "task_history", ["task_id"])
        op.create_index("ix_task_history_user_id", "task_history", ["user_id"])
        op.create_index("ix_task_history_submission_id", "task_history", ["submission_id"])
    if "task_attachments" not in tables:
        op.create_table(
            "task_attachments", sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("task_id", sa.Integer, sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
            sa.Column("kind", sa.String(12), nullable=False), sa.Column("filename", sa.String(200), nullable=False),
            sa.Column("content_type", sa.String(100)), sa.Column("size_bytes", sa.Integer, nullable=False),
            sa.Column("storage_path", sa.String(400), nullable=False),
            sa.Column("uploaded_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("submission_id", sa.Integer), sa.Column("deleted_at", TS), *_stamps())
        op.create_index("ix_task_attachments_task_id", "task_attachments", ["task_id"])
    if "task_time" not in tables:
        op.create_table(
            "task_time", sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("task_id", sa.Integer, sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("active_seconds", sa.Integer, nullable=False, server_default="0"),
            sa.Column("paused_seconds", sa.Integer, nullable=False, server_default="0"),
            sa.Column("first_at", TS), sa.Column("last_at", TS), *_stamps(),
            sa.UniqueConstraint("task_id", "user_id"))
        op.create_index("ix_task_time_task_id", "task_time", ["task_id"])
        op.create_index("ix_task_time_user_id", "task_time", ["user_id"])
    if "file_events" not in tables:
        op.create_table(
            "file_events", sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("workspace_id", sa.Integer, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
            sa.Column("file_id", sa.Integer), sa.Column("path", sa.String(300), nullable=False),
            sa.Column("action", sa.String(12), nullable=False), sa.Column("from_path", sa.String(300)),
            sa.Column("prev_version_no", sa.Integer), sa.Column("version_no", sa.Integer),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("summary", sa.String(200)), sa.Column("submission_id", sa.Integer), *_stamps())
        op.create_index("ix_file_events_workspace_id", "file_events", ["workspace_id"])
        op.create_index("ix_file_events_file_id", "file_events", ["file_id"])

    # ---- existing data ------------------------------------------------------------------
    # review stage names
    op.execute("UPDATE submissions SET stage = 'onroll_review' WHERE stage = 'developer_review'")
    op.execute("UPDATE submissions SET status = 'pending_onroll_review' WHERE status = 'pending_developer_review'")
    op.execute("UPDATE reviews SET stage = 'onroll_review' WHERE stage = 'developer_review'")
    op.execute("UPDATE tasks SET review_status = 'pending_onroll_review' WHERE review_status = 'pending_developer_review'")
    op.execute("UPDATE submissions SET version_label = '1.' || CAST(version_no - 1 AS VARCHAR) WHERE version_label IS NULL")
    # task statuses -> the new list
    op.execute("UPDATE tasks SET status = 'in_progress' WHERE status = 'saved'")
    op.execute("UPDATE tasks SET status = 'rework_required' WHERE status = 'changes_requested'")
    op.execute("UPDATE tasks SET status = 'completed' WHERE status = 'approved'")
    op.execute("""UPDATE tasks SET status = 'under_admin_review' WHERE status IN ('submitted', 'under_review')
                  AND review_status = 'pending_admin_review'""")
    op.execute("UPDATE tasks SET status = 'under_onroll_review' WHERE status IN ('submitted', 'under_review')")
    op.execute("""UPDATE tasks SET status = 'admin_rejected' WHERE status = 'rejected' AND id IN (
                  SELECT s.task_id FROM submissions s JOIN reviews r ON r.submission_id = s.id
                  WHERE r.stage = 'admin_review' AND r.decision = 'rejected')""")
    op.execute("UPDATE tasks SET status = 'onroll_rejected' WHERE status = 'rejected'")

    # Developer role retired: developers become On-Roll. Their old profile row is kept; history is recorded.
    now = datetime.now(timezone.utc)
    devs = bind.execute(sa.text("SELECT id FROM users WHERE role = 'developer'")).fetchall()
    for (uid,) in devs:
        has = bind.execute(sa.text("SELECT 1 FROM employee_profiles WHERE user_id = :u"), {"u": uid}).first()
        if not has:
            old = bind.execute(sa.text("SELECT employee_code, joining_date, phone, compensation FROM developer_profiles "
                                       "WHERE user_id = :u"), {"u": uid}).first()
            code = old[0] if old else f"WC-E{uid:04d}"
            if bind.execute(sa.text("SELECT 1 FROM employee_profiles WHERE employee_code = :c"), {"c": code}).first():
                code = f"{code}-R"
            bind.execute(sa.text(
                "INSERT INTO employee_profiles (user_id, employee_code, category, joining_date, phone, compensation, "
                "employment_status, conversion_status, created_at, updated_at) VALUES (:u, :c, 'onroll', :j, :p, :m, "
                "'active', 'none', :n, :n)"),
                {"u": uid, "c": code, "j": old[1] if old else None, "p": old[2] if old else None,
                 "m": old[3] if old else None, "n": now})
        bind.execute(sa.text(
            "INSERT INTO employment_history (user_id, event, from_role, to_role, reason, effective_date, created_at, updated_at) "
            "VALUES (:u, 'converted', 'developer', 'onroll', 'Developer role retired (build 16)', :d, :n, :n)"),
            {"u": uid, "d": now.date(), "n": now})
        bind.execute(sa.text("UPDATE users SET role = 'onroll' WHERE id = :u"), {"u": uid})


def downgrade():
    pass  # additive only; nothing is dropped
