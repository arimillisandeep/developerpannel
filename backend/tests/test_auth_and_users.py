from tests.conftest import PASSWORD


def test_login_success_and_me(client, admin):
    r = admin.get("/api/auth/me")
    assert r.status_code == 200 and r.json()["role"] == "admin"


def test_login_wrong_password(client):
    r = client.post("/api/auth/login", json={"email": "admin@wc.test", "password": "nope"})
    assert r.status_code == 401


def test_requests_without_token_are_rejected(client):
    for url in ("/api/auth/me", "/api/tasks", "/api/users", "/api/notifications", "/api/dashboard/admin"):
        assert client.get(url).status_code == 401
    assert client.get("/api/tasks", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_login_rate_limit(client):
    codes = [client.post("/api/auth/login", json={"email": "x@wc.test", "password": "bad"}).status_code
             for _ in range(12)]
    assert codes[0] == 401 and codes[-1] == 429


def test_employee_crud_and_audit(client, admin, make_user):
    u = make_user("offroll", "Sandeep K", compensation=15000)
    assert u.user["employee_code"].startswith("WC-E")
    assert u.user["contract_end"] is not None  # six-month training period set automatically
    r = admin.patch(f"/api/users/{u.id}", {"full_name": "Sandeep Kumar", "phone": "999"})
    assert r.status_code == 200 and r.json()["full_name"] == "Sandeep Kumar"
    logs = admin.get("/api/audit-logs?action=user.update").json()
    assert logs[0]["previous_value"]["full_name"] == "Sandeep K"
    assert logs[0]["new_value"]["full_name"] == "Sandeep Kumar"
    assert logs[0]["actor_id"] == admin.id and logs[0]["ip_address"]
    # duplicate email
    r = admin.post("/api/users", {"email": "sandeep.k@wc.test", "password": PASSWORD,
                                  "full_name": "Dup", "role": "intern"})
    assert r.status_code == 409


def test_deactivated_user_cannot_login_or_use_token(client, admin, make_user):
    u = make_user("intern", "Gone Soon")
    assert admin.post(f"/api/users/{u.id}/deactivate", {"status": "left"}).status_code == 200
    assert u.get("/api/auth/me").status_code == 401
    r = client.post("/api/auth/login", json={"email": "gone.soon@wc.test", "password": PASSWORD})
    assert r.status_code == 403


def test_only_three_admins(admin):
    for i in range(2):
        r = admin.post("/api/users", {"email": f"a{i}@wc.test", "password": PASSWORD,
                                      "full_name": f"Admin {i}", "role": "admin"})
        assert r.status_code == 201
    r = admin.post("/api/users", {"email": "a9@wc.test", "password": PASSWORD,
                                  "full_name": "Admin Nine", "role": "admin"})
    assert r.status_code == 409


def test_admin_cannot_deactivate_self(admin):
    assert admin.post(f"/api/users/{admin.id}/deactivate", {}).status_code == 409


def test_non_admins_cannot_manage_people(org):
    for actor in (org.dev, org.onroll, org.offroll, org.intern):
        r = actor.post("/api/users", {"email": "h@wc.test", "password": PASSWORD,
                                      "full_name": "Hacker", "role": "admin"})
        assert r.status_code == 403
        assert actor.patch(f"/api/users/{org.intern.id}", {"full_name": "Changed"}).status_code == 403
        assert actor.post(f"/api/users/{org.intern.id}/convert", {"to_role": "onroll"}).status_code == 403
        assert actor.get("/api/audit-logs").status_code == 403
        assert actor.get("/api/dashboard/admin").status_code == 403
    for actor in (org.offroll, org.intern):
        assert actor.get("/api/users").status_code == 403
    # an On-Roll employee sees only the members of a team they lead
    assert org.onroll.get("/api/users").json() == []
    assert {u["id"] for u in org.dev.get("/api/users").json()} == {org.onroll.id, org.offroll.id, org.intern.id}


def test_private_profile_data_is_restricted(org, admin):
    admin.patch(f"/api/users/{org.offroll.id}", {"compensation": 20000})
    # another employee cannot open the profile at all
    assert org.intern.get(f"/api/users/{org.offroll.id}").status_code == 403
    # the team's developer sees the profile but not compensation
    r = org.dev.get(f"/api/users/{org.offroll.id}")
    assert r.status_code == 200 and "compensation" not in r.json()
    # a developer of another team cannot see it
    assert org.other_dev.get(f"/api/users/{org.offroll.id}").status_code == 403
    assert org.offroll.get(f"/api/users/{org.offroll.id}").json()["compensation"] == 20000


def test_developer_lists_only_own_team(org):
    ids = {u["id"] for u in org.dev.get("/api/users").json()}
    assert ids == {org.onroll.id, org.offroll.id, org.intern.id}


def test_intern_vacancy_updates_automatically(admin, make_user, client):
    admin.put("/api/intern-vacancy", {"target_headcount": 2})
    a = make_user("intern", "In A")
    make_user("intern", "In B")
    assert admin.get("/api/users/intern-headcount").json() == {"target": 2, "filled": 2, "vacant": 0}
    r = admin.post("/api/users", {"email": "c@wc.test", "password": PASSWORD, "full_name": "In C",
                                  "role": "intern"})
    assert r.status_code == 409
    # converting an intern frees a seat
    assert admin.post(f"/api/users/{a.id}/convert", {"to_role": "onroll", "confirm_early": True}).status_code == 200
    assert admin.get("/api/users/intern-headcount").json()["vacant"] == 1


def test_conversion_requires_confirmation_when_early(admin, make_user):
    u = make_user("offroll", "Early Bird")
    assert admin.post(f"/api/users/{u.id}/convert", {"to_role": "onroll"}).status_code == 409
    assert admin.post(f"/api/users/{u.id}/convert", {"to_role": "intern"}).status_code == 422
    old = make_user("offroll", "Old Hand", joining_date="2020-01-01")
    r = admin.post(f"/api/users/{old.id}/convert", {"to_role": "onroll"})
    assert r.status_code == 200 and r.json()["role"] == "onroll" and r.json()["contract_end"] is None


def test_token_accepted_in_fallback_header_and_still_validated(client, admin):
    ok = client.get("/api/auth/me", headers={"X-Workcode-Token": admin.token})
    assert ok.status_code == 200 and ok.json()["role"] == "admin"
    # a proxy replaced Authorization with its own value: the fallback header still works
    mixed = client.get("/api/auth/me", headers={"Authorization": "Bearer proxy-own-token",
                                                "X-Workcode-Token": admin.token})
    assert mixed.status_code == 200
    assert client.get("/api/auth/me", headers={"X-Workcode-Token": "garbage"}).status_code == 401


def test_query_token_is_refused_unless_explicitly_enabled(client, admin):
    assert client.get(f"/api/auth/me?_t={admin.token}").status_code == 401
    assert client.get(f"/api/_t/{admin.token}/auth/me").status_code == 404
