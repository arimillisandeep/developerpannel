"""Build 36: "Open" on a reference file — into the coding workspace, or as a preview (34-16 base)."""
from app.database.connection import SessionLocal
from app.database.models import FileVersion, Workspace, WorkspaceFile
from tests.conftest import assign


def upload(actor, task_id, name, data):
    r = actor.client.post(f"/api/tasks/{task_id}/attachments", headers=actor.h,
                          files={"file": (name, data, "application/octet-stream")})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_a_code_reference_becomes_an_editable_file_in_the_workspace(org):
    t = assign(org.dev, org.intern).json()
    org.intern.post(f"/api/tasks/{t['id']}/accept")
    aid = upload(org.dev, t["id"], "starter.py", b'print("from the assigner")\n')
    r = org.intern.post(f"/api/tasks/{t['id']}/attachments/{aid}/open")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "editor" and body["path"] == "starter.py"
    assert body["url"] == f"/workspace/{t['id']}?file=starter.py"
    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter_by(task_id=t["id"], user_id=org.intern.id).first()
        f = db.query(WorkspaceFile).filter_by(workspace_id=ws.id, path="starter.py").first()
        assert f.content == 'print("from the assigner")\n'
        assert db.query(FileVersion).filter_by(file_id=f.id).count() == 1
    finally:
        db.close()


def test_the_assigner_can_keep_uploading_the_original_stays_untouched(org):
    """Editing the copy must never change what the assigner uploaded."""
    t = assign(org.dev, org.intern).json()
    org.intern.post(f"/api/tasks/{t['id']}/accept")
    aid = upload(org.dev, t["id"], "spec.md", b"# Requirements\n- one\n")
    org.intern.post(f"/api/tasks/{t['id']}/attachments/{aid}/open")
    ws = org.intern.get(f"/api/tasks/{t['id']}/workspace").json()
    org.intern.put(f"/api/workspaces/{ws['id']}/files",
                   {"path": "spec.md", "content": "# Requirements\n- one\n- two (mine)\n", "manual": True})
    again = org.intern.get(f"/api/tasks/{t['id']}/attachments/{aid}")
    assert again.content == b"# Requirements\n- one\n", "the reference must be unchanged"
    ws2 = org.intern.get(f"/api/tasks/{t['id']}/workspace").json()
    mine = [f for f in ws2["files"] if f["path"] == "spec.md"][0]
    assert "two (mine)" in mine["content"]


def test_opening_the_same_file_twice_does_not_overwrite_your_work(org):
    t = assign(org.dev, org.intern).json()
    org.intern.post(f"/api/tasks/{t['id']}/accept")
    aid = upload(org.dev, t["id"], "app.js", b"console.log(1)\n")
    first = org.intern.post(f"/api/tasks/{t['id']}/attachments/{aid}/open").json()
    ws = org.intern.get(f"/api/tasks/{t['id']}/workspace").json()
    org.intern.put(f"/api/workspaces/{ws['id']}/files",
                   {"path": "app.js", "content": "console.log(2)  // my work\n", "manual": True})
    second = org.intern.post(f"/api/tasks/{t['id']}/attachments/{aid}/open").json()
    assert first["path"] == "app.js" and second["path"] == "ref-1-app.js"
    ws2 = org.intern.get(f"/api/tasks/{t['id']}/workspace").json()
    assert "my work" in [f for f in ws2["files"] if f["path"] == "app.js"][0]["content"]


def test_a_pdf_is_opened_as_a_preview_not_copied(org):
    t = assign(org.dev, org.intern).json()
    org.intern.post(f"/api/tasks/{t['id']}/accept")
    aid = upload(org.dev, t["id"], "design.pdf", b"%PDF-1.4 fake but fine")
    body = org.intern.post(f"/api/tasks/{t['id']}/attachments/{aid}/open").json()
    assert body["mode"] == "preview" and body["url"].endswith(f"/attachments/{aid}")
    ws = org.intern.get(f"/api/tasks/{t['id']}/workspace").json()
    assert all(f["path"] != "design.pdf" for f in ws["files"]), "a PDF must not become a workspace file"


def test_a_zip_keeps_download_only(org):
    t = assign(org.dev, org.intern).json()
    org.intern.post(f"/api/tasks/{t['id']}/accept")
    aid = upload(org.dev, t["id"], "assets.zip", b"PK\x03\x04something")
    body = org.intern.post(f"/api/tasks/{t['id']}/attachments/{aid}/open").json()
    assert body["mode"] == "download" and "cannot be edited" in body["detail"]


def test_only_the_assignee_gets_an_editable_copy(org):
    t = assign(org.dev, org.intern).json()
    org.intern.post(f"/api/tasks/{t['id']}/accept")
    aid = upload(org.dev, t["id"], "notes.txt", b"hello\n")
    body = org.dev.post(f"/api/tasks/{t['id']}/attachments/{aid}/open").json()   # the assigner, not the assignee
    assert body["mode"] == "read_only" and body["content"] == "hello\n"
    db = SessionLocal()
    try:
        assert db.query(WorkspaceFile).filter_by(path="notes.txt").count() == 0
    finally:
        db.close()


def test_an_outsider_cannot_open_the_file_at_all(org):
    t = assign(org.dev, org.intern).json()
    org.intern.post(f"/api/tasks/{t['id']}/accept")
    aid = upload(org.dev, t["id"], "notes.txt", b"hello\n")
    assert org.outsider.post(f"/api/tasks/{t['id']}/attachments/{aid}/open").status_code in (403, 404)


def test_a_locked_task_refuses_to_open_into_the_workspace(org):
    t = assign(org.dev, org.intern).json()
    aid = upload(org.dev, t["id"], "notes.txt", b"hello\n")     # task not accepted yet
    assert org.intern.post(f"/api/tasks/{t['id']}/attachments/{aid}/open").status_code == 409


def test_the_task_screen_is_told_which_button_to_draw(org):
    """The browser keeps no list of extensions: open_mode comes with the file."""
    t = assign(org.dev, org.intern).json()
    code = upload(org.dev, t["id"], "starter.py", b"print(1)\n")
    pdf = upload(org.dev, t["id"], "design.pdf", b"%PDF-1.4")
    zip_ = upload(org.dev, t["id"], "assets.zip", b"PK\x03\x04")
    got = {a["id"]: a["open_mode"] for a in org.dev.get(f"/api/tasks/{t['id']}").json()["attachments"]}
    assert got == {code: "editor", pdf: "preview", zip_: "download"}
