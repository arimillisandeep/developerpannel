"""Tests added by the API audit (build 19). Each one covers a problem that the audit found with a real request."""
from sqlalchemy import inspect, text

from app.database.connection import engine
from tests.conftest import PASSWORD, Actor

NEW_PASSWORD = "Changed!Passw0rd9"


def test_token_stops_working_after_logout(client, make_user):
    intern = make_user("intern", "Logout Person")
    assert intern.get("/api/auth/me").status_code == 200
    assert intern.post("/api/auth/logout").status_code == 200
    assert intern.get("/api/auth/me").status_code == 401          # the same token, used again
    assert intern.get("/api/tasks").status_code == 401
    again = Actor(client, intern.user["email"])                    # a new login works normally
    assert again.get("/api/auth/me").status_code == 200


def test_password_change_ends_old_tokens_and_returns_a_new_one(client, make_user):
    first = make_user("offroll", "Two Browsers")
    second = Actor(client, first.user["email"])                    # the same person in a second browser
    r = first.post("/api/auth/change-password", {"current_password": PASSWORD, "new_password": NEW_PASSWORD})
    assert r.status_code == 200 and r.json()["access_token"]
    assert second.get("/api/auth/me").status_code == 401
    assert first.get("/api/auth/me").status_code == 401            # the old token of this browser too
    fresh = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/api/auth/me", headers=fresh).status_code == 200
    assert client.post("/api/auth/login", json={"email": first.user["email"], "password": PASSWORD}).status_code == 401
    assert Actor(client, first.user["email"], NEW_PASSWORD).get("/api/auth/me").status_code == 200


def test_admin_password_reset_signs_the_person_out(admin, make_user):
    intern = make_user("intern", "Reset Person")
    assert admin.patch(f"/api/users/{intern.id}", {"new_password": NEW_PASSWORD}).status_code == 200
    assert intern.get("/api/auth/me").status_code == 401
    assert admin.get("/api/auth/me").status_code == 200            # the admin's own token is not touched


def test_other_profile_edits_do_not_sign_the_person_out(admin, make_user):
    intern = make_user("intern", "Edit Person")
    assert admin.patch(f"/api/users/{intern.id}", {"full_name": "Edited Person"}).status_code == 200
    assert intern.get("/api/auth/me").json()["full_name"] == "Edited Person"


def test_extension_token_survives_logout_but_is_never_a_login_token(client, make_user):
    intern = make_user("intern", "Extension Person")
    token = intern.post("/api/extension/token").json()["token"]
    intern.post("/api/auth/logout")
    h = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/extension/config", headers=h).status_code == 200
    assert client.get("/api/auth/me", headers=h).status_code == 401


def test_activity_of_unknown_user_is_404(admin, make_user):
    intern = make_user("intern", "Known Person")
    assert admin.get(f"/api/users/{intern.id}/activity").status_code == 200
    assert admin.get("/api/users/999999/activity").status_code == 404


def test_report_with_end_before_start_is_refused(admin):
    r = admin.get("/api/reports/summary?start=2026-02-01&end=2026-01-01")
    assert r.status_code == 422 and "end date" in r.json()["detail"]
    assert admin.get("/api/reports/summary?start=2026-01-01&end=2026-02-01").status_code == 200
    assert admin.get("/api/reports/summary").status_code == 200


def test_debug_endpoint_does_not_exist_outside_the_hosted_preview(client):
    assert client.post("/api/debug/client", content=b"x" * 100_000).status_code in (404, 405)


def test_sqlite_enforces_foreign_keys():
    if engine.dialect.name != "sqlite":
        return      # PostgreSQL always enforces foreign keys
    with engine.connect() as c:
        assert c.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_every_foreign_key_column_has_an_index():
    insp = inspect(engine)
    missing = []
    for table in insp.get_table_names():
        first_columns = {i["column_names"][0] for i in insp.get_indexes(table)}
        first_columns |= {u["column_names"][0] for u in insp.get_unique_constraints(table)}
        first_columns |= set(insp.get_pk_constraint(table)["constrained_columns"][:1])
        for fk in insp.get_foreign_keys(table):
            if fk["constrained_columns"][0] not in first_columns:
                missing.append(f"{table}.{fk['constrained_columns'][0]}")
    assert missing == []
