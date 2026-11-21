"""Build 20: uploaded files and screen recordings are stored in the database, nothing is written to the storage folder."""
import os

from app.core.config import settings
from app.database.connection import SessionLocal
from app.database.models import RecordingChunk, ScreenRecording, TaskAttachment
from tests.conftest import assign

WEBM = b"\x1a\x45\xdf\xa3"


def storage_files():
    return [name for _, _, names in os.walk(settings.STORAGE_DIR) for name in names]


def test_attachment_is_stored_in_the_database_and_downloads_identically(org, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    tid = assign(org.admin, org.intern).json()["id"]
    content = bytes(range(256)) * 40                               # binary data, not only text
    r = org.admin.client.post(f"/api/tasks/{tid}/attachments", headers=org.admin.h,
                              files={"file": ("spec \"v1\".pdf", content, "application/pdf")})
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    db = SessionLocal()
    row = db.get(TaskAttachment, aid)
    assert row.data == content and row.storage_path == "database" and row.size_bytes == len(content)
    db.close()
    assert storage_files() == []
    got = org.intern.get(f"/api/tasks/{tid}/attachments/{aid}")
    assert got.status_code == 200 and got.content == content
    assert "attachment" in got.headers["content-disposition"] and got.headers["x-content-type-options"] == "nosniff"
    assert "data" not in r.json()                                   # the file bytes never appear in JSON answers
    assert org.outsider.get(f"/api/tasks/{tid}/attachments/{aid}").status_code == 403


def test_attachment_uploaded_before_build_20_is_still_read_from_disk(org, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    tid = assign(org.admin, org.intern).json()["id"]
    folder = tmp_path / "attachments" / str(tid)
    folder.mkdir(parents=True)
    (folder / "abc123").write_bytes(b"old upload")
    db = SessionLocal()
    old = TaskAttachment(task_id=tid, kind="reference", filename="old.txt", size_bytes=10,
                         storage_path=str(folder / "abc123"), uploaded_by=org.admin.id)
    db.add(old)
    db.commit()
    aid = old.id
    db.close()
    assert org.intern.get(f"/api/tasks/{tid}/attachments/{aid}").content == b"old upload"


def test_recording_chunks_are_stored_in_order_and_play_back_identically(org, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    rid = org.intern.post("/api/recordings/start", {"consent": True}).json()["id"]
    parts = [WEBM + b"first" * 1000, b"second" * 2000, bytes(range(256)) * 10]
    for part in parts:
        r = org.intern.client.post(f"/api/recordings/{rid}/chunk", headers=org.intern.h, content=part)
        assert r.status_code == 200, r.text
    assert org.intern.post(f"/api/recordings/{rid}/stop").json()["status"] == "completed"
    db = SessionLocal()
    rows = db.query(RecordingChunk).filter_by(recording_id=rid).order_by(RecordingChunk.seq).all()
    assert [(c.seq, c.size_bytes) for c in rows] == [(1, len(parts[0])), (2, len(parts[1])), (3, len(parts[2]))]
    assert db.get(ScreenRecording, rid).size_bytes == sum(len(p) for p in parts)
    db.close()
    assert storage_files() == []
    video = org.intern.get(f"/api/recordings/{rid}/file")
    assert video.status_code == 200 and video.content == b"".join(parts)
    assert video.headers["content-length"] == str(sum(len(p) for p in parts))
    assert org.admin.get(f"/api/recordings/{rid}/file").content == b"".join(parts)
    assert org.outsider.get(f"/api/recordings/{rid}/file").status_code == 404
    assert org.intern.client.post(f"/api/recordings/{rid}/chunk", headers=org.intern.h, content=b"late").status_code == 409


def test_recording_made_before_build_20_is_still_read_from_disk(org, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    rid = org.intern.post("/api/recordings/start", {"consent": True}).json()["id"]
    folder = tmp_path / "recordings" / str(org.intern.id)
    folder.mkdir(parents=True)
    (folder / f"{rid}.webm").write_bytes(WEBM + b"old video")
    assert org.intern.get(f"/api/recordings/{rid}/file").content == WEBM + b"old video"
