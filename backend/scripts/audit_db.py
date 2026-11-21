"""API audit step 4: database structure and consistency checks (read-only).

    AUDIT_DB=/tmp/audit/audit.db python scripts/audit_db.py
Works on a SQLite file. It only reads.
"""
import json, os, sqlite3, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB = os.environ.get("AUDIT_DB", "/tmp/audit/audit.db")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "audit")
c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True); R = []
def add(check, result, detail=""): R.append({"check": check, "result": result, "detail": str(detail)[:600]}); print(result, check, str(detail)[:300] if result != "PASS" else "")
tables = [r[0] for r in c.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")]
add(f"database opens; {len(tables)} tables", "PASS")
add("integrity_check", "PASS" if c.execute("pragma integrity_check").fetchone()[0] == "ok" else "FAIL")
fk = c.execute("pragma foreign_key_check").fetchall(); add("no row points to a missing parent (foreign_key_check)", "PASS" if not fk else "FAIL", fk[:10])
add("foreign keys enforced by the application connection", "PASS" if "foreign_keys" in open(os.path.join(os.path.dirname(__file__), "..", "app", "database", "connection.py")).read() else "WARNING", "SQLite ignores foreign keys unless PRAGMA foreign_keys=ON is set per connection")
nopk = [t for t in tables if t != "alembic_version" and not any(r[5] for r in c.execute(f"pragma table_info({t})"))]; add("every table has a primary key", "PASS" if not nopk else "FAIL", nopk)
# foreign-key columns without an index (slow joins / slow deletes on a big database)
missing = []
for t in tables:
    idx_cols = set()
    for i in c.execute(f"pragma index_list({t})"):
        cols = [x[2] for x in c.execute(f"pragma index_info({i[1]})")]
        if cols: idx_cols.add(cols[0])
    pk = {r[1] for r in c.execute(f"pragma table_info({t})") if r[5]}
    for f in c.execute(f"pragma foreign_key_list({t})"):
        if f[3] not in idx_cols and f[3] not in pk: missing.append(f"{t}.{f[3]}")
add("foreign-key columns have an index", "PASS" if not missing else "WARNING", f"{len(missing)} without index: " + ", ".join(missing))
dups = {}
for name, q in {"users.email": "select lower(email), count(*) from users group by 1 having count(*)>1",
                "tasks.code": "select code, count(*) from tasks group by 1 having count(*)>1",
                "live file path per workspace": "select workspace_id||':'||path, count(*) from workspace_files where deleted_at is null group by 1 having count(*)>1",
                "team member": "select team_id||':'||user_id, count(*) from team_members group by 1 having count(*)>1",
                "open work session per user": "select user_id, count(*) from work_sessions where ended_at is null group by 1 having count(*)>1",
                "attendance per user/day": "select user_id||':'||day, count(*) from attendance group by 1 having count(*)>1",
                "workspace per task": "select task_id, count(*) from workspaces group by 1 having count(*)>1",
                "submission version per task": "select task_id||':'||version_label, count(*) from submissions group by 1 having count(*)>1",
                "chat member": "select conversation_id||':'||user_id, count(*) from chat_members group by 1 having count(*)>1",
                "allowlist domain": "select domain, count(*) from website_allowlist group by 1 having count(*)>1",
                "file version number": "select file_id||':'||version_no, count(*) from file_versions group by 1 having count(*)>1"}.items():
    rows = c.execute(q).fetchall()
    if rows: dups[name] = rows[:5]
add("no duplicate records (11 uniqueness rules)", "PASS" if not dups else "FAIL", dups)
# does the database itself forbid these duplicates (unique constraint), or only the code?
uniq = {}
for t in tables:
    for i in c.execute(f"pragma index_list({t})"):
        if i[2]: uniq.setdefault(t, []).append(tuple(x[2] for x in c.execute(f"pragma index_info({i[1]})")))
want = {"users": ("email",), "tasks": ("code",), "team_members": ("team_id", "user_id"), "attendance": ("user_id", "day"), "workspaces": ("task_id", "user_id"),
        "chat_members": ("conversation_id", "user_id"), "website_allowlist": ("domain",), "file_versions": ("file_id", "version_no"), "departments": ("name",)}
soft = [f"{t}{cols}" for t, cols in want.items() if not any(set(cols) == set(u) for u in uniq.get(t, []))]
add("uniqueness is also enforced by a database constraint", "PASS" if not soft else "WARNING", "only the code prevents duplicates in: " + ", ".join(soft))
nulls = {}
for name, q in {"users without role/email/hash": "select count(*) from users where role is null or email is null or password_hash is null or password_hash=''",
                "tasks without assignee/status": "select count(*) from tasks where assigned_to is null or status is null",
                "submissions without task/submitter/label": "select count(*) from submissions where task_id is null or submitted_by is null or version_label is null",
                "task status outside the 16 allowed": "select count(*) from tasks where status not in ('created','assigned','accepted','in_progress','submitted','under_onroll_review','onroll_approved','onroll_rejected','under_admin_review','admin_approved','admin_rejected','rework_required','resubmitted','completed','cancelled','archived')",
                "role outside the 4 active roles": "select count(*) from users where role not in ('admin','onroll','offroll','intern')",
                "plain-text passwords": "select count(*) from users where password_hash not like '$2%'",
                "AI keys stored unencrypted": "select count(*) from ai_providers where api_key_enc like 'sk-%' or api_key_enc like 'AQ.%'",
                "completed task without an admin approval": "select count(*) from tasks t where t.status='completed' and not exists (select 1 from reviews r join submissions s on s.id=r.submission_id where s.task_id=t.id and r.stage like 'admin%' and r.decision='approved')",
                "negative timer seconds": "select count(*) from work_sessions where active_seconds<0 or paused_seconds<0 or idle_seconds<0"}.items():
    n = c.execute(q).fetchone()[0]
    if n: nulls[name] = n
add("no bad values (9 rules: nulls, roles, statuses, hashes, encrypted keys)", "PASS" if not nulls else "FAIL", nulls)
add("migration version", "PASS", c.execute("select version_num from alembic_version").fetchone()[0])
json.dump(R, open(os.path.join(OUT, f"db_{os.path.basename(DB)}.json"), "w"), indent=1)
