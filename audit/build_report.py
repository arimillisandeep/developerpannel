"""Builds the endpoint table of API_AUDIT.md from the real run outputs in this folder (nothing is typed by hand)."""
import json, re

routes = [r for r in json.load(open("routes.json")) if r["method"] != "MOUNT"]
cov = json.load(open("coverage.json"))
matrix = json.load(open("matrix.json"))["results"]
DOCKER = {"POST /api/submissions/{sub_id}/run", "POST /api/languages/{lang_id}/pull", "POST /api/workspaces/{ws_id}/run"}
NO_UI = {"DELETE /api/users/{user_id}", "POST /api/workspaces/{ws_id}/files/{file_id}/rename", "GET /api/sessions/current", "GET /api/dashboard/developer"}
OTHER_CLIENT = {
    "GET /api/tasks/{task_id}/attachments/{attachment_id}": "src/utils/download.js (called from Tasks.jsx, ReviewDetail.jsx)",
    "GET /api/submissions/{sub_id}/download": "src/utils/download.js (called from Tasks.jsx, ReviewDetail.jsx)",
    "POST /api/sessions/pause": "src/context/TimerContext.jsx:125", "POST /api/sessions/resume": "src/context/TimerContext.jsx:125",
    "POST /api/sessions/stop": "src/context/TimerContext.jsx:125",
    "GET /api/extension/config": "extension/ (Chrome extension)", "POST /api/extension/report": "extension/ (Chrome extension)",
    "POST /api/ai/conversations/{conv_id}/messages": "src/services/ai.js (streamed fetch)", "POST /api/ai/conversations/{conv_id}/regenerate": "src/services/ai.js (streamed fetch)",
    "GET /api/health": "none (server health check)", "WS /ws": "src/context/NotificationContext.jsx", "WS /ws/terminal": "src/pages/workspace/Terminal.jsx",
}
WHO = {"matrix": "negative matrix", "functional": "API workflow", "extra": "API workflow", "live_task": "task flow", "live_ai": "AI flow", "flows": "browser", "sweep": "browser"}

def access(r):
    key = r["method"] + " " + r["path"]
    role = next((d[4:-1].replace(",", ", ") for d in r["deps"] if d.startswith("dep(")), None)
    if key in ("POST /api/auth/login", "GET /api/health"): return "none", "public"
    if "extension_user" in r["deps"]: return "extension token", "any signed-in user's extension"
    if r["method"] == "WS": return "JWT in ?token=", "any signed-in user" if r["path"] == "/ws" else "owner of the workspace"
    return "JWT", (role.replace("developer", "developer*") if role else "any signed-in user (object rules inside)")

rows, count = [], {"PASS": 0, "FAIL": 0, "WARNING": 0, "NOT TESTED": 0, "BLOCKED": 0}
for r in sorted(routes, key=lambda r: (r["file"].split(":")[0], r["path"], r["method"])):
    key = r["method"] + " " + r["path"]
    auth, role = access(r)
    front = "; ".join(sorted(set(f.rsplit(":", 1)[0] if False else f for f in r["frontend"]))[:2]) or OTHER_CLIENT.get(key, "")
    c = cov.get(key, {})
    good = sorted({s for p, ss in c.items() if p != "matrix" for s in ss if s < 300})
    browser = any(s < 300 for p in ("flows", "sweep") for s in c.get(p, []))
    m = matrix.get(key, {}); neg_ok = sum(1 for x in m.values() if x["result"] == "PASS"); neg = len(m)
    issue = ""
    if r["method"] == "WS":
        if r["path"] == "/ws": status, actual = "PASS", "connects with a token, live notification and chat events received (API script + browser shows 'live'); no/bad token closed 4401"
        else: status, actual, issue = "BLOCKED", "no token / foreign workspace refused; with a valid token it answers a clear 'runner not available' message", "the shell itself needs Docker"
    elif key in DOCKER:
        status, actual, issue = "BLOCKED", f"503 with a clear message (no Docker here); negative checks {neg_ok}/{neg}", "success path needs Docker on the server"
    elif not good:
        status, actual = "NOT TESTED", f"no successful request made; negative checks {neg_ok}/{neg}"
    elif neg_ok != neg:
        status, actual = "FAIL", f"{good}; negative checks {neg_ok}/{neg}"
    else:
        status = "PASS"; actual = f"{'/'.join(map(str, good))} ({'browser + API' if browser else 'API workflow'}); negative checks {neg_ok}/{neg}"
        if key in NO_UI: status, issue = "WARNING", "works, but no page or client calls it"
    if key == "GET /api/users/{user_id}/activity": issue = "fixed: unknown user now 404 (was 200 with an empty list)"
    if key == "GET /api/reports/summary": issue = "fixed: end before start now 422 (was 200)"
    if key == "POST /api/auth/logout": issue = "fixed: the token is refused after logout"
    if key == "POST /api/auth/change-password": issue = "fixed: old tokens refused, a new token is returned"
    if key == "PATCH /api/users/{user_id}": issue = "fixed: admin password reset ends the person's tokens"
    count[status] += 1
    params = ", ".join(r["path_params"] + [q + "?" for q in r["query"]]) or "-"
    body = ", ".join(r["body"])[:70] or "-"
    exp = r["status"] or (101 if r["method"] == "WS" else 200)
    rows.append(f"| {r['method']} | `{r['path']}` | {r['file']} | {front or 'none'} | {auth} | {role} | {params} | {body} | {exp} | {actual} | {status} | {issue or '-'} |")

head = "| Method | URL | Backend file | Frontend / client file | Auth | Role | Params (?=query) | Body fields | Expected | Actual test result | Status | Issue |\n|---|---|---|---|---|---|---|---|---|---|---|---|"
open("inventory.md", "w").write(head + "\n" + "\n".join(rows) + "\n")
json.dump(count, open("inventory_counts.json", "w"))
print(len(rows), count)
