"""End-to-end check of WORKCODE in a real browser: backend endpoints, then the whole task cycle.

Run:  python verify/verify_all.py
Needs: API on 127.0.0.1:8000, website on 127.0.0.1:5173, Playwright chromium.
It creates its own task (reviewer -> intern), so it can be run again and again.
"""
import asyncio
import json
import os
import urllib.error
import urllib.request

from playwright.async_api import async_playwright

API = "http://127.0.0.1:8000/api"
BASE = "http://127.0.0.1:5173"
OUT = "/home/user/screenshots"
os.makedirs(OUT, exist_ok=True)
PASSWORD = "Workcode@123"

results = []


def check(name, ok, detail=""):
    results.append((ok, name, detail))
    print(("PASS  " if ok else "FAIL  ") + name + ("  -> " + str(detail)[:240] if detail != "" else ""))


def api(path, data=None, token=None, method=None):
    req = urllib.request.Request(API + path, method=method or ("POST" if data is not None else "GET"))
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    body = json.dumps(data).encode() if data is not None else None
    try:
        with urllib.request.urlopen(req, body, timeout=25) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw


async def dismiss_consent(page):
    cancel = page.locator(".modal-back").get_by_role("button", name="Cancel")
    if await cancel.count():
        await cancel.first.click()
        await page.wait_for_timeout(600)
        return True
    return False


async def click(page, name, exact=False, timeout=12000):
    await dismiss_consent(page)
    await page.get_by_role("button", name=name, exact=exact).first.click(timeout=timeout)


async def open_session(page, token, landing="/"):
    await page.goto(f"{BASE}/login")
    await page.evaluate("t => localStorage.setItem('workcode_token', t)", token)
    await page.goto(f"{BASE}{landing}")
    await page.wait_for_timeout(3000)
    return page.url


async def main():
    # ------------------------------------------------------------------ backend
    code, health = api("/health")
    check("backend: GET /api/health", code == 200 and health.get("status") == "ok", health)

    code, db = api("/health/db")
    check("backend: GET /api/health/db reaches PostgreSQL", code == 200 and db.get("status") == "ok", db)

    code, ver = api("/health/version")
    check("backend: GET /api/health/version names the running build", code == 200 and "fixes" in ver, ver)

    code, bad = api("/auth/login", {"email": "intern@workcode.local", "password": "wrong"})
    check("backend: a wrong password answers 401, not 500", code == 401, (code, bad))

    code, forgot = api("/auth/forgot-password", {"email": "intern@workcode.local"})
    check("backend: forgot-password without e-mail setup answers 503 with a sentence",
          code == 503 and "not set up" in str(forgot), (code, forgot))

    tokens, ids = {}, {}
    for who in ("admin", "reviewer", "onroll", "intern", "offroll"):
        code, body = api("/auth/login", {"email": f"{who}@workcode.local", "password": PASSWORD})
        if code == 200:
            tokens[who] = body["access_token"]
            ids[who] = body["user"]["id"]
    check("backend: all five demo roles sign in", len(tokens) == 5, list(tokens))

    code, task = api("/tasks", {"title": "End-to-end check", "assigned_to": ids["intern"],
                                "reviewer_id": ids["reviewer"], "requirements": "Checked by the browser"},
                     token=tokens["reviewer"])
    task_id = task.get("id") if isinstance(task, dict) else None
    check("backend: the On-Roll reviewer assigns a task to the intern", code == 201 and task_id, (code, task_id))

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1500, "height": 950}, device_scale_factor=2)
        page = await ctx.new_page()
        console = []
        page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)

        # -------------------------------------------------------------- intern: sign in through the form
        await page.goto(f"{BASE}/login")
        await page.get_by_label("Email or username").fill("intern@workcode.local")
        await page.get_by_label("Password").fill(PASSWORD)
        await page.get_by_role("button", name="Sign in").click()
        await page.wait_for_timeout(2500)
        check("browser: the intern signs in through the form", "/login" not in page.url, page.url)

        await page.goto(f"{BASE}/workspace")
        await page.wait_for_timeout(2500)
        for label in ("Accept and start", "Start task", "Open workspace"):
            btn = page.get_by_role("button", name=label)
            if await btn.count():
                await btn.first.click()
                await page.wait_for_timeout(3000)
                break
        await dismiss_consent(page)
        check("browser: the intern reaches the coding workspace", "/workspace/" in page.url, page.url)

        # -------------------------------------------------------------- two terminals at once (build 34.8)
        await click(page, "Terminal", exact=True)
        await page.wait_for_timeout(1500)
        await click(page, "＋ New terminal", exact=True)
        await page.wait_for_timeout(6000)
        read = """() => [...document.querySelectorAll('[data-testid="terminal"]')].map((el) => el.innerText).join('\\n')"""
        await page.locator('[data-testid="terminal"]:visible').click()
        await page.keyboard.type("echo VERIFY-T1\n")
        await page.wait_for_timeout(1200)
        await click(page, "Add terminal", exact=True)
        await page.wait_for_timeout(6000)
        await page.locator('[data-testid="terminal"]:visible').click()
        await page.keyboard.type("echo VERIFY-T2\n")
        await page.wait_for_timeout(1500)
        terminals = await page.evaluate(read)
        check("browser: two terminal tabs both answer (34.8)", "VERIFY-T1" in terminals and "VERIFY-T2" in terminals,
              terminals[-110:].replace("\n", " | "))
        await page.screenshot(path=f"{OUT}/v1-intern-terminals.png")

        # -------------------------------------------------------------- submit
        code, ws = api(f"/tasks/{task_id}/workspace", token=tokens["intern"])
        wid = ws.get("id")
        code, put = api(f"/workspaces/{wid}/files", {"path": "main.py", "content": 'print("checked")\n', "manual": True},
                        token=tokens["intern"], method="PUT")
        check("backend: the intern saves a file in the workspace", code == 200, code)

        await page.goto(f"{BASE}/workspace/{task_id}")
        await page.wait_for_timeout(4000)
        await dismiss_consent(page)
        await page.locator(".monaco-editor .view-lines").first.click()
        await page.wait_for_timeout(400)
        await page.keyboard.press("Control+End")
        await page.keyboard.type("# typed in the browser\n")
        await page.wait_for_timeout(500)
        save = page.get_by_role("button", name="Save", exact=True)
        if await save.count():
            await save.first.click()
            await page.wait_for_timeout(2000)
        await click(page, "Submit", exact=True)
        await page.wait_for_timeout(1000)
        note = page.get_by_label("Submission note")
        if await note.count():
            await note.first.fill("End-to-end check")
        await page.locator(".modal-back").get_by_role("button", name="Submit").click()
        await page.wait_for_timeout(3000)
        body = await page.inner_text("body")
        check("browser: the intern submits for review", "On-Roll review" in body or "locked" in body.lower(),
              [l for l in body.split("\n") if "eview" in l or "ocked" in l][:2])
        await page.screenshot(path=f"{OUT}/v2-intern-submitted.png")

        code, queue = api("/submissions?view=queue", token=tokens["reviewer"])
        sub_id = queue[0]["id"] if code == 200 and queue else None
        check("backend: the submission is in the On-Roll queue", sub_id is not None,
              [(q["id"], q["task_id"], q["stage"]) for q in queue] if code == 200 else queue)

        code, ws_read = api(f"/tasks/{task_id}/workspace", token=tokens["reviewer"])
        check("backend: the reviewer may read the workspace (34.13)", code == 200 and ws_read.get("read_only") is True,
              ws_read if code != 200 else {"id": ws_read.get("id"), "read_only": ws_read.get("read_only")})

        # -------------------------------------------------------------- reviewer: queue, task, read-only workspace
        await ctx.clear_cookies()
        url = await open_session(page, tokens["reviewer"])
        check("browser: the reviewer session opens", "/login" not in url, url)

        await page.goto(f"{BASE}/reviews")
        await page.wait_for_timeout(2500)
        rows = page.locator("tr.click")
        check("browser: the review queue lists the submission", await rows.count() >= 1, await rows.count())
        await rows.first.click()
        await page.wait_for_timeout(2500)
        check("browser: the review page opens with the files", "/reviews/" in page.url, page.url)

        await page.goto(f"{BASE}/tasks/{task_id}")
        await page.wait_for_timeout(3500)
        ro = page.get_by_role("link", name="View workspace (read-only)")
        if not await ro.count():
            ro = page.get_by_role("button", name="View workspace (read-only)")
        check("browser: the task shows 'View workspace (read-only)' for the reviewer", await ro.count() >= 1,
              await page.locator(".modal-back").inner_text() if await page.locator(".modal-back").count() else "")
        await ro.first.click()
        await page.wait_for_timeout(4000)
        await dismiss_consent(page)
        body = await page.inner_text("body")
        check("browser: the read-only workspace opens for the reviewer (34.13)", "/workspace/" in page.url, page.url)
        check("browser: it shows the intern's files and says read-only",
              "You cannot access this workspace" not in body and "read-only" in body.lower(),
              [l for l in body.split("\n") if "read-only" in l.lower() or "cannot" in l.lower()][:2])
        await page.screenshot(path=f"{OUT}/v3-reviewer-readonly.png")

        # -------------------------------------------------------------- reviewer approves
        await page.goto(f"{BASE}/reviews/{sub_id}")
        await page.wait_for_timeout(2500)
        await click(page, "Approve → send to Admin")
        await page.wait_for_timeout(2500)
        code, rev = api(f"/submissions/{sub_id}", token=tokens["reviewer"])
        check("backend: after approval it waits for Admin", rev.get("stage") == "admin_review", rev.get("stage"))

        # -------------------------------------------------------------- admin finishes
        await ctx.clear_cookies()
        url = await open_session(page, tokens["admin"])
        check("browser: the admin session opens", "/login" not in url, url)
        await page.goto(f"{BASE}/reviews/{sub_id}")
        await page.wait_for_timeout(2500)
        if await page.get_by_role("button", name="Final approve").count():
            await click(page, "Final approve")
            await page.wait_for_timeout(2500)
        code, done = api(f"/tasks/{task_id}", token=tokens["admin"])
        check("backend: the task is completed after both approvals", done.get("status") == "completed",
              done.get("status"))
        await page.goto(f"{BASE}/tasks/{task_id}")
        await page.wait_for_timeout(2500)
        body = await page.inner_text("body")
        check("browser: the task page shows it as completed", "omplet" in body,
              [json.dumps(l) for l in body.split("\n") if "omplet" in l][:2])
        await page.screenshot(path=f"{OUT}/v4-task-completed.png")

        errors = [c for c in console if "favicon" not in c and "Failed to load resource" not in c]
        check("browser: no JavaScript errors on the pages used", len(errors) == 0, errors[:3])
        await browser.close()

    print("\n----------")
    passed = sum(1 for ok, _, _ in results if ok)
    print(f"{passed}/{len(results)} checks passed")
    with open("/home/user/verify/report.json", "w") as f:
        json.dump([{"ok": ok, "check": n, "detail": str(d)[:600]} for ok, n, d in results], f, indent=1)


if __name__ == "__main__":
    asyncio.run(main())
