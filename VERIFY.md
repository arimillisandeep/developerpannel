# WORKCODE — step-by-step check of frontend and backend

Build 34.15 · run on 18 Nov 2026 · **25 of 25 checks passed**

Everything below was executed, not inspected by eye. The app ran with a **real PostgreSQL 17**, the **real FastAPI
backend**, the **real Vite frontend** and a **real Chromium** driven by Playwright. `verify/verify_all.py` is the
script; it creates its own task, so it can be run again.

| What ran | Version / place |
|---|---|
| Database | PostgreSQL 17 in Docker, port 5440, database `workcode_v2`, 43 tables, `alembic_version` = `0010` |
| Backend | `python -m uvicorn app.main:app` on 127.0.0.1:8000 |
| Frontend | `npx vite` on 127.0.0.1:5173 (the same dev server Docker uses) |
| Browser | Chromium (headless), 1500×950 |
| Accounts | the five demo accounts, password `Workcode@123` |

## 1. Backend, endpoint by endpoint

| # | Check | Result |
|---|---|---|
| 1 | `GET /api/health` | `{"status":"ok"}` |
| 2 | `GET /api/health/db` (really queries PostgreSQL) | `{"status":"ok","users":5,"schema":"0010"}` |
| 3 | `GET /api/health/version` | `{"build":"build 34.15","fixes":["workspace-read-only-for-reviewers","review-task-in-my-list"]}` |
| 4 | Wrong password → `401`, never `500` | `401 {"detail":"Incorrect email or password"}` |
| 5 | Forgot password with no mail configured → honest sentence | `503 {"detail":"Password reset by e-mail is not set up on this server. …"}` |
| 6 | All five roles can sign in | admin, reviewer, onroll, intern, offroll |
| 7 | Reviewer assigns a task to the intern | `201`, task `WC-0004` |
| 8 | Intern saves a file in the workspace | `200` |
| 9 | The submission lands in the On-Roll queue | submission 2, task 4, stage `onroll_review` |
| 10 | **The reviewer may read the intern's workspace** | `200`, `read_only: true` (this was the 403 of build 34.1) |
| 11 | After the On-Roll approval the stage is `admin_review` | yes |
| 12 | After the Admin approval the task is `completed` | yes |

## 2. Frontend, click by click

| # | Step in the browser | Result |
|---|---|---|
| 13 | Intern signs in through the login form | lands on `/intern` |
| 14 | "Accept and start" opens the workspace | `/workspace/4`, editor + explorer + terminal |
| 15 | **Two terminal tabs at the same time** (build 34.8) | `echo VERIFY-T1` and `echo VERIFY-T2` both answered, each in its own shell |
| 16 | Intern types in the editor, Save | change reaches the server (`All changes saved to server`) |
| 17 | Submit → modal → Submit | task shows **Under On-Roll review**, workspace locked |
| 18 | Reviewer sessions opens | `/onroll` |
| 19 | Reviews page lists the submission | 1 pending review |
| 20 | Review page opens with the submitted files | `/reviews/2` |
| 21 | Task modal offers **View workspace (read-only)** | button present for the reviewer |
| 22 | **Clicking it opens the intern's workspace** | `/workspace/4` — **no "You cannot access this workspace"** |
| 23 | It really is read-only and shows the intern's files | badge `Read-only · Under On-Roll review`, `main.py` + `README.md`, Save disabled |
| 24 | Reviewer clicks "Approve → send to Admin" | stage moves to Admin |
| 25 | Admin clicks "Final approve" | task page shows **Completed** |
| — | JavaScript errors on all pages used | **none** |

Screenshots (in the workspace `screenshots/`): `v1-intern-terminals.png`, `v2-intern-submitted.png`,
`v3-reviewer-readonly.png`, `v4-task-completed.png`.

## 3. The two bugs you reported, checked again here

| Reported | Cause | Now |
|---|---|---|
| On-Roll opens the review, "View workspace (read-only)" says *You cannot access this workspace* | the read rule knew only the team lead, the review rule also accepted the named reviewer and (for a submitter without a team) any On-Roll employee | **check 10 + 22 + 23 pass** |
| The task waiting for review does not open / is not in the task list | the task list used the team rule only, the review queue used the review rule | **checks 8–9, 11–24 pass**; `tests/test_workspace_access.py` has 9 tests, 5 of which fail on the old rules |

## 4. The suites that run without a browser

| Suite | Result |
|---|---|
| `cd backend && python -m pytest -q` | **182 passed** (SQLite throw-away, incl. the 9 workspace-access and 5 mailer tests) |
| `cd frontend && npx vitest run` | **92 passed / 5 files** |
| `npx vite build` | builds |

## 5. What this check did **not** cover

Being explicit about the edges:

- **Screen recording** (needs a real screen-share prompt), **meetings**, the **AI assistant** (needs a provider key),
  the **Run** button / terminal *inside tasks* (`docker exec` from a container — it works in your Docker setup but
  was not part of this run), **CSV reports**, **Admin people/teams CRUD**, **backup/restore**.
- The email path was checked up to the moment of sending (`503 not set up` here, `check_mail.py` covers the SMTP
  conversation), not with your Gmail account.
- Numbers were not re-derived against your own data; this is a fresh database with the demo seed.

## 6. Repeat it on your own machine

Backend and frontend logic (no browser needed):

```
cd C:\Users\sande\Downloads\workcode-build34-1\workcode\backend
python -m pytest -q
cd ..\frontend
npx vitest run
```

The click-through, in the same order this report used:

1. Sign in as `intern@workcode.local` → Coding workspace → *Accept and start*.
2. Terminal tab → `echo one`; *Add terminal* → `echo two` — both answer.
3. Create a file, type, **Save**, **Submit** → *Under On-Roll review*.
4. Sign out, sign in as `reviewer@workcode.local` → **Reviews** → open the row.
5. **Task** → **View workspace (read-only)** → the files open, badge read-only, Save greyed out. ← the bug you hit
6. Back → **Approve → send to Admin**.
7. Sign in as `admin@workcode.local` → **Reviews** → **Final approve** → the task shows **Completed**.

If step 5 still refuses, the two commands in the answer to your last message (`docker exec … grep -c
can_read_workspace …`) tell whether the fixed files are inside the running container.
