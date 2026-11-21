"""GET /api/health/db: the one URL that says which layer is broken when every page says "Request failed (500)"."""
from app import main


def test_health_db_answers_with_counts(client, admin):
    body = client.get("/api/health/db").json()
    assert body["status"] == "ok"
    assert body["users"] >= 1                      # the admin fixture created one
    assert "schema" in body                        # None on a test database that was never migrated


def test_health_db_names_a_database_failure(client, monkeypatch):
    class Broken:
        def execute(self, *args, **kwargs):
            raise RuntimeError('connection to server at "db" (172.18.0.2), port 5432 failed: '
                               'FATAL:  password authentication failed for user "postgres"')

        def close(self):
            pass

    monkeypatch.setattr(main, "SessionLocal", lambda: Broken())
    answer = client.get("/api/health/db")
    assert answer.status_code == 503
    detail = answer.json()["detail"]
    assert detail.startswith("Database problem:")
    assert "password authentication failed" in detail


def test_health_db_never_shows_a_password(client, monkeypatch):
    class Broken:
        def execute(self, *args, **kwargs):
            raise RuntimeError("could not connect: postgresql://postgres:sup3rsecret@127.0.0.1:5432/workcode_v2")

        def close(self):
            pass

    monkeypatch.setattr(main, "SessionLocal", lambda: Broken())
    detail = client.get("/api/health/db").json()["detail"]
    assert "Database problem:" in detail
    assert "sup3rsecret" not in detail              # a connection string is scrubbed before it is shown
    assert "127.0.0.1:5432/workcode_v2" in detail   # the rest of the reason is kept: that is the useful part


def test_health_db_is_reachable_without_signing_in(client):
    assert client.get("/api/health/db").status_code == 200


def test_health_version_says_which_code_is_running(client):
    body = client.get("/api/health/version").json()
    assert body["build"].startswith("build ")
    assert "workspace-read-only-for-reviewers" in body["fixes"]
