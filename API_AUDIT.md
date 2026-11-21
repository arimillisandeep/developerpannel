# WORKCODE – Frontend and Backend API Audit (Build 19)

Date: 13 Nov 2026. Baseline: git commit `3516955` (Build 18), taken before any change.

Every number in this report comes from a real run. The raw outputs are in `audit/` and the scripts are in
`backend/scripts/audit_*.py` and `audit/*.mjs`, so each result can be reproduced (commands in section 13).

**Update (same day): PostgreSQL has now been tested** on a real PostgreSQL 17 server: 90 pytest, the 1280-check matrix,
all API workflows, and both browser runs pass. Results are in `LOCAL_SETUP.md`. Lines below that say PostgreSQL was
not tested describe the first run.

**This is not a 100% result.** 4 endpoints are BLOCKED (they need Docker), 4 are WARNING, and three things were
NOT TESTED at all (PostgreSQL, the extension inside real Chrome, a real AI provider in this run). See sections 11 and 12.

## How it was tested

| Layer | How | Where |
|---|---|---|
| Backend | Real HTTP requests to a running server (`uvicorn`, port 8010) | isolated SQLite test database `/tmp/audit/audit.db`, created by the 6 migrations + demo seed |
| Database | Read with `sqlite3` after each request to prove the change was stored | same test database |
| Frontend | Real headless Chromium opening the built React app through the Vite proxy, clicking and typing | same server and database |
| Production data | Not touched. `demo.db` was only read, then upgraded by the additive migration 0006 after a backup (`backend/demo.before-audit.db`); row counts are identical before and after | |

Statuses: **PASS** = at least one real successful request with the right result, and every negative check passed.
**WARNING** = works, but something should be looked at. **BLOCKED** = cannot run in this environment.
**NOT TESTED** = no request was made. PASS does not mean every possible input was tried.

## 1. Summary

| Check | Result |
|---|---|
| Existing tests before any change | pytest 80 passed, vitest 59 passed, extension 5 passed |
| Route inventory | 129 HTTP endpoints + 2 WebSockets, 16 backend files; no duplicate routes |
| Negative matrix (no token, broken token, wrong role, outsider, missing id, empty body, broken JSON) | 1280 of 1280 checks passed, 129 endpoints, no 5xx |
| API workflows with database proof | 190 PASS, 1 BLOCKED (Docker) of 191; extra task/review paths 14 of 14 |
| Task and review flow (Intern → On-Roll → Admin) | 35 of 35 |
| AI assistant flow (local test provider) | 54 of 54 |
| Database structure and data | 10 of 10 checks on the test DB, on an upgraded old DB and on `demo.db` |
| Browser: every menu page, 5 logins | 72 of 72 pages opened, 0 crashes, 0 failed API calls, 0 calls without the auth header |
| Browser: clicked workflows | 34 of 34 |
| Tests after the fixes | pytest 90 passed, vitest 62 passed, extension 5 passed |
| Confirmed problems found | 9 (all fixed and retested, section 9) |

## 2. Backend audit

Checked for each of the 129 endpoints with real requests:

- **Authentication**: no token → 401 and broken token → 401 on every protected endpoint. Expired, forged, re-signed with another secret,
  `alg=none` and `?token=` in the address are all refused. Passwords are bcrypt hashes.
- **Authorization**: 28 role-restricted endpoints answer 403 for every other role. An Off-Roll user and an unrelated
  On-Roll user tried every endpoint with the Intern's task, workspace, files, submission, AI conversation, chat and
  recording ids: only 403 / 404, and the Intern's project was byte-identical afterwards.
- **Validation and status codes**: ids that do not exist, empty bodies and broken JSON give a clean 4xx on all
  endpoints and roles. No 500 in any run (0 lines with status 500 in the server log, `audit/access.log`).
- **Methods**: GET, POST, PUT, PATCH and DELETE were all exercised (see the table in section 7).
- **Pagination / limits**: notifications (50, max 200), chat messages (200, max 500), audit log (200, max 1000),
  activity (100, max 500), AI conversations (200), file history (300). `GET /tasks`, `/users`, `/submissions` return the
  whole list (WARNING W4).
- **Uploads / downloads**: attachment of 30 MB and `.exe` refused; file over 1 MB and path traversal (`../`) refused;
  recording upload and download byte-identical; project zip and submission zip download correctly.
- **WebSockets**: `/ws` connects with a token and delivers live notification and chat events; without a token it is
  closed (4401). `/ws/terminal` refuses foreign workspaces; the shell itself is BLOCKED (Docker).
- **Database relationships**: every write was read back from SQLite (users, profiles, teams, tasks, assignments,
  workspaces, files, versions, submissions, reviews, comments, notifications, chat, meetings, recordings, sessions,
  attendance, AI providers and conversations). No duplicates, no orphan rows.

## 3. Frontend audit

- **Service layer**: one Axios instance (`src/services/api.js`, base URL `/api`), one streamed `fetch` for AI answers
  (`src/services/ai.js`, uses the same token through `rawRequest`), one download helper (`src/utils/download.js`),
  two WebSockets (`NotificationContext.jsx`, `Terminal.jsx`). No hard-coded host: all calls are relative and go
  through the Vite proxy (`vite.config.js`, env `WORKCODE_API`), so there is no CORS request in normal use.
- **Token handling**: request interceptor adds `Authorization: Bearer …` to every call (verified in the browser:
  0 API calls without it). Response interceptor: a 401 clears the token and returns to the login page.
- **Call sites**: 137 API call sites found in the code. 135 match a backend route and method exactly.
  The other 2 build the address at run time (`POST /sessions/${name}` in `TimerContext.jsx` and the download helper);
  Pause / Resume / Stop were clicked in the browser (200). The two download endpoints answer 200 with the right file in the API scripts; the download **buttons** themselves were not clicked in the browser.
  **Frontend calls without a backend route: 0. Wrong method or wrong path: 0.**
- **Rendering**: 72 pages opened with real data for Admin, On-Roll reviewer, On-Roll, Off-Roll and Intern; no crash,
  no JavaScript error. Wrong password shows the server's message. Forms show server errors (reject without comment,
  wrong current password).
- **Found and fixed**: form labels were not linked to their inputs (F1 below), and the profile page did not handle
  the new token after a password change (part of fix S1).
- **Duplicate request (WARNING W5)**: the dashboard asks `GET /api/attendance` twice on first load.

## 4. End-to-end workflows in the browser (34 of 34)

Each line was clicked in headless Chromium; the request, the status code and the row in the test database were checked.

| Area | Check | Result |
|---|---|---|
| people | Admin adds a person in the People form -> POST /users 201 -> row in the database | PASS |
| people | Search box filters the list from the server | PASS |
| tasks | Admin assigns a task in the form (intern + On-Roll reviewer) -> POST /tasks 201 -> row in the database | PASS |
| ai | Admin adds an AI provider in the AI assistant page -> key stored, never shown again | PASS |
| tasks | Intern sees the new task, opens it and presses Accept -> status accepted in the database | PASS |
| notifications | Intern got a notification for the assignment (bell) and can mark all as read | PASS |
| workspace | Start task opens the workspace; the Monaco editor loads | PASS |
| workspace | New file dialog creates index.html -> PUT /files 200 | PASS |
| workspace | Typing in the editor + Save button stores the exact text in the database | PASS |
| workspace | Reloading the page shows the saved text again (read back from the server) | PASS |
| copy protection | Ctrl+C in the real editor: the code does NOT reach the clipboard | PASS |
| copy protection | Ctrl+V right after: the copied code is pasted inside WORKCODE | PASS |
| copy protection | Text copied in another program can be pasted into the editor | PASS |
| copy protection | Ctrl+Z undoes the paste, Ctrl+X cuts without leaking | PASS |
| ai | AI panel opens on the right; a question streams an answer built from the open file | PASS |
| ai | Preview shows the diff; rejecting one file and applying the other changes only that file in the database | PASS |
| ai | Insert at cursor puts AI code into the editor; "Send to terminal" only fills the input | PASS |
| workspace | Run button without Docker shows the honest "runner not available" message (503), no fake output | PASS |
| tasks | Submit for review -> version 1.0, task under_onroll_review, project locked | PASS |
| chat | Intern sends a chat message to the reviewer -> stored once | PASS |
| timer | Timer in the top bar: Pause, Resume, Stop call the API and the session ends in the database | PASS |
| chat | Reviewer sees the intern's message | PASS |
| reviews | Reviewer finds the submission in the queue, opens it and sees the submitted code | PASS |
| reviews | Reject without a comment is refused with a message; nothing changes in the database | PASS |
| reviews | Approve -> send to Admin: task under_admin_review | PASS |
| reviews | Admin final approve in the UI: task completed, one review row per stage | PASS |
| tasks | Task page shows Completed and the version list with v1.0 | PASS |
| errors | No JavaScript errors in the reviewer's browser | PASS |
| profile | Profile page: wrong current password shows the server message; right one changes it (then changed back) | PASS |
| auth | After a password change the old token is refused (401) and this browser keeps working with its new token | PASS |
| auth | Sign out in the browser: the token that was in use is refused by the server afterwards | PASS |
| forms | Form labels are linked to their inputs (login page and password form reachable by label) | PASS |
| errors | No JavaScript errors in the admin's browser | PASS |
| errors | No JavaScript errors in the intern's browser | PASS |

## 5. Roles

Logins used: Admin, On-Roll reviewer (team lead), On-Roll, Off-Roll, Intern.

| Role | Login / logout | Pages opened | Typed admin addresses | Forbidden API requests |
|---|---|---|---|---|
| Admin | PASS | 14 of 14 | – | – |
| On-Roll (reviewer) | PASS | 11 + 4 | sent back to own dashboard | 403 |
| On-Roll | PASS | 11 + 4 | sent back to own dashboard | 403 |
| Off-Roll | PASS | 10 + 4 | sent back to own dashboard | 403 |
| Intern | PASS | 10 + 4 | sent back to own dashboard | 403 |
| Developer | NOT TESTED as a login | – | – | – |

**About "Developer"**: the platform has four active roles (admin, onroll, offroll, intern). `developer` exists only as a
constant in `permissions.py`; the On-Roll team lead does the reviewer job, and `GET /api/dashboard/developer` answers
200 for On-Roll. No user can be created with a separate Developer role, so there was nothing to log in with.

Covered per role: dashboard, task assignment (Admin), accept / start / save / submit (Intern), review and approve
(On-Roll), final approve (Admin), reject and rework, user management (Admin only), profile and password, coding
workspace, timer (start, pause, resume, stop), notifications, reports.

## 6. Database

| Check | Test DB | Old DB upgraded 0005 → 0006 | `demo.db` |
|---|---|---|---|
| `PRAGMA integrity_check`, `foreign_key_check` (no orphan rows) | PASS | PASS | PASS |
| Every table (40) has a primary key | PASS | PASS | PASS |
| Every foreign-key column has an index | PASS (after fix D2) | PASS | PASS |
| No duplicates (11 rules: e-mail, task code, team member, attendance day, version label …) | PASS | PASS | PASS |
| Unique constraints exist in the database, not only in code | PASS | PASS | PASS |
| No bad values (9 rules: nulls, roles, statuses, bcrypt hashes, AI keys encrypted, completed ⇒ admin approval) | PASS | PASS | PASS |
| Migrations match the models (`alembic check`) | PASS | PASS | PASS |
| Downgrade 0006 → 0005 → upgrade again | – | PASS | – |

Transactions: every endpoint commits once through `commit(db)`; failed requests in the matrix left no partial rows
(checked by the duplicate and orphan rules after 1280 negative requests).

**PostgreSQL: NOT TESTED** (not available here). The migrations use only portable SQLAlchemy operations, but that is
not proof.

## 7. API inventory (131 entries)

`developer*` = role name kept in code; in practice it is the On-Roll lead. "negative checks" = the matrix checks for that endpoint.

| Method | URL | Backend file | Frontend / client file | Auth | Role | Params (?=query) | Body fields | Expected | Actual test result | Status | Issue |
|---|---|---|---|---|---|---|---|---|---|---|---|
| GET | `/api/ai/conversations` | app/api/ai.py:360 | src/pages/workspace/AIPanel.jsx:140 | JWT | any signed-in user (object rules inside) | q?, task_id? | - | 200 | 200 (API workflow); negative checks 7/7 | PASS | - |
| POST | `/api/ai/conversations` | app/api/ai.py:376 | src/pages/workspace/AIPanel.jsx:197 | JWT | any signed-in user (object rules inside) | - | body:ConversationIn | 201 | 201 (browser + API); negative checks 10/10 | PASS | - |
| DELETE | `/api/ai/conversations/{conv_id}` | app/api/ai.py:408 | src/pages/workspace/AIPanel.jsx:249 | JWT | any signed-in user (object rules inside) | conv_id | - | 200 | 200 (API workflow); negative checks 8/8 | PASS | - |
| GET | `/api/ai/conversations/{conv_id}` | app/api/ai.py:392 | src/pages/workspace/AIPanel.jsx:145 | JWT | any signed-in user (object rules inside) | conv_id | - | 200 | 200 (API workflow); negative checks 8/8 | PASS | - |
| PATCH | `/api/ai/conversations/{conv_id}` | app/api/ai.py:399 | src/pages/workspace/AIPanel.jsx:248 | JWT | any signed-in user (object rules inside) | conv_id | body:TitleIn | 200 | 200 (API workflow); negative checks 16/16 | PASS | - |
| POST | `/api/ai/conversations/{conv_id}/clear` | app/api/ai.py:419 | src/pages/workspace/AIPanel.jsx:250 | JWT | any signed-in user (object rules inside) | conv_id | - | 200 | 200 (API workflow); negative checks 8/8 | PASS | - |
| POST | `/api/ai/conversations/{conv_id}/messages` | app/api/ai.py:578 | src/services/ai.js (streamed fetch) | JWT | any signed-in user (object rules inside) | conv_id | body:AskIn | 200 | 200 (browser + API); negative checks 16/16 | PASS | - |
| POST | `/api/ai/conversations/{conv_id}/regenerate` | app/api/ai.py:605 | src/services/ai.js (streamed fetch) | JWT | any signed-in user (object rules inside) | conv_id | body:RegenerateIn | 200 | 200 (API workflow); negative checks 16/16 | PASS | - |
| PATCH | `/api/ai/messages/{message_id}` | app/api/ai.py:448 | src/pages/workspace/AIPanel.jsx:233 | JWT | any signed-in user (object rules inside) | message_id | body:SavedIn | 200 | 200 (API workflow); negative checks 16/16 | PASS | - |
| POST | `/api/ai/messages/{message_id}/stop` | app/api/ai.py:456 | src/pages/workspace/AIPanel.jsx:211 | JWT | any signed-in user (object rules inside) | message_id | - | 200 | 200 (API workflow); negative checks 8/8 | PASS | - |
| POST | `/api/ai/patch/apply` | app/api/ai.py:660 | src/pages/workspace/AIPanel.jsx:76 | JWT | any signed-in user (object rules inside) | - | body:PatchIn | 200 | 200 (browser + API); negative checks 12/12 | PASS | - |
| POST | `/api/ai/patch/preview` | app/api/ai.py:648 | src/pages/workspace/AIPanel.jsx:66 | JWT | any signed-in user (object rules inside) | - | body:PatchIn | 200 | 200 (browser + API); negative checks 12/12 | PASS | - |
| GET | `/api/ai/providers` | app/api/ai.py:231 | src/pages/admin/AISettings.jsx:85 | JWT | admin | - | - | 200 | 200 (browser + API); negative checks 10/10 | PASS | - |
| POST | `/api/ai/providers` | app/api/ai.py:237 | src/pages/admin/AISettings.jsx:28 | JWT | admin | - | body:ProviderIn | 201 | 201 (browser + API); negative checks 13/13 | PASS | - |
| DELETE | `/api/ai/providers/{provider_id}` | app/api/ai.py:285 | src/pages/admin/AISettings.jsx:159 | JWT | admin | provider_id | - | 200 | 200 (API workflow); negative checks 11/11 | PASS | - |
| PATCH | `/api/ai/providers/{provider_id}` | app/api/ai.py:259 | src/pages/admin/AISettings.jsx:28 | JWT | admin | provider_id | body:ProviderUpdate | 200 | 200 (browser + API); negative checks 19/19 | PASS | - |
| POST | `/api/ai/providers/{provider_id}/test` | app/api/ai.py:295 | src/pages/admin/AISettings.jsx:38 | JWT | admin | provider_id | - | 200 | 200 (browser + API); negative checks 11/11 | PASS | - |
| GET | `/api/ai/saved` | app/api/ai.py:433 | src/pages/workspace/AIPanel.jsx:142 | JWT | any signed-in user (object rules inside) | - | - | 200 | 200 (API workflow); negative checks 7/7 | PASS | - |
| GET | `/api/ai/settings` | app/api/ai.py:204 | src/pages/admin/AISettings.jsx:86 | JWT | admin | - | - | 200 | 200 (browser + API); negative checks 10/10 | PASS | - |
| PUT | `/api/ai/settings` | app/api/ai.py:211 | src/pages/admin/AISettings.jsx:91 | JWT | admin | - | body:SettingsIn | 200 | 200 (API workflow); negative checks 13/13 | PASS | - |
| GET | `/api/ai/status` | app/api/ai.py:196 | src/pages/workspace/AIPanel.jsx:131 | JWT | any signed-in user (object rules inside) | - | - | 200 | 200 (browser + API); negative checks 7/7 | PASS | - |
| GET | `/api/ai/usage` | app/api/ai.py:306 | src/pages/admin/AISettings.jsx:89 | JWT | admin | days? | - | 200 | 200 (browser + API); negative checks 10/10 | PASS | - |
| POST | `/api/auth/change-password` | app/api/auth.py:50 | src/pages/profile/Profile.jsx:15 | JWT | any signed-in user (object rules inside) | - | body:ChangePasswordIn | 200 | 200 (browser + API); negative checks 10/10 | PASS | fixed: old tokens refused, a new token is returned |
| POST | `/api/auth/login` | app/api/auth.py:16 | src/context/AuthContext.jsx:24 | none | public | - | body:LoginIn | 200 | 200 (browser + API); negative checks 9/9 | PASS | - |
| POST | `/api/auth/logout` | app/api/auth.py:39 | src/context/AuthContext.jsx:32 | JWT | any signed-in user (object rules inside) | - | - | 200 | 200 (browser + API); negative checks 2/2 | PASS | fixed: the token is refused after logout |
| GET | `/api/auth/me` | app/api/auth.py:34 | src/context/AuthContext.jsx:13 | JWT | any signed-in user (object rules inside) | - | - | 200 | 200 (browser + API); negative checks 7/7 | PASS | - |
| GET | `/api/chat/contacts` | app/api/chat.py:49 | src/pages/chat/Chat.jsx:48 | JWT | any signed-in user (object rules inside) | - | - | 200 | 200 (browser + API); negative checks 7/7 | PASS | - |
| GET | `/api/chat/conversations` | app/api/chat.py:55 | src/layouts/AppLayout.jsx:117; src/pages/chat/Chat.jsx:46 | JWT | any signed-in user (object rules inside) | - | - | 200 | 200 (browser + API); negative checks 7/7 | PASS | - |
| POST | `/api/chat/conversations` | app/api/chat.py:63 | src/pages/chat/Chat.jsx:15; src/pages/chat/Chat.jsx:63 | JWT | any signed-in user (object rules inside) | - | body:ConversationIn | 201 | 201 (browser + API); negative checks 10/10 | PASS | - |
| GET | `/api/chat/conversations/{conv_id}/messages` | app/api/chat.py:98 | src/pages/chat/Chat.jsx:47 | JWT | any signed-in user (object rules inside) | conv_id, limit? | - | 200 | 200 (browser + API); negative checks 8/8 | PASS | - |
| POST | `/api/chat/conversations/{conv_id}/messages` | app/api/chat.py:114 | src/pages/chat/Chat.jsx:69 | JWT | any signed-in user (object rules inside) | conv_id | body:MessageIn | 201 | 201 (browser + API); negative checks 16/16 | PASS | - |
| GET | `/api/dashboard/admin` | app/api/dashboard.py:73 | src/pages/admin/AdminDashboard.jsx:17 | JWT | admin | start?, end? | - | 200 | 200 (browser + API); negative checks 10/10 | PASS | - |
| GET | `/api/dashboard/developer` | app/api/dashboard.py:101 | none | JWT | developer*, onroll | start?, end? | - | 200 | 200 (API workflow); negative checks 9/9 | WARNING | works, but no page or client calls it |
| GET | `/api/dashboard/me` | app/api/dashboard.py:124 | src/pages/employee/EmployeeDashboard.jsx:20 | JWT | any signed-in user (object rules inside) | - | - | 200 | 200 (browser + API); negative checks 7/7 | PASS | - |
| GET | `/api/languages` | app/api/execution.py:27 | src/pages/admin/Languages.jsx:10; src/pages/workspace/Workspace.jsx:132 | JWT | any signed-in user (object rules inside) | - | - | 200 | 200 (browser + API); negative checks 7/7 | PASS | - |
| POST | `/api/languages/{lang_id}/pull` | app/api/execution.py:33 | src/pages/admin/Languages.jsx:17 | JWT | any signed-in user (object rules inside) | lang_id | - | 202 | 503 with a clear message (no Docker here); negative checks 8/8 | BLOCKED | success path needs Docker on the server |
| POST | `/api/workspaces/{ws_id}/run` | app/api/execution.py:50 | src/pages/workspace/Workspace.jsx:242 | JWT | any signed-in user (object rules inside) | ws_id | body:RunIn | 200 | 503 with a clear message (no Docker here); negative checks 16/16 | BLOCKED | success path needs Docker on the server |
| POST | `/api/workspaces/{ws_id}/run/stop` | app/api/execution.py:79 | src/pages/workspace/Workspace.jsx:247 | JWT | any signed-in user (object rules inside) | ws_id | - | 200 | 200 (API workflow); negative checks 8/8 | PASS | - |
| GET | `/api/meetings` | app/api/meetings.py:39 | src/pages/meetings/Meetings.jsx:50 | JWT | any signed-in user (object rules inside) | - | - | 200 | 200 (browser + API); negative checks 7/7 | PASS | - |
| POST | `/api/meetings` | app/api/meetings.py:49 | src/pages/meetings/Meetings.jsx:17 | JWT | any signed-in user (object rules inside) | - | body:MeetingIn | 201 | 201 (API workflow); negative checks 10/10 | PASS | - |
| GET | `/api/meetings/invitable` | app/api/meetings.py:26 | src/pages/meetings/Meetings.jsx:52 | JWT | any signed-in user (object rules inside) | - | - | 200 | 200 (browser + API); negative checks 7/7 | PASS | - |
| DELETE | `/api/meetings/{meeting_id}` | app/api/meetings.py:73 | src/pages/meetings/Meetings.jsx:53 | JWT | any signed-in user (object rules inside) | meeting_id | - | 200 | 200 (API workflow); negative checks 8/8 | PASS | - |
| GET | `/api/notifications` | app/api/notifications.py:13 | src/context/NotificationContext.jsx:18 | JWT | any signed-in user (object rules inside) | limit? | - | 200 | 200 (browser + API); negative checks 7/7 | PASS | - |
| POST | `/api/notifications/read-all` | app/api/notifications.py:21 | src/context/NotificationContext.jsx:55 | JWT | any signed-in user (object rules inside) | - | - | 200 | 200 (browser + API); negative checks 2/2 | PASS | - |
| POST | `/api/notifications/{notification_id}/read` | app/api/notifications.py:28 | src/context/NotificationContext.jsx:51 | JWT | any signed-in user (object rules inside) | notification_id | - | 200 | 200 (API workflow); negative checks 8/8 | PASS | - |
| GET | `/api/audit-logs` | app/api/org.py:166 | src/pages/admin/AuditLog.jsx:13 | JWT | admin | action?, actor_id?, limit? | - | 200 | 200 (browser + API); negative checks 10/10 | PASS | - |
| GET | `/api/departments` | app/api/org.py:18 | src/pages/admin/People.jsx:102; src/pages/admin/Teams.jsx:15 | JWT | any signed-in user (object rules inside) | - | - | 200 | 200 (browser + API); negative checks 7/7 | PASS | - |
| POST | `/api/departments` | app/api/org.py:23 | src/pages/admin/Teams.jsx:25 | JWT | admin | - | body:NameIn | 201 | 201 (API workflow); negative checks 13/13 | PASS | - |
| PUT | `/api/intern-vacancy` | app/api/org.py:150 | src/pages/admin/People.jsx:146 | JWT | admin | - | body:VacancyIn | 200 | 200 (API workflow); negative checks 13/13 | PASS | - |
| GET | `/api/projects` | app/api/org.py:37 | src/pages/admin/Teams.jsx:15; src/pages/tasks/Tasks.jsx:278 | JWT | any signed-in user (object rules inside) | - | - | 200 | 200 (browser + API); negative checks 7/7 | PASS | - |
| POST | `/api/projects` | app/api/org.py:43 | src/pages/admin/Teams.jsx:26 | JWT | admin, developer*, onroll | - | body:NameIn | 201 | 201 (API workflow); negative checks 12/12 | PASS | - |
| GET | `/api/teams` | app/api/org.py:75 | src/pages/admin/Teams.jsx:15; src/pages/developer/MyTeam.jsx:12 | JWT | admin, developer*, onroll | - | - | 200 | 200 (browser + API); negative checks 9/9 | PASS | - |
| POST | `/api/teams` | app/api/org.py:83 | src/pages/admin/Teams.jsx:24 | JWT | admin | - | body:TeamIn | 201 | 201 (API workflow); negative checks 13/13 | PASS | - |
| PATCH | `/api/teams/{team_id}` | app/api/org.py:96 | src/pages/admin/Teams.jsx:42 | JWT | admin | team_id | body:TeamUpdate | 200 | 200 (API workflow); negative checks 19/19 | PASS | - |
| POST | `/api/teams/{team_id}/members` | app/api/org.py:118 | src/pages/admin/Teams.jsx:50 | JWT | admin | team_id | body:MemberIn | 201 | 201 (API workflow); negative checks 19/19 | PASS | - |
| DELETE | `/api/teams/{team_id}/members/{user_id}` | app/api/org.py:134 | src/pages/admin/Teams.jsx:48 | JWT | admin | team_id, user_id | - | 200 | 200 (API workflow); negative checks 11/11 | PASS | - |
| GET | `/api/recordings` | app/api/recordings.py:62 | src/pages/recordings/Recordings.jsx:42 | JWT | any signed-in user (object rules inside) | user_id?, day? | - | 200 | 200 (browser + API); negative checks 7/7 | PASS | - |
| POST | `/api/recordings/start` | app/api/recordings.py:84 | src/context/RecordingContext.jsx:54 | JWT | any signed-in user (object rules inside) | - | body:RecordingStart | 201 | 201 (API workflow); negative checks 10/10 | PASS | - |
| POST | `/api/recordings/{rec_id}/chunk` | app/api/recordings.py:111 | src/context/RecordingContext.jsx:41 | JWT | any signed-in user (object rules inside) | rec_id | - | 200 | 200 (API workflow); negative checks 8/8 | PASS | - |
| GET | `/api/recordings/{rec_id}/file` | app/api/recordings.py:147 | src/pages/recordings/Recordings.jsx:16 | JWT | any signed-in user (object rules inside) | rec_id | - | 200 | 200/206 (API workflow); negative checks 8/8 | PASS | - |
| POST | `/api/recordings/{rec_id}/stop` | app/api/recordings.py:134 | src/context/RecordingContext.jsx:32 | JWT | any signed-in user (object rules inside) | rec_id, failed? | - | 200 | 200 (API workflow); negative checks 8/8 | PASS | - |
| GET | `/api/reports/summary` | app/api/reports.py:71 | src/pages/reports/Reports.jsx:16; src/pages/reports/Reports.jsx:21 | JWT | any signed-in user (object rules inside) | start?, end?, format? | - | 200 | 200 (browser + API); negative checks 7/7 | PASS | fixed: end before start now 422 (was 200) |
| GET | `/api/attendance` | app/api/sessions.py:94 | src/components/WorkTime.jsx:44; src/pages/profile/Profile.jsx:46 | JWT | any signed-in user (object rules inside) | user_id?, days? | - | 200 | 200 (browser + API); negative checks 7/7 | PASS | - |
| GET | `/api/sessions/current` | app/api/sessions.py:43 | none | JWT | any signed-in user (object rules inside) | - | - | 200 | 200 (API workflow); negative checks 7/7 | WARNING | works, but no page or client calls it |
| POST | `/api/sessions/heartbeat` | app/api/sessions.py:48 | src/context/TimerContext.jsx:75 | JWT | any signed-in user (object rules inside) | - | body:HeartbeatIn | 200 | 200 (browser + API); negative checks 10/10 | PASS | - |
| GET | `/api/sessions/live` | app/api/sessions.py:117 | src/pages/admin/Monitoring.jsx:13 | JWT | admin, developer*, onroll | - | - | 200 | 200 (browser + API); negative checks 9/9 | PASS | - |
| POST | `/api/sessions/pause` | app/api/sessions.py:70 | src/context/TimerContext.jsx:125 | JWT | any signed-in user (object rules inside) | - | - | 200 | 200 (browser + API); negative checks 2/2 | PASS | - |
| POST | `/api/sessions/resume` | app/api/sessions.py:78 | src/context/TimerContext.jsx:125 | JWT | any signed-in user (object rules inside) | - | - | 200 | 200 (browser + API); negative checks 2/2 | PASS | - |
| POST | `/api/sessions/start` | app/api/sessions.py:36 | src/context/TimerContext.jsx:81 | JWT | any signed-in user (object rules inside) | - | body:ClientIn | 200 | 200 (browser + API); negative checks 10/10 | PASS | - |
| POST | `/api/sessions/stop` | app/api/sessions.py:86 | src/context/TimerContext.jsx:125 | JWT | any signed-in user (object rules inside) | - | - | 200 | 200 (browser + API); negative checks 2/2 | PASS | - |
| GET | `/api/submissions` | app/api/submissions.py:85 | src/layouts/AppLayout.jsx:113; src/pages/reviews/Reviews.jsx:34 | JWT | any signed-in user (object rules inside) | view? | - | 200 | 200 (browser + API); negative checks 7/7 | PASS | - |
| GET | `/api/submissions/{sub_id}` | app/api/submissions.py:112 | src/pages/reviews/ReviewDetail.jsx:32 | JWT | any signed-in user (object rules inside) | sub_id | - | 200 | 200 (browser + API); negative checks 8/8 | PASS | - |
| POST | `/api/submissions/{sub_id}/comments` | app/api/submissions.py:198 | src/pages/reviews/ReviewDetail.jsx:46 | JWT | any signed-in user (object rules inside) | sub_id | body:CommentIn | 201 | 201 (API workflow); negative checks 16/16 | PASS | - |
| GET | `/api/submissions/{sub_id}/download` | app/api/submissions.py:117 | src/utils/download.js (called from Tasks.jsx, ReviewDetail.jsx) | JWT | any signed-in user (object rules inside) | sub_id | - | 200 | 200 (API workflow); negative checks 8/8 | PASS | - |
| POST | `/api/submissions/{sub_id}/restore` | app/api/submissions.py:161 | src/pages/reviews/ReviewDetail.jsx:62 | JWT | any signed-in user (object rules inside) | sub_id | - | 200 | 200 (API workflow); negative checks 8/8 | PASS | - |
| POST | `/api/submissions/{sub_id}/review` | app/api/submissions.py:212 | src/pages/reviews/ReviewDetail.jsx:41 | JWT | any signed-in user (object rules inside) | sub_id | body:ReviewIn | 200 | 200 (browser + API); negative checks 16/16 | PASS | - |
| POST | `/api/submissions/{sub_id}/run` | app/api/submissions.py:133 | src/pages/reviews/ReviewDetail.jsx:56 | JWT | any signed-in user (object rules inside) | sub_id | body:SnapshotRun | 200 | 503 with a clear message (no Docker here); negative checks 16/16 | BLOCKED | success path needs Docker on the server |
| GET | `/api/tasks` | app/api/tasks.py:93 | src/pages/profile/Profile.jsx:49; src/pages/tasks/Tasks.jsx:271 | JWT | any signed-in user (object rules inside) | scope?, status?, assigned_to?, project_id?, archived? | - | 200 | 200 (browser + API); negative checks 7/7 | PASS | - |
| POST | `/api/tasks` | app/api/tasks.py:136 | src/pages/tasks/Tasks.jsx:54 | JWT | any signed-in user (object rules inside) | - | body:TaskCreate | 201 | 201 (browser + API); negative checks 10/10 | PASS | - |
| DELETE | `/api/tasks/{task_id}` | app/api/tasks.py:354 | src/pages/tasks/Tasks.jsx:243 | JWT | any signed-in user (object rules inside) | task_id | - | 200 | 200 (API workflow); negative checks 8/8 | PASS | - |
| GET | `/api/tasks/{task_id}` | app/api/tasks.py:201 | src/pages/tasks/Tasks.jsx:176 | JWT | any signed-in user (object rules inside) | task_id | - | 200 | 200 (browser + API); negative checks 8/8 | PASS | - |
| PATCH | `/api/tasks/{task_id}` | app/api/tasks.py:219 | src/pages/tasks/Tasks.jsx:52 | JWT | any signed-in user (object rules inside) | task_id | body:TaskUpdate | 200 | 200 (API workflow); negative checks 16/16 | PASS | - |
| POST | `/api/tasks/{task_id}/accept` | app/api/tasks.py:268 | src/pages/tasks/Tasks.jsx:237; src/pages/workspace/WorkspaceIndex.jsx:14 | JWT | any signed-in user (object rules inside) | task_id | - | 200 | 200 (browser + API); negative checks 8/8 | PASS | - |
| POST | `/api/tasks/{task_id}/archive` | app/api/tasks.py:321 | src/pages/tasks/Tasks.jsx:244 | JWT | any signed-in user (object rules inside) | task_id | - | 200 | 200 (API workflow); negative checks 8/8 | PASS | - |
| POST | `/api/tasks/{task_id}/attachments` | app/api/tasks.py:423 | src/pages/tasks/Tasks.jsx:184; src/pages/tasks/Tasks.jsx:57 | JWT | any signed-in user (object rules inside) | task_id | file:UploadFile | 201 | 201 (API workflow); negative checks 16/16 | PASS | - |
| DELETE | `/api/tasks/{task_id}/attachments/{attachment_id}` | app/api/tasks.py:479 | src/pages/tasks/Tasks.jsx:218 | JWT | any signed-in user (object rules inside) | task_id, attachment_id | - | 200 | 200 (API workflow); negative checks 8/8 | PASS | - |
| GET | `/api/tasks/{task_id}/attachments/{attachment_id}` | app/api/tasks.py:467 | src/utils/download.js (called from Tasks.jsx, ReviewDetail.jsx) | JWT | any signed-in user (object rules inside) | task_id, attachment_id | - | 200 | 200 (API workflow); negative checks 8/8 | PASS | - |
| POST | `/api/tasks/{task_id}/cancel` | app/api/tasks.py:299 | src/pages/tasks/Tasks.jsx:245 | JWT | any signed-in user (object rules inside) | task_id | body:NoteIn | 200 | 200 (API workflow); negative checks 16/16 | PASS | - |
| GET | `/api/tasks/{task_id}/compare` | app/api/tasks.py:402 | src/pages/reviews/ReviewDetail.jsx:51; src/pages/tasks/Tasks.jsx:138 | JWT | any signed-in user (object rules inside) | task_id, a?, b? | - | 200 | 200 (API workflow); negative checks 8/8 | PASS | - |
| GET | `/api/tasks/{task_id}/history` | app/api/tasks.py:374 | src/pages/tasks/Tasks.jsx:114 | JWT | any signed-in user (object rules inside) | task_id | - | 200 | 200 (API workflow); negative checks 8/8 | PASS | - |
| POST | `/api/tasks/{task_id}/reopen` | app/api/tasks.py:335 | src/pages/tasks/Tasks.jsx:246 | JWT | any signed-in user (object rules inside) | task_id | body:NoteIn | 200 | 200 (API workflow); negative checks 16/16 | PASS | - |
| POST | `/api/tasks/{task_id}/start` | app/api/tasks.py:288 | src/pages/tasks/Tasks.jsx:179; src/pages/workspace/WorkspaceIndex.jsx:15 | JWT | any signed-in user (object rules inside) | task_id | - | 200 | 200 (browser + API); negative checks 8/8 | PASS | - |
| GET | `/api/tasks/{task_id}/versions` | app/api/tasks.py:393 | src/pages/tasks/Tasks.jsx:132 | JWT | any signed-in user (object rules inside) | task_id | - | 200 | 200 (API workflow); negative checks 8/8 | PASS | - |
| GET | `/api/extension/config` | app/api/timer_admin.py:99 | extension/ (Chrome extension) | extension token | any signed-in user's extension | - | - | 200 | 200 (API workflow); negative checks 7/7 | PASS | - |
| POST | `/api/extension/report` | app/api/timer_admin.py:106 | extension/ (Chrome extension) | extension token | any signed-in user's extension | - | body:ExtensionReport | 200 | 200 (API workflow); negative checks 10/10 | PASS | - |
| POST | `/api/extension/token` | app/api/timer_admin.py:92 | src/components/TimerAdmin.jsx:124 | JWT | any signed-in user (object rules inside) | - | - | 200 | 200 (API workflow); negative checks 2/2 | PASS | - |
| GET | `/api/timer/allowlist` | app/api/timer_admin.py:49 | src/components/TimerAdmin.jsx:85 | JWT | any signed-in user (object rules inside) | - | - | 200 | 200 (browser + API); negative checks 7/7 | PASS | - |
| POST | `/api/timer/allowlist` | app/api/timer_admin.py:54 | src/components/TimerAdmin.jsx:89 | JWT | any signed-in user (object rules inside) | - | body:AllowedSiteIn | 201 | 201 (API workflow); negative checks 10/10 | PASS | - |
| DELETE | `/api/timer/allowlist/{site_id}` | app/api/timer_admin.py:70 | src/components/TimerAdmin.jsx:92 | JWT | any signed-in user (object rules inside) | site_id | - | 200 | 200 (API workflow); negative checks 8/8 | PASS | - |
| GET | `/api/timer/overview` | app/api/timer_admin.py:152 | src/components/TimerAdmin.jsx:31; src/components/TimerAdmin.jsx:39 | JWT | any signed-in user (object rules inside) | start?, end?, role?, format? | - | 200 | 200 (browser + API); negative checks 7/7 | PASS | - |
| GET | `/api/timer/sessions` | app/api/timer_admin.py:203 | src/components/WorkTime.jsx:17 | JWT | any signed-in user (object rules inside) | user_id?, start?, end? | - | 200 | 200 (API workflow); negative checks 7/7 | PASS | - |
| GET | `/api/users` | app/api/users.py:99 | src/pages/admin/People.jsx:98; src/pages/admin/Teams.jsx:15 | JWT | admin, developer*, onroll | role?, active?, q? | - | 200 | 200 (browser + API); negative checks 9/9 | PASS | - |
| POST | `/api/users` | app/api/users.py:141 | src/pages/admin/People.jsx:27 | JWT | admin | - | body:UserCreate | 201 | 201 (browser + API); negative checks 13/13 | PASS | - |
| GET | `/api/users/assignable` | app/api/users.py:117 | src/pages/tasks/Tasks.jsx:276 | JWT | any signed-in user (object rules inside) | - | - | 200 | 200 (browser + API); negative checks 7/7 | PASS | - |
| GET | `/api/users/intern-headcount` | app/api/users.py:136 | src/pages/admin/People.jsx:99 | JWT | admin | - | - | 200 | 200 (browser + API); negative checks 10/10 | PASS | - |
| GET | `/api/users/reviewers` | app/api/users.py:127 | src/pages/tasks/Tasks.jsx:277 | JWT | any signed-in user (object rules inside) | - | - | 200 | 200 (browser + API); negative checks 7/7 | PASS | - |
| DELETE | `/api/users/{user_id}` | app/api/users.py:265 | none | JWT | admin | user_id | - | 200 | 200 (API workflow); negative checks 11/11 | WARNING | works, but no page or client calls it |
| GET | `/api/users/{user_id}` | app/api/users.py:184 | src/pages/profile/Profile.jsx:45 | JWT | any signed-in user (object rules inside) | user_id | - | 200 | 200 (browser + API); negative checks 8/8 | PASS | - |
| PATCH | `/api/users/{user_id}` | app/api/users.py:192 | src/pages/admin/People.jsx:25 | JWT | admin | user_id | body:UserUpdate | 200 | 200 (API workflow); negative checks 19/19 | PASS | fixed: admin password reset ends the person's tokens |
| POST | `/api/users/{user_id}/activate` | app/api/users.py:257 | src/pages/admin/People.jsx:137 | JWT | admin | user_id | - | 200 | 200 (API workflow); negative checks 11/11 | PASS | - |
| GET | `/api/users/{user_id}/activity` | app/api/users.py:335 | src/pages/profile/Profile.jsx:47 | JWT | any signed-in user (object rules inside) | user_id, limit? | - | 200 | 200 (browser + API); negative checks 8/8 | PASS | fixed: unknown user now 404 (was 200 with an empty list) |
| POST | `/api/users/{user_id}/convert` | app/api/users.py:281 | src/pages/admin/People.jsx:68 | JWT | admin | user_id | body:ConvertIn | 200 | 200 (API workflow); negative checks 19/19 | PASS | - |
| POST | `/api/users/{user_id}/deactivate` | app/api/users.py:248 | src/pages/admin/People.jsx:153 | JWT | admin | user_id | body:DeactivateIn | 200 | 200 (API workflow); negative checks 19/19 | PASS | - |
| GET | `/api/users/{user_id}/history` | app/api/users.py:324 | src/pages/profile/Profile.jsx:48 | JWT | any signed-in user (object rules inside) | user_id | - | 200 | 200 (browser + API); negative checks 8/8 | PASS | - |
| GET | `/api/tasks/{task_id}/workspace` | app/api/workspaces.py:125 | src/pages/workspace/Workspace.jsx:156 | JWT | any signed-in user (object rules inside) | task_id | - | 200 | 200 (browser + API); negative checks 8/8 | PASS | - |
| GET | `/api/templates` | app/api/workspaces.py:429 | src/pages/workspace/ProjectWizard.jsx:12 | JWT | any signed-in user (object rules inside) | - | - | 200 | 200 (API workflow); negative checks 7/7 | PASS | - |
| POST | `/api/workspaces/{ws_id}/copy` | app/api/workspaces.py:374 | src/pages/workspace/Workspace.jsx:249 | JWT | any signed-in user (object rules inside) | ws_id | body:PathMove | 201 | 201 (API workflow); negative checks 16/16 | PASS | - |
| GET | `/api/workspaces/{ws_id}/download` | app/api/workspaces.py:413 | src/pages/workspace/Workspace.jsx:276 | JWT | any signed-in user (object rules inside) | ws_id | - | 200 | 200 (API workflow); negative checks 8/8 | PASS | - |
| PUT | `/api/workspaces/{ws_id}/files` | app/api/workspaces.py:149 | src/pages/workspace/Workspace.jsx:170; src/pages/workspace/Workspace.jsx:233 | JWT | any signed-in user (object rules inside) | ws_id | body:FileSave | 200 | 200 (browser + API); negative checks 16/16 | PASS | - |
| DELETE | `/api/workspaces/{ws_id}/files/{file_id}` | app/api/workspaces.py:216 | src/pages/workspace/Workspace.jsx:253 | JWT | any signed-in user (object rules inside) | ws_id, file_id | - | 200 | 200 (API workflow); negative checks 8/8 | PASS | - |
| POST | `/api/workspaces/{ws_id}/files/{file_id}/rename` | app/api/workspaces.py:196 | none | JWT | any signed-in user (object rules inside) | ws_id, file_id | body:FileRename | 200 | 200 (API workflow); negative checks 16/16 | WARNING | works, but no page or client calls it |
| GET | `/api/workspaces/{ws_id}/files/{file_id}/versions` | app/api/workspaces.py:227 | src/pages/workspace/Workspace.jsx:281 | JWT | any signed-in user (object rules inside) | ws_id, file_id | - | 200 | 200 (API workflow); negative checks 8/8 | PASS | - |
| POST | `/api/workspaces/{ws_id}/files/{file_id}/versions/{version_id}/restore` | app/api/workspaces.py:256 | src/pages/workspace/Workspace.jsx:286 | JWT | any signed-in user (object rules inside) | ws_id, file_id, version_id | - | 200 | 200 (API workflow); negative checks 8/8 | PASS | - |
| DELETE | `/api/workspaces/{ws_id}/folder` | app/api/workspaces.py:397 | src/pages/workspace/Workspace.jsx:250 | JWT | any signed-in user (object rules inside) | ws_id, path? | - | 200 | 200 (API workflow); negative checks 8/8 | PASS | - |
| GET | `/api/workspaces/{ws_id}/history` | app/api/workspaces.py:238 | src/pages/workspace/Workspace.jsx:150 | JWT | any signed-in user (object rules inside) | ws_id, path?, limit? | - | 200 | 200 (API workflow); negative checks 8/8 | PASS | - |
| POST | `/api/workspaces/{ws_id}/move` | app/api/workspaces.py:339 | src/pages/workspace/Workspace.jsx:248 | JWT | any signed-in user (object rules inside) | ws_id | body:PathMove | 200 | 200 (API workflow); negative checks 16/16 | PASS | - |
| POST | `/api/workspaces/{ws_id}/submit` | app/api/workspaces.py:271 | src/pages/workspace/Workspace.jsx:293 | JWT | any signed-in user (object rules inside) | ws_id | body:body | 201 | 201 (browser + API); negative checks 16/16 | PASS | - |
| POST | `/api/workspaces/{ws_id}/template` | app/api/workspaces.py:436 | src/pages/workspace/ProjectWizard.jsx:16 | JWT | any signed-in user (object rules inside) | ws_id | body:TemplateApply | 201 | 201 (API workflow); negative checks 16/16 | PASS | - |
| GET | `/api/health` | app/main.py:73 | none (server health check) | none | public | - | - | 200 | 200 (API workflow); negative checks 6/6 | PASS | - |
| WS | `/ws` | app/main.py | src/context/NotificationContext.jsx | JWT in ?token= | any signed-in user | - | - | 101 | connects with a token, live notification and chat events received (API script + browser shows 'live'); no/bad token closed 4401 | PASS | - |
| WS | `/ws/terminal` | app/main.py | src/pages/workspace/Terminal.jsx | JWT in ?token= | owner of the workspace | - | - | 101 | no token / foreign workspace refused; with a valid token it answers a clear 'runner not available' message | BLOCKED | the shell itself needs Docker |

### Mapping lists

- **Backend endpoints with no frontend call (4, WARNING)**: `DELETE /api/users/{user_id}` (the People page uses
  deactivate), `POST /api/workspaces/{ws_id}/files/{file_id}/rename` (the editor uses `move`),
  `GET /api/sessions/current`, `GET /api/dashboard/developer`. All four work when called. Not removed (rule: do not delete).
- **Frontend calls with no backend route**: none.
- **Duplicate endpoints**: none. `rename` and `move` overlap in purpose.
- **Wrong mappings (method, path, field names)**: none found.
- `POST /api/debug/client` is no longer part of the API outside the hosted preview (fix S3), so it is not in the table.

## 8. Tests

| Suite | Before | After | New |
|---|---|---|---|
| Backend `pytest` | 80 | 90 | `tests/test_api_audit.py`: 10 tests (logout, password change, admin reset, extension token, activity 404, report dates, debug endpoint, SQLite foreign keys, FK indexes) |
| Frontend `vitest` | 59 | 62 | `src/tests/audit.test.jsx`: 3 tests (label linking, new token after password change) |
| Extension `node --test` | 5 | 5 | – |
| Live scripts (need a running server) | 2 | 6 | `audit_matrix.py`, `audit_functional.py`, `audit_extra.py`, `audit_db.py` |
| Browser scripts | 0 | 2 | `audit/e2e_sweep.mjs`, `audit/e2e_flows.mjs` |

Proof that the new tests test something: on the old code 8 of the 10 new pytest tests fail; on the fixed code all pass.

Two existing tests were changed: `tests/test_timer.py` reused a token after logout (that was the weakness S1), it now
signs in again; `tests/test_execution.py` waited 5 s for a background cleanup and failed once under load, it now waits up to 15 s.

## 9. Problems found and fixed

| # | Problem (confirmed by a real request) | Root cause | Fix | Files | Retest |
|---|---|---|---|---|---|
| S1 | A token still worked after **logout**, after a **password change** and after an **admin password reset** (until it expired, 12 hours). A stolen token could not be cut off. | The JWT was only checked for signature and expiry. | `users.token_version` is stored in the token (`ver`). Logout, password change and admin reset raise it; older tokens get 401. Change-password returns a new token, the profile page stores it. | `app/database/models.py`, `app/core/security.py`, `app/dependencies/auth.py`, `app/api/auth.py`, `app/api/users.py`, migration `0006`, `frontend/src/pages/profile/Profile.jsx` | 5 pytest tests, API script, browser (2 checks) |
| S2 | `GET /api/users/999999/activity` answered 200 with an empty list. | No existence check. | 404 "User not found". | `app/api/users.py` | pytest + matrix |
| S3 | `POST /api/debug/client` was public on every server and read a 100 KB body without sign-in. | A preview helper was always registered. | Registered only when `ALLOW_QUERY_TOKEN` is on (hosted preview). The frontend already called it only in the preview build. | `app/main.py` | pytest + API script (404) |
| S4 | `GET /api/reports/summary` with end before start answered 200 with wrong data. | The start date was silently moved. | 422 with a clear message. | `app/api/reports.py` | pytest + API script |
| S5 | The server started silently with the built-in default `JWT_SECRET`. | No check. | A clear warning in the log at startup (the server still starts, nothing breaks). | `app/main.py` | manual run |
| D1 | SQLite did not enforce foreign keys (PostgreSQL does), so local runs could hide broken relationships. | `PRAGMA foreign_keys` is off by default. | Turned on for every SQLite connection. | `app/database/connection.py` | pytest; all 90 tests and all live flows pass with it on |
| D2 | 21 foreign-key columns had no index (slow joins and deletes when tables grow). | Not declared. | `index=True` in the models + migration `0006` (additive, with downgrade). | `app/database/models.py`, `migrations/versions/0006_audit_hardening.py` | pytest + `audit_db.py` + `alembic check` |
| F1 | Form labels were not linked to their inputs: a click on the label did nothing and screen readers read no name. | `Field` rendered `<label>` without `for`. | `Field` gives the input an id and links the label. | `frontend/src/components/ui.jsx` | vitest (2) + browser |
| T1 | One existing test was timing-dependent (see section 8). | 5 s wait. | 15 s wait. | `tests/test_execution.py` | suite run 3 times |

**Behaviour changes you will notice**: signing out, or changing a password, now signs that person out in every
browser (the browser that changed the password stays signed in). Tokens issued before this update keep working until
the first logout or password change.

Not a problem (script mistakes, corrected in the scripts, not in the app): template apply returns 201; the extension
endpoints need the extension token; `ERR_ABORTED` lines in the first browser run came from the script reloading the page too early.

## 10. Performance and security

**Response time** (local SQLite, small data): slowest request in 1280 matrix calls 27 ms; all list endpoints 6–17 ms.

**Query count when the data grows** (tasks 9 → 49; a growing number would mean an N+1 problem):

| Endpoint | Rows | SQL statements | ms |
|---|---|---|---|
| `/tasks` | 9 → 49 | 6 → 5 | 11 |
| `/users` | 8 → 8 | 18 → 18 | 12 |
| `/submissions?view=all` | 8 → 8 | 18 → 18 | 10 |
| `/dashboard/admin` | 0 → 0 | 16 → 16 | 11 |
| `/reports/summary` | 7 → 7 | 13 → 13 | 11 |
| `/sessions/live` | 1 → 1 | 2 → 2 | 7 |
| `/teams` | 4 → 4 | 10 → 10 | 9 |
| `/audit-logs` | 136 → 176 | 2 → 2 | 17 |
| `/recordings` | 3 → 3 | 4 → 4 | 9 |
| `/timer/overview` | 8 → 8 | 14 → 14 | 13 |
| `/notifications` | 14 → 14 | 3 → 3 | 8 |
| `/chat/conversations` | 0 → 0 | 2 → 2 | 7 |
| `/meetings` | 4 → 4 | 10 → 10 | 10 |
| `/ai/usage` | 2 → 2 | 7 → 7 | 9 |
| `/languages` | 71 → 71 | 1 → 1 | 8 |
| `/projects` | 4 → 4 | 2 → 2 | 6 |

No endpoint's statement count grew with the data. This was measured with 49 tasks, not with thousands of rows.

**Security checks**

| Check | Result |
|---|---|
| SQL injection | PASS: all queries go through the SQLAlchemy ORM with bound parameters; no SQL built from strings found; injection strings in the login form, people search, audit-log filter and AI history search returned 401 / 0 rows and changed nothing |
| Input validation | PASS: Pydantic schemas on every body; 422 on bad input |
| CORS | PASS: only the origins in `CORS_ORIGINS` get the header; other origins get none |
| Security headers | PASS: present on responses |
| Secrets in responses | PASS: password hashes never returned; AI keys write-only (`key_set`), encrypted in the database, not in the page |
| Secrets in logs | PASS: the 401 log line records only whether a header was present, never the token |
| Upload security | PASS: size limits, extension block, path traversal refused |
| Token lifetime | FIXED (S1) |
| Default `JWT_SECRET` | WARNING (W1) |
| Token stored in `localStorage` | WARNING (W2) |

## 11. Final numbers

**Backend**

| | Count |
|---|---|
| Total APIs | 131 (129 HTTP + 2 WebSocket) |
| Working (PASS) | 123 |
| Failed | 0 |
| Warnings | 4 |
| Not tested | 0 |
| Blocked | 4 |

**Frontend**

| | Count |
|---|---|
| Total API call sites | 137 |
| Working integrations | 137 (135 matched in code, 2 run-time addresses confirmed in the browser). 61 distinct endpoints were seen answering 2xx from the real browser; the rest were confirmed against the backend by API scripts only |
| Failed integrations | 0 |
| Missing APIs | 0 |
| Incorrect mappings | 0 |

**Integration**

| | Count |
|---|---|
| Workflows tested in the browser | 34 checks + 72 page loads (file download buttons not clicked) |
| Successful | 34 + 72 |
| Failed | 0 |
| Blocked | 1 (real code run and terminal: Docker) |

**Fixes**

| | Count |
|---|---|
| Application files modified | 11 (8 backend, 2 frontend, 1 new migration) |
| API behaviours fixed | 6 endpoints (logout, change-password, user update, activity, report summary, debug) |
| Frontend integrations fixed | 2 (password change token, form labels) |
| Database issues fixed | 2 (foreign keys enforced on SQLite, 21 indexes) |
| Tests added | 13 automated (10 pytest, 3 vitest) + 4 live scripts + 2 browser scripts |

## 12. Remaining issues

| # | Status | Issue | Suggested next step |
|---|---|---|---|
| B1 | BLOCKED | `POST /workspaces/{id}/run`, `POST /submissions/{id}/run`, `POST /languages/{id}/pull`, `/ws/terminal` shell: need Docker. Here they answer an honest 503 / clear message; unit tests cover them with a fake Docker only. | Run the audit scripts on a PC with Docker Desktop |
| N1 | DONE (PASS) | PostgreSQL: tested after the first report, see `LOCAL_SETUP.md` | – |
| N2 | NOT TESTED | Chrome extension inside real Chrome (only its node tests and its two endpoints) | Manual test |
| N3 | NOT TESTED | A real AI provider in this audit (a local test provider was used; Gemini was last verified in Build 18) | Ask one question in the preview |
| N4 | NOT TESTED | Separate "Developer" login: the role does not exist as an account type | Decide if it is needed |
| W1 | WARNING | The server still starts with the default `JWT_SECRET` (now with a warning). | Set a long random `JWT_SECRET` in `backend/.env`; optionally refuse to start without it |
| W2 | WARNING | The login token is kept in `localStorage`; a script injection in the page could read it. No injection point was found (no raw HTML rendering). | An httpOnly cookie is a bigger change; not done |
| W3 | WARNING | 4 endpoints have no caller in the frontend (section 7). | Keep or remove later |
| W4 | WARNING | `GET /tasks`, `/users`, `/submissions` have no paging. Fine for a company-size list, slow for thousands of rows. | Add `limit` / `offset` when needed |
| W5 | WARNING | The dashboard requests `GET /attendance` twice on first load. | Small frontend cleanup |
| W6 | WARNING | Login rate limit and AI rate limit are kept in memory: they reset on restart and are per server process. | Fine for one server |
| Q1 | OPEN | Download buttons for non-admin roles, reviewer zip download, copy block for Admin: waiting for your decision (asked in Build 17.1). | – |

## 13. How to repeat the audit

```
cd backend
export JWT_SECRET=audit-secret-not-for-production-000000001 DATABASE_URL=sqlite:////tmp/audit/audit.db STORAGE_DIR=/tmp/audit/storage
alembic upgrade head && python -m app.demo_seed
LOGIN_RATE_LIMIT=1000 uvicorn app.main:app --port 8010 &
python scripts/fake_ai_provider.py 9911 &
export AUDIT_DB=/tmp/audit/audit.db WORKCODE_API=http://127.0.0.1:8010/api
python scripts/audit_inventory.py          # routes and frontend calls
python -W ignore scripts/audit_matrix.py   # run first, on a fresh database
python scripts/audit_extra.py
python -W ignore scripts/audit_functional.py
python scripts/live_task_check.py
python scripts/live_ai_check.py            # deletes all AI providers: test database only
python scripts/audit_db.py
# browser (needs playwright-core and Chromium): build the frontend, serve it with WORKCODE_API=http://127.0.0.1:8010
cd ../audit && node e2e_flows.mjs && node e2e_sweep.mjs
python build_report.py                     # rebuilds the table in section 7
```

Raw outputs: `audit/matrix.json`, `functional.json`, `extra.json`, `coverage.json` (status codes seen per endpoint and
run), `e2e_flows.json`, `e2e_sweep.json`, `db_*.json`, `perf.json`, `access.log` (server log of the final run), `shots/`.
