"""AI assistant: providers, settings, private conversations, messages. Additive: nothing is dropped."""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def _stamps():
    return [sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False)]


def upgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())   # a fresh 0001 already creates them
    if "ai_providers" not in tables:
        op.create_table(
            "ai_providers", sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.String(80), nullable=False),
            sa.Column("kind", sa.String(20), nullable=False, server_default="openai"),
            sa.Column("base_url", sa.String(300), nullable=False),
            sa.Column("api_key_enc", sa.Text),
            sa.Column("models", sa.JSON, nullable=False),
            sa.Column("default_model", sa.String(120)),
            sa.Column("is_enabled", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("deleted_at", TS), *_stamps())
    if "ai_settings" not in tables:
        op.create_table(
            "ai_settings", sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("role_enabled", sa.JSON, nullable=False),
            sa.Column("daily_limits", sa.JSON, nullable=False),
            sa.Column("max_context_chars", sa.Integer, nullable=False, server_default="60000"),
            sa.Column("max_output_tokens", sa.Integer, nullable=False, server_default="4000"),
            sa.Column("extra_instructions", sa.Text), *_stamps())
    if "ai_conversations" not in tables:
        op.create_table(
            "ai_conversations", sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("title", sa.String(160), nullable=False),
            sa.Column("task_id", sa.Integer, sa.ForeignKey("tasks.id", ondelete="SET NULL")),
            sa.Column("workspace_id", sa.Integer),
            sa.Column("model", sa.String(160)),
            sa.Column("deleted_at", TS), *_stamps())
        op.create_index("ix_ai_conversations_user_id", "ai_conversations", ["user_id"])
        op.create_index("ix_ai_conversations_task_id", "ai_conversations", ["task_id"])
    if "ai_messages" not in tables:
        op.create_table(
            "ai_messages", sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("conversation_id", sa.Integer, sa.ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("role", sa.String(10), nullable=False),
            sa.Column("content", sa.Text, nullable=False, server_default=""),
            sa.Column("context", sa.JSON),
            sa.Column("provider_id", sa.Integer),
            sa.Column("model", sa.String(120)),
            sa.Column("prompt_tokens", sa.Integer, nullable=False, server_default="0"),
            sa.Column("completion_tokens", sa.Integer, nullable=False, server_default="0"),
            sa.Column("status", sa.String(12), nullable=False, server_default="ok"),
            sa.Column("error", sa.String(300)),
            sa.Column("saved", sa.Boolean, nullable=False, server_default=sa.false()), *_stamps())
        op.create_index("ix_ai_messages_conversation_id", "ai_messages", ["conversation_id"])
        op.create_index("ix_ai_messages_user_id", "ai_messages", ["user_id"])


def downgrade():
    pass  # additive only; nothing is dropped
