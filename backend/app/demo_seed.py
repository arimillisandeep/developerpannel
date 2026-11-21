"""OPTIONAL demo accounts for trying the app on a development database.

    python -m app.demo_seed

Creates one account per role (password: Workcode@123), one team, one project and two tasks,
all through the real API. It refuses to run if the database already has users, so it can
never touch real company data. Do not use on production.
"""
import sys

from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.database.connection import Base, SessionLocal, engine
from app.database.models import AdminProfile, EmploymentHistory, InternVacancy, User
from app.main import app

PASSWORD = "Workcode@123"


def main():
    Base.metadata.create_all(engine, checkfirst=True)
    db = SessionLocal()
    if db.query(User).count():
        sys.exit("Database already has users - demo seed skipped.")
    admin = User(email="admin@workcode.local", full_name="Arun Kumar", role="admin",
                 password_hash=hash_password(PASSWORD))
    db.add(admin)
    db.flush()
    db.add_all([AdminProfile(user_id=admin.id), InternVacancy(target_headcount=10),
                EmploymentHistory(user_id=admin.id, event="joined", to_role="admin")])
    db.commit()
    db.close()

    c = TestClient(app)

    def login(email):
        token = c.post("/api/auth/login", json={"email": email, "password": PASSWORD}).json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    a = login("admin@workcode.local")
    ids = {}
    for key, role, name in [("reviewer", "onroll", "Divya Rao"), ("onroll", "onroll", "Ravi Teja"),
                            ("offroll", "offroll", "Sandeep K"), ("intern", "intern", "Kabir Singh")]:
        r = c.post("/api/users", headers=a, json={"email": f"{key}@workcode.local", "password": PASSWORD,
                                                  "full_name": name, "role": role})
        r.raise_for_status()
        ids[key] = r.json()["id"]
    team = c.post("/api/teams", headers=a, json={"name": "Platform team", "lead_developer_id": ids["reviewer"]}).json()
    for role in ("onroll", "offroll", "intern"):
        c.post(f"/api/teams/{team['id']}/members", headers=a, json={"user_id": ids[role]})
    project = c.post("/api/projects", headers=a, json={"name": "WORKCODE website"}).json()
    c.post("/api/tasks", headers=a, json={"title": "Build the landing page", "assigned_to": ids["intern"],
                                          "project_id": project["id"], "priority": "high",
                                          "requirements": "Create index.html and style.css for the landing page.",
                                          "reviewer_id": ids["reviewer"]})
    c.post("/api/tasks", headers=login("reviewer@workcode.local"),
           json={"title": "Write the contact form validation", "assigned_to": ids["offroll"],
                 "project_id": project["id"], "requirements": "Validate name, email and message in JavaScript."})
    print("Demo data created. Sign in with <role>@workcode.local /", PASSWORD,
          "(admin, reviewer = On-Roll team lead, onroll, offroll, intern)")


if __name__ == "__main__":
    main()
