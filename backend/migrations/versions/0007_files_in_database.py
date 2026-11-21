"""Build 20: uploaded files and screen recordings are stored in the database instead of the storage folder.

Additive: nothing is dropped. Files that already exist in the storage folder are copied into the database;
the files on disk are left where they are (delete the folder yourself once you have checked the result)."""
import os
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

PIECE = 5_000_000   # recordings are copied in 5 MB pieces


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "data" not in {c["name"] for c in insp.get_columns("task_attachments")}:
        op.add_column("task_attachments", sa.Column("data", sa.LargeBinary))
    if "recording_chunks" not in insp.get_table_names():
        op.create_table(
            "recording_chunks",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("recording_id", sa.Integer, sa.ForeignKey("screen_recordings.id", ondelete="CASCADE"), nullable=False),
            sa.Column("seq", sa.Integer, nullable=False),
            sa.Column("size_bytes", sa.Integer, nullable=False),
            sa.Column("data", sa.LargeBinary, nullable=False),
            sa.UniqueConstraint("recording_id", "seq"),
        )
        op.create_index("ix_recording_chunks_recording_id", "recording_chunks", ["recording_id"])

    # copy existing files from disk into the database
    attachments = sa.table("task_attachments", sa.column("id"), sa.column("storage_path"), sa.column("data"))
    copied = missing = 0
    for row in bind.execute(sa.select(attachments.c.id, attachments.c.storage_path).where(attachments.c.data.is_(None))).fetchall():
        path = Path(row.storage_path or "")
        if row.storage_path and path.is_file():
            bind.execute(attachments.update().where(attachments.c.id == row.id).values(data=path.read_bytes(), storage_path="database"))
            copied += 1
        else:
            missing += 1

    recordings = sa.table("screen_recordings", sa.column("id"), sa.column("user_id"), sa.column("storage_path"))
    chunks = sa.table("recording_chunks", sa.column("recording_id"), sa.column("seq"), sa.column("size_bytes"), sa.column("data"))
    storage = Path(os.environ.get("STORAGE_DIR", "./storage")).resolve()
    videos = 0
    for row in bind.execute(sa.select(recordings.c.id, recordings.c.user_id, recordings.c.storage_path)).fetchall():
        if bind.execute(sa.select(sa.func.count()).select_from(chunks).where(chunks.c.recording_id == row.id)).scalar():
            continue
        candidates = [Path(row.storage_path or ""), storage / "recordings" / str(row.user_id) / f"{row.id}.webm"]
        path = next((p for p in candidates if str(p) not in ("", ".") and p.is_file()), None)
        if not path:
            continue
        with open(path, "rb") as video:
            seq = 0
            while True:
                piece = video.read(PIECE)
                if not piece:
                    break
                seq += 1
                bind.execute(chunks.insert().values(recording_id=row.id, seq=seq, size_bytes=len(piece), data=piece))
        bind.execute(recordings.update().where(recordings.c.id == row.id).values(storage_path="database"))
        videos += 1
    print(f"0007: copied into the database: {copied} attachment(s), {videos} recording(s); "
          f"{missing} attachment file(s) were not found on disk.")


def downgrade():
    # The files are not written back to disk. Only use this on a database without uploads you need.
    op.drop_index("ix_recording_chunks_recording_id", table_name="recording_chunks")
    op.drop_table("recording_chunks")
    with op.batch_alter_table("task_attachments") as batch:
        batch.drop_column("data")
