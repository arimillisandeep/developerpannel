import os
import tempfile

# Tests run on a throw-away SQLite file. To run them on PostgreSQL, set TEST_DATABASE_URL to an EMPTY database
# whose name contains "test": every test drops and recreates all tables in it.
_tmp = tempfile.mkdtemp()
_url = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_tmp}/test.db"
if not _url.startswith("sqlite") and "test" not in _url.rsplit("/", 1)[-1]:
    raise SystemExit("TEST_DATABASE_URL must point to a database with 'test' in its name (the tests delete all tables).")
os.environ["DATABASE_URL"] = _url
os.environ["STORAGE_DIR"] = os.path.join(_tmp, "storage")
os.environ["BCRYPT_ROUNDS"] = "4"
os.environ["JWT_SECRET"] = "test-secret-test-secret-test-secret-123"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.security import hash_password, login_limiter  # noqa: E402
from app.database import models  # noqa: E402
from app.database.connection import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402

PASSWORD = "Passw0rd!123"


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)   # test database only
    Base.metadata.create_all(engine)
    login_limiter.reset()
    db = SessionLocal()
    admin = models.User(email="admin@wc.test", full_name="Root Admin", role="admin",
                        password_hash=hash_password(PASSWORD))
    db.add(admin)
    db.flush()
    db.add(models.AdminProfile(user_id=admin.id))
    db.commit()
    db.close()
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


class Actor:
    def __init__(self, client, email, password=PASSWORD):
        self.client = client
        r = client.post("/api/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        self.user = r.json()["user"]
        self.id = self.user["id"]
        self.token = r.json()["access_token"]
        self.h = {"Authorization": f"Bearer {self.token}"}

    def get(self, url, **kw):
        return self.client.get(url, headers=self.h, **kw)

    def post(self, url, json=None, **kw):
        return self.client.post(url, headers=self.h, json=json, **kw)

    def put(self, url, json=None):
        return self.client.put(url, headers=self.h, json=json)

    def patch(self, url, json=None):
        return self.client.patch(url, headers=self.h, json=json)

    def delete(self, url):
        return self.client.delete(url, headers=self.h)


@pytest.fixture
def admin(client):
    return Actor(client, "admin@wc.test")


@pytest.fixture
def make_user(client, admin):
    def _make(role, name=None, **extra):
        name = name or f"{role} user"
        email = f"{name.replace(' ', '.').lower()}@wc.test"
        r = admin.post("/api/users", {"email": email, "password": PASSWORD, "full_name": name,
                                      "role": role, **extra})
        assert r.status_code == 201, r.text
        return Actor(client, email)
    return _make


@pytest.fixture
def org(admin, make_user):
    """One developer leading a team with an on-roll, an off-roll and an intern; plus outsiders."""
    dev = make_user("onroll", "Dev One")          # On-Roll team lead and reviewer
    onroll = make_user("onroll", "Onroll One")
    offroll = make_user("offroll", "Offroll One")
    intern = make_user("intern", "Intern One")
    other_dev = make_user("onroll", "Dev Two")
    outsider = make_user("intern", "Intern Two")  # in Dev Two's team
    t1 = admin.post("/api/teams", {"name": "Alpha", "lead_developer_id": dev.id}).json()
    t2 = admin.post("/api/teams", {"name": "Beta", "lead_developer_id": other_dev.id}).json()
    for u in (onroll, offroll, intern):
        assert admin.post(f"/api/teams/{t1['id']}/members", {"user_id": u.id}).status_code == 201
    assert admin.post(f"/api/teams/{t2['id']}/members", {"user_id": outsider.id}).status_code == 201

    class O:
        pass
    o = O()
    o.admin, o.dev, o.onroll, o.offroll, o.intern, o.other_dev, o.outsider = (
        admin, dev, onroll, offroll, intern, other_dev, outsider)
    return o


def assign(actor, to, title="Build login page"):
    return actor.post("/api/tasks", {"title": title, "assigned_to": to.id, "requirements": "Do it well"})


def work_and_submit(actor, task_id, content="print('hi')"):
    actor.post(f"/api/tasks/{task_id}/accept")
    ws = actor.get(f"/api/tasks/{task_id}/workspace")
    assert ws.status_code == 200, ws.text
    wid = ws.json()["id"]
    r = actor.put(f"/api/workspaces/{wid}/files", {"path": "main.py", "content": content, "manual": True})
    assert r.status_code == 200, r.text
    r = actor.post(f"/api/workspaces/{wid}/submit")
    return wid, r
