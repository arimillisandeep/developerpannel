"""API audit (build 19): token version on users + indexes on foreign-key columns. Additive: nothing is dropped."""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

# foreign-key columns that had no index (slow joins and slow parent deletes on a large database)
FK_INDEXES = [
    ("employee_profiles", "reporting_manager_id"), ("employee_profiles", "department_id"), ("employment_history", "changed_by"),
    ("intern_vacancies", "updated_by"), ("projects", "created_by"), ("website_allowlist", "created_by"),
    ("chat_conversations", "created_by"), ("meetings", "created_by"), ("activity_logs", "session_id"), ("chat_messages", "sender_id"),
    ("task_attachments", "uploaded_by"), ("task_assignments", "assigned_to"), ("task_assignments", "assigned_by"),
    ("workspaces", "project_id"), ("screen_recordings", "task_id"), ("screen_recordings", "session_id"), ("file_events", "user_id"),
    ("submissions", "workspace_id"), ("file_versions", "saved_by"), ("review_comments", "author_id"), ("review_comments", "review_id"),
]


def upgrade():
    insp = sa.inspect(op.get_bind())      # a fresh 0001 builds the tables from the current models, so check before adding
    if "token_version" not in {c["name"] for c in insp.get_columns("users")}:
        op.add_column("users", sa.Column("token_version", sa.Integer, nullable=False, server_default="0"))
    tables = set(insp.get_table_names())
    for table, column in FK_INDEXES:
        name = f"ix_{table}_{column}"
        if table in tables and name not in {i["name"] for i in insp.get_indexes(table)}:
            op.create_index(name, table, [column])


def downgrade():
    insp = sa.inspect(op.get_bind())
    for table, column in FK_INDEXES:
        name = f"ix_{table}_{column}"
        if name in {i["name"] for i in insp.get_indexes(table)}:
            op.drop_index(name, table_name=table)
    with op.batch_alter_table("users") as b:
        b.drop_column("token_version")
