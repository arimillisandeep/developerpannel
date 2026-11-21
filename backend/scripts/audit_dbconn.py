"""Database access for the audit scripts. SQLite file by default (AUDIT_DB); PostgreSQL when AUDIT_DB_URL is set,
for example  AUDIT_DB_URL=postgresql://postgres:secret@127.0.0.1:5432/workcode_audit"""
import os
import sqlite3

URL = os.environ.get("AUDIT_DB_URL", "")


def rows(query, args=(), as_dict=False):
    """Run a read query with ? placeholders and return all rows (tuples, or dicts when as_dict is set)."""
    if URL:
        import psycopg2
        import psycopg2.extras
        con = psycopg2.connect(URL.replace("postgresql+psycopg2://", "postgresql://"))
        try:
            cur = con.cursor(cursor_factory=psycopg2.extras.RealDictCursor if as_dict else None)
            cur.execute(query.replace("%", "%%").replace("?", "%s"), tuple(args))
            found = cur.fetchall()
            return [dict(r) for r in found] if as_dict else [tuple(r) for r in found]
        finally:
            con.close()
    con = sqlite3.connect(os.environ.get("AUDIT_DB", "/tmp/audit/audit.db"))
    if as_dict:
        con.row_factory = sqlite3.Row
    try:
        found = con.execute(query, tuple(args)).fetchall()
        return [dict(r) for r in found] if as_dict else found
    finally:
        con.close()
