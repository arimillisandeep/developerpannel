"""Forgot password (build 26): table for the hashed, single-use reset links. Additive: nothing is changed or dropped."""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())      # a fresh 0001 builds the tables from the current models, so check before adding
    if "password_reset_tokens" in insp.get_table_names():
        return
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("requested_ip", sa.String(64)),
    )
    op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])
    op.create_index("ix_password_reset_tokens_token_hash", "password_reset_tokens", ["token_hash"], unique=True)


def downgrade():
    op.drop_table("password_reset_tokens")
