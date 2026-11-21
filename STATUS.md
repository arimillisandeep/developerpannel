# Build status

## Done and tested
- Phase 2: schema (29 tables), role and permission matrix, Alembic migration
- Phase 3: JWT login, bcrypt passwords, login rate limit, role-guarded routes
- Phase 4 (core): admin dashboard, people CRUD, deactivate / soft delete, role conversion with
  history, three-admin limit, intern seats, teams, departments, projects, audit log, live sessions
- Phase 5 (core): developer dashboard, my team, team-scoped task assignment, first review
- Phases 6-8 (core): on-roll, off-roll and intern dashboards and menus
- Phase 9: tasks and the two-stage review workflow, comments, resubmission versions
- Phase 10 (part): workspace with Monaco, server-side files, autosave, version history and restore,
  upload, rename, delete, submit, sandboxed HTML preview
- Phase 11 (part): server-authoritative timer, single reporting tab, attendance per day
- Phase 13 (part): notifications over WebSocket with bell, unread count, mark read

## Not built yet
- Code execution (Python, Java, C, C++, Node, SQL): needs the Docker runner. No Run button is shown.
- Screen recording: table exists, no capture, upload or playback yet.
- Chat and meetings: tables exist, no API or pages yet.
- Reports with CSV / Excel export.
- Chrome extension for the "pause on unauthorised websites, except ChatGPT and Google Meet" rule.
  Until then the timer counts as "away" whenever the WORKCODE tab is not focused.
- Task attachments, deadline-approaching reminders, admin announcements.
- Monitoring filters by project, task and date; browser, chat and meeting activity.
- Redis / Celery (nothing needs a background queue yet).
- Rate limiting covers login only.


## Build 8 – communication, recordings, reports (added)

Done and tested (backend 40 tests, frontend 24 tests):
- **Meetings** – `/api/meetings`: Admin, Developer and On-Roll schedule; Developer invites own team/admins/developers; On-Roll cannot invite admins; cancel keeps history; invitees get a notification. Page: Meetings.
- **Chat** – `/api/chat`: direct, group (Admin/Developer/On-Roll) and announcement channels (Admin posts only), unread counts, read status, live delivery over the WebSocket. Not built: attachments.
- **Screen recording** – `/api/recordings`: consent required, WebM chunks stored under `STORAGE_DIR` (default `backend/storage`, set it in `.env`), size limits, type check, statuses recording/completed/interrupted/failed, playback only for the owner, their team's Developer and Admins (audited). Header **Record** button, Recordings page. A page reload ends a recording (browser rule) and it is marked interrupted. **The capture itself could not be tried in the sandbox (no browser) – test it in Chrome.**
- **Reports** – `/api/reports/summary` with `format=json|csv|xlsx`, date range; Admin all, Developer own team, others self.
- **Internet** page – links to the approved tools (ChatGPT, Google Meet). The timer still counts them as away until the Chrome extension exists.

Still not built: Docker code runner (Run button), Chrome extension, chat/task attachments, deadline reminders, monitoring filters, Redis/Celery, "Local (0)" header item from the old app (its purpose is unknown).
No new database migration was needed (tables already existed in 0001).


## Build 10–11 – full screen, 70 languages, isolated code runner

- **Full screen** button in the coding workspace (also F11 / Esc).
- **Language list** in one place: `backend/app/core/languages.py` (71 entries). `GET /api/languages` feeds the editor (highlighting, "New file" templates) and the admin **Languages** page.
  - 39 run in the Docker runner (Python, JavaScript/Node, TypeScript, Java, C, C++, SQL/SQLite, PostgreSQL, C#, Go, Rust, PHP, Ruby, Perl, Lua, R, Julia, Kotlin, Swift, Dart, Bash, PowerShell, Haskell, Elixir, Erlang, OCaml, Nim, Common Lisp, Prolog, Fortran, Octave/MATLAB, Pascal, D, Crystal, Groovy, Racket, Scala, AWK).
  - HTML/CSS use the browser preview.
  - The rest are edit-only (React, Express, Next.js, Vue, Nuxt, Svelte, Angular need npm packages and a running server; the runner has no network).
- **Runner** `backend/app/services/runner.py`: one throw-away container per run, `--network none`, read-only root, project mounted read-only, non-root user, all capabilities dropped, memory/CPU/process limits, time limit, output limit, Stop button. Without Docker the run is refused with a clear message; code is never run on the host.
- Admin installs each language image from the Languages page (or `docker pull <image>`).

**Not verified:** the sandbox has no Docker, so no program was actually executed. Tests (45 backend, 28 frontend) check permissions, the Docker flags, timeout/kill and the no-Docker refusal with a fake Docker. The per-language images and commands are untested; expect some to need a fix on first real run – Python, Node, Java, C, C++ are the most standard.
Editor colouring: Monaco has no grammar for Haskell, Erlang, OCaml, Nim, Fortran, Prolog, MATLAB, COBOL, Assembly, Zig, AWK – these show as plain text.


## Build 12 – terminal

- **Terminal** tab in the coding workspace. WebSocket `/ws/terminal?token=&workspace_id=&language=`; a shell in the same locked-down Docker container as Run (no network, read-only root, limits, non-root), owner only, one terminal per user, idle limit 10 min, session limit 60 min, container killed on close.
- It is line-based (type a command, press Enter). There is no PTY, so full-screen programs (vim, nano, top), Ctrl+C and tab-completion do not work; stop a stuck command with "Close terminal".
- The container gets a copy of the saved files. Files created or changed in the terminal are not written back to the workspace. No internet, so `pip install` / `npm install` do not work.
- Not verified with real Docker (none in the sandbox); tested with a fake shell process (47 backend tests, 29 frontend tests).

## Build 15: automatic work timer
Done and tested (backend 60 tests, frontend 42 tests, extension logic 5 tests): server-decided timer states with a transition log,
5-minute inactivity pause with a 4-minute warning, approved-website allowlist (admin), extension endpoints with a scoped token,
timer report with Today / Yesterday / This week / This month / Custom filters, pause history and CSV export, Chrome extension files.
Not verified: the Chrome extension running in a real browser. Not built: per-user timer settings, WebSocket push of timer state
(the page polls every 15 s). Details: `TIMER.md`.


## Build 16 — task workflow, reviews, versions

See `TASKS.md`. Backend tests 70, frontend tests 46, extension tests 5, live flow check 35/35 (SQLite). Migration `0004_task_workflow` tested on an empty database and on a build-15 database. Not verified here: PostgreSQL, Docker run, anything visual in a real browser.

## Build 17 — AI coding assistant

Done: right-side AI panel in the workspace (resizable, collapsible), streaming chat through the backend to any
OpenAI-compatible provider, project context (open file, selection, files, tree, whole project, terminal, run errors),
insert/replace/create actions in Monaco, diff preview with per-file accept/reject and versioned apply, commands to the
terminal input with confirmation for risky ones, private history (search, rename, delete, saved answers),
Admin page for providers/keys/models/roles/limits/usage. Migration `0005`. Details: `AI.md`.

Tests: backend pytest 80, frontend vitest 58, extension 5, live task flow 35/35, live AI flow 54/54 (fake provider).

Not verified: a real model's answers (no key in the build sandbox), the panel in a real browser, PostgreSQL.

## Build 17.1 — copy protection

For every role except Admin: copy/cut anywhere in WORKCODE never puts the real text on the computer's clipboard
(a notice is put there instead); the text stays usable for paste inside WORKCODE. Paste from other programs works
as before. Dragging text out is blocked. Code: `frontend/src/services/copyGuard.js`, switched on in `AppLayout.jsx`.
Limits: a browser cannot stop screenshots, retyping or developer tools; the Download buttons still exist.

## Build 18 — human-readable code rules

Style rules added to the assistant prompt (see `AI.md` section 7). Backend pytest 80. Checked on a real Gemini model (`gemini-3.5-flash-lite`).

## Build 19 – API audit (13 Nov 2026)

Full report: `API_AUDIT.md`. No redesign, no file deleted.

- Tested: 129 HTTP endpoints + 2 WebSockets with real requests on an isolated test database, and the React app in headless Chromium for 5 logins.
- Result: 123 PASS, 4 WARNING, 4 BLOCKED (Docker), 0 FAIL after the fixes.
- Fixed: tokens now stop working after logout / password change / admin reset (`users.token_version`, migration 0006);
  activity of an unknown user → 404; report with end before start → 422; debug endpoint only in the hosted preview;
  warning for a default `JWT_SECRET`; SQLite enforces foreign keys; 21 foreign-key indexes; form labels linked to inputs.
- Tests: pytest 90, vitest 62, extension 5.
- After updating an existing installation run `alembic upgrade head` once.
- Not verified: PostgreSQL, Docker run and terminal, extension in real Chrome.

## Build 19.1 – local run with PostgreSQL (13 Nov 2026)

- New: `LOCAL_SETUP.md`, `backend/setup_local.py`, `setup.bat`, `start-backend.bat`, `start-frontend.bat`.
- Tested on a real PostgreSQL 17 server: pytest 90, matrix 1280, API workflows 190 + 14, task flow 35, AI flow 54, browser 34 + 72 pages. No application code had to change for PostgreSQL.
- Tests can run on PostgreSQL with `TEST_DATABASE_URL` (database name must contain `test`).
- Not tested: the `.bat` files on Windows, Docker Run, extension in real Chrome.

## Build 20 – all data in the database (13 Nov 2026)

- Task attachments are stored in `task_attachments.data`; screen recordings in the new table `recording_chunks`. Nothing new is written to the `storage` folder.
- Migration 0007 copies existing files from `storage` into the database (files on disk are kept).
- Old rows without database content are still read from disk.
- Tests: pytest 94 on SQLite and 94 on PostgreSQL 17; live checks on PostgreSQL: matrix 1280, workflows 190 + 14, task flow 35, AI flow 54, browser 34; 80 MB recording round trip byte-identical.
- Details: `LOCAL_SETUP.md`, section "Where the data is stored".

## Build 20.1 – 20.4 (frontend fixes)

- 20.1: dialogs render under `<body>` (the Record dialog was clipped inside the top bar).
- 20.2 / 20.3: AI panel layout. The editor keeps at least 420px, the AI panel at least 300px; in a small window the AI panel and the file list take turns.
- 20.4: the **Internet** page is removed (menu item, route `/internet`, page file). The backend endpoints are unchanged. Side effect: only admins (Monitoring) can create a browser-extension connection code now.
- Docker mode: `docker-compose.yml`, Dockerfiles; Run and the terminal work there (see `LOCAL_SETUP.md`).

## Build 21 – real terminal

- Terminal tab = xterm.js + a pseudo terminal on the server (`runner.PtyShell`, `docker run -it`). Raw keys, resize, Ctrl+C, Tab, colours.
- Two-way file sync between the workspace and the terminal folder (`app/services/terminal_sync.py`, every 1.5 s while a terminal is open). Dependency / build folders are not synced. File versions written by the shell have kind `terminal`.
- New settings: `TERMINAL_NETWORK` (`none` default, `bridge` in docker-compose.yml), `TERMINAL_MEMORY_MB`, `TERMINAL_TMP_MB`.
- WebSocket `/ws/terminal`: new query `cols`, `rows`; new client message `resize`; new server messages `files`, `note`.
- Not done: several terminals at once, split terminals, a registry-only network filter (it is all or nothing), terminal when the backend runs directly on Windows.
- Tests: pytest 97, vitest 61. Checked with real Docker on Linux, both with the backend on the host and with `docker compose`.

## Build 22 – Explorer works like VS Code

- New File / New Folder / Rename open a name box inside the file tree (no dialog). Enter or a click elsewhere confirms, Esc cancels, a wrong or duplicate name shows a message under the box.
- The new item goes into the selected folder, or next to the selected file. `src/utils/a.js` as a name creates the folders too.
- Right-click menu on files, folders and empty space: New File, New Folder, New File from Template, Rename (F2), Duplicate, Delete (Del).
- "Collapse folders" button in the Explorer header.
- An empty folder is stored as a hidden `<folder>/.gitkeep` file, because the server keeps files only.
- Not built: drag and drop to move, multi-select, cut / copy / paste of files.

## Build 23 – dev server preview

- A web server started in the terminal (`npm run dev`, `npm start`, `flask run`, `python -m http.server` ...) can be opened in the **Preview** tab ("Terminal server") or in a new browser tab.
- How: the terminal container publishes the ports in `TERMINAL_PORTS` on free ports of `TERMINAL_PORTS_BIND` (127.0.0.1). The server tells the browser the mapping (`{"type":"ports"}` on `/ws/terminal`). When the terminal prints an address such as `http://localhost:5173/`, the Preview tab switches to it.
- The program must listen on all addresses (`--host 0.0.0.0`); Vite prints a hint and the terminal repeats the exact command.
- Needs `TERMINAL_NETWORK=bridge`. The published ports have no login; they are reachable only from the same computer unless `TERMINAL_PORTS_BIND` is changed.
- Only the listed ports work. The ports close when the terminal is closed.

## Build 24 – several terminals, preview status line

- Up to 4 terminals at the same time (tabs "Terminal 1", "Terminal 2" ... and a ＋ button in the Terminal panel; `TERMINAL_MAX_PER_USER`).
- All terminals of a workspace are shells (`docker exec`) in one container (`docker run -d`), so they share files, installed packages and localhost: a server started in terminal 1 can be called with `curl localhost:3000` from terminal 2.
- Removing a terminal tab stops what that terminal started; the container is removed when the last terminal closes.
- One environment (image) for all open terminals; the choice is locked while a terminal is open.
- Limits changed: idle 30 minutes without a key in any terminal (was 10), longest life 4 hours (was 1). Memory, CPU and the process limit are shared by all terminals.
- Preview → Terminal server shows a status line read from inside the container: port answering / listens on localhost only / nothing listening. The frame reloads by itself when the server comes up.

## Build 25 – Docker mode with the PC's own PostgreSQL

- `docker-compose.localdb.yml`: backend connects to `host.docker.internal:<LOCAL_PGPORT>`; the `db` container is not started. Values come from `.env` next to the compose files.
- `setup_local.py` in Docker mode now switches `backend/.env` to the chosen database without asking (secrets kept).

## Build 26 – forgot password

- Login: field "Email or username" (username = employee code such as WC-E0005), link **Forgot password?**.
- `/forgot-password` -> `POST /api/auth/forgot-password {email}`: same answer for every address; for an active account a mail goes to the address in its `users` row.
- Token: 32 random bytes, only its SHA-256 in table `password_reset_tokens` (migration 0008), 30 minutes, single use; a new request cancels earlier links. It travels after `#` in the link, so no server log sees it.
- `/reset-password` -> `POST /api/auth/reset-password/validate {token}` and `POST /api/auth/reset-password {token, new_password}`: strength rules (8+, small, capital, number, symbol), bcrypt hash, `token_version` + 1 (all sessions signed out), audit rows.
- Mail: `app/services/mailer.py`, Gmail API (refresh token) or SMTP (Gmail app password); settings in `backend/.env` (see LOCAL_SETUP.md). Not set up -> 503, nothing is pretended.
- Limits: 5 requests per address and per computer in 15 minutes.

## Build 26.1

- Fix: "token: String should have at least 20 characters" on Save password. In development mode (`npm run dev`, the Docker setup) React StrictMode runs effects twice; the second run emptied the reset token. Guard added in `ResetPassword.jsx`, vitest case under StrictMode, checked in a browser against the Vite dev server.

## Build 26.2

- Forgot password now says "Email not found, please enter the correct email." (404) for an address without an account, "This account is deactivated" (403) for a switched-off one, and "The reset e-mail could not be sent" (502) when the mail service fails (reason in the audit log). Success: "A password reset link has been sent to <address>." The mail is sent before the answer. Requested by the owner; the earlier "same answer for every address" rule is dropped, the limit of 5 requests / 15 minutes stays.

## Build 27 – meeting timer

A second timer for scheduled external meetings (Google Meet, Zoom, Teams). The work timer is unchanged: no line of
`app/services/timer.py`, `app/api/sessions.py` or `TimerContext.jsx` was edited, and the new code never reads or writes
`work_sessions`, `attendance` or `timer_events`.

- Table `meeting_attendance` (migration 0009, additive): one row per stay = meeting, person, joined, left, how it was detected, why it ended.
- Automatic: the browser extension (v1.1.0) gets the links of the person's meetings that are open now, compares them with
  the open tabs inside the browser and reports only the meeting ids. Tab open = joined, tab closed = left.
  Meet: same meeting code. Zoom: same meeting number. Teams: any Teams tab during the meeting window.
- Fallback: **Join** on the Meetings page starts the meeting timer, **Leave meeting** (top bar or Meetings page) stops it.
  Used without the extension or when the meeting runs in a desktop program.
- Safety: no report for 150 s = ended at the last report; a stay started with the button ends at the latest 1 hour after the planned end;
  one meeting at a time; a cancelled meeting ends the stay. Joinable from 15 minutes before the start until 3 hours after the planned end.
- Shown: top bar pill next to the work timer; Meetings page ("Today in meetings"); Admin dashboard and My Team card
  "Work time and meeting time" with both timers in separate columns and join / leave details per person.
- API: `POST /api/meetings/{id}/join`, `POST /api/meetings/{id}/leave`, `POST /api/meetings/timer/ping`,
  `GET /api/meetings/timer/report?start&end`, `GET` + `POST /api/extension/meetings`.
- Not built: Google Meet / Zoom / Teams server APIs and webhooks (they need a paid Workspace / a Zoom app and a public https address;
  WORKCODE on localhost cannot receive them). "Tab open" is taken as "in the meeting", so time in the waiting room counts too.

## Build 29 – 8 h workday schedule, Continue schedule, automatic workspace recording

(Build 28, a Google Meet API experiment, was reverted at the owner's request; the number stays unused.)

- **8 h regular schedule** (`work_sessions.schedule = regular`, `attendance.regular_completed_at`):
  Developer / On-Roll / Off-Roll count active time toward `WORKDAY_TARGET_HOURS` (default 8). The server decides —
  when the day's active seconds reach the target, the regular session closes with `end_reason=day_complete` and the
  day is marked complete. Interns and Admins keep the free-running timer (no target).
- **Separate Continue schedule**: after the 8 h are done the top bar shows *Continue Working*; starting it opens a
  session with `schedule=extra`. Its time goes to `attendance.extra_seconds` and the session rows only — the regular
  day totals never move. Stopping, refreshing, logging out and reconnecting are handled by the same server-side
  machinery as the regular timer; an automatic start never opens an extra session by itself, and after the day is
  done an automatic start starts nothing at all (the button is the decision).
- **Payload / API**: `/api/sessions/*` answers gained `schedule_target_seconds`, `regular_completed`,
  `regular_completed_at`, `regular_remaining_seconds`, `extra_seconds_today`, `today.extra_seconds`, `session.schedule`;
  new `POST /api/sessions/continue`. `GET /api/attendance` includes `extra_seconds` + `regular_completed_at`.
  `GET /api/timer/overview` (JSON and CSV) has *Recording now*, *Continue today*, *8 h done* columns and per-row
  `schedule` ("continue" while the extra session runs). `/api/reports/summary` has `extra_hours` and `full_days`
  (days with a completed regular schedule); Continue hours are counted even on extra-only days.
- **Automatic workspace recording**: opening a coding workspace starts the screen recording — after one consent per
  person (WORKCODE dialog, remembered) and the browser's own permission prompt, never silently. Status pill in the
  IDE bar: *Recording Active* / *Recording Paused* / a restart button after a stop or refresh; Pause / Resume drive the
  browser's real recorder. Closing the workspace or signing out stops it; a refresh ends the browser capture and the
  server marks it `interrupted`. The top-bar Record button still records anywhere else, now with Pause too.
- **Retention (F)**: every recording gets `screen_recordings.retention_until` (now + `RECORDING_RETENTION_DAYS`, default 30).
  The recording list sweep deletes finished recordings past that date together with their chunks; a recording that is
  still capturing is never purged. `GET /api/recordings/policy` answers what the consent dialog promises.
  Videos stay in the private per-user store the platform already uses (chunks in PostgreSQL, served only through the
  permission-checked streaming endpoint; `storage = "database"`). A separate S3-compatible bucket can replace that layer
  later; it is not enabled here because there are no cloud credentials — this is stated, not faked.
- **Migration `0010`** (additive): `work_sessions.schedule`, `attendance.extra_seconds`, `attendance.regular_completed_at`,
  `screen_recordings.retention_until`.
- Config: `WORKDAY_TARGET_HOURS`, `RECORDING_RETENTION_DAYS`.
- Tests: backend 133 passed (13 new in `tests/test_workday_schedule.py` — target close, extra isolation, 409 before done,
  auto-start stays off after completion, intern exemption, attendance / overview / reports fields, retention purge incl.
  "never purge while capturing", CSV columns, policy). Frontend 72 passed (4 new: Continue button calls
  `/sessions/continue`, progress text, extra label, report cells). `vite build` clean; sandbox preview verified against the
  real API (payload fields, policy JSON, CSV headers).

## Build 30 – completion popup, admin extra-work panel, report totals

- **Popup**: when the server closes an employee's regular 8 h schedule, WORKCODE asks
  "Your 8-Hour Work Schedule Is Completed!" with **Continue Working** / **Not Now**. Not Now is remembered per
  person per day (sessionStorage) and starts nothing; the popup also appears when someone opens the app after the
  day completed while the tab was closed, and disappears the moment a (continue) session is running.
- **Employee dashboard**: the working-time card now shows the running Continue schedule (extra today, apart from
  the 8 h) with the same Pause / Resume / Stop path, a *Continue Working* entry once the day is complete, an
  *Extra* and *8 h* column in the daily attendance table, and extra hours in the today summary.
- **Admin panel**: new "Extra work today" card on the Admin dashboard — Employee, Regular time (x/8 h), Completed /
  In progress, Extra time, Extra timer (Running) and the extra session's start → end. The timer report gained a
  **Schedule** column (Regular / Extra / Completed), **Regular Work** progress cell, an *Extra Working Time* column
  (running badge) and a *Range totals* line: Regular working hours, Extra working hours, Total working hours for the
  chosen filter (Today / Yesterday / Week / Month / Custom — already there). The CSV export adds
  *Extra total (s)*, *Extra start*, *Extra end*, *Schedule*.
- **Reports API**: per-person `total_hours` = active + extra; `extra_hours` counted even on extra-only days;
  `full_days` counts days with a completed regular schedule.
- No schema change (build 29's `0010` covers everything); no new timers — same `work_sessions` / `attendance` rows,
  same server-owned timer.
- Tests: backend 133 passed (overview fields, running/stopped extra session times, CSV headers, total_hours);
  frontend 77 passed (5 new: popup Not Now / Continue, Schedule column + range totals, admin card rows, employee
  continue-timer card). Build clean; live API + preview verified on the sandbox.

## Build 31 — the workspace recording follows the tab

User request: *"Open workspace chey gane automatic ga screen record avvali; bayataki osthe stop avvali."* The first half
existed since build 29 (not yet deployed on the PC, which still runs build 27); the second half is new here.

- **Opens by itself**: the workspace mount effect calls `recording.autoStart(taskId)` — consent remembered per person,
  the browser's own share dialog still asked, never bypassed; the recording is linked to the task (`/recordings/start`).
- **Never films what is outside the tab**: `RecordingContext` now watches `visibilitychange` / `blur` / `focus` (same
  signal the automatic timer uses). While a *workspace* recording runs and the page is not the window being looked at,
  the recorder is **paused at once** (nothing is captured, nothing is uploaded) and **closed and saved** if the person
  stays away longer than `RECORDING_AWAY_GRACE_SECONDS` (default 60; `0` = close immediately). Coming back resumes it by
  itself — pause/resume need no browser permission, so a quick alt-tab costs no footage and no re-prompt.
- **No fake restart**: after the grace closed a recording, the app does not pretend to still be recording. The browser
  only shares a screen after a real click, so the workspace pill changes to *Record screen again* and says why.
- **Honest UI**: the pill shows *Paused — you left the tab (Ns)* with a live countdown of the grace, and the consent
  dialog states the rule before anyone agrees. A recording started from the top-bar **Record** button is left alone —
  that one the person controls.
- **Policy**: `/api/recordings/policy` now also returns `away_grace_seconds`, so the promise in the dialog is the number
  in effect; the fetch moved behind the signed-in user (it used to 401 on the login page).
- No schema change, no new tables: same `screen_recordings` / `recording_chunks`, same retention rule.
- **Reports page** (Admin → Reports, and the employee's own "My reports"): the per-person table now shows
  **Active h · Extra h (Continue) · Total h** next to each other, and the "Active hours" tile adds the extra hours in its
  sub-line — the numbers the API already returned (`extra_hours`, `total_hours`) were only visible in the CSV until now.
- Tests: backend **134** passed (2 policy/away-grace assertions), frontend **83** passed (6 new: starts by itself and
  links the task, pauses off-screen and resumes on return, grace expiry closes and saves, `away_grace_seconds: 0`,
  manual Record button untouched, no self-restart). **Real browser check** (Chromium under Xvfb, fake screen device):
  opening the workspace recorded and uploaded (0 → 204 KB), leaving froze the file (204 436 → 204 436 for 12 s),
  returning resumed it (317 → 419 KB), and the 60 s grace closed it as `completed` with the chunks intact and
  downloadable (419 622 bytes, `0x1A45DFA3` WebM). No console or HTTP errors.
