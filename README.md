# WORKCODE v2 (fresh build)

Company management and developer workspace platform: FastAPI + SQLAlchemy + PostgreSQL backend,
React + Vite frontend.

## Run it on Windows (PowerShell)

**Step-by-step guide with PostgreSQL, a setup script and troubleshooting: see `LOCAL_SETUP.md`** (double-click `setup.bat`).
VS Code + PostgreSQL connection values per mode, and the "Forgot password" mail check (`backend/check_mail.py`),
are in `LOCAL_SETUP.md` as well.

The zip unpacks into a folder named **`workcode`** - `docker compose` must be run **inside that folder** (the one with
`docker-compose.yml` in it), not in the folder you unzipped into. `doctor.bat` says which folder is the right one.

Is your PostgreSQL usable by WORKCODE? Double-click **`check-db.bat`** - it reads `.env`, tests the password through
`psql`, and tests the connection **from inside a Docker container** (that last one is what the app needs).

Is "Forgot password" silent? `cd backend` and run `python check_mail.py you@example.com` - it reads `.env` the
way the API does and names the exact reason a mail was not sent.

Requirements: Python 3.11+, Node 20+, your PostgreSQL on port 5433.

### 1. Database (once)
This build uses its **own new database** so the old `workcode` database is never touched:

    createdb -p 5433 -U postgres workcode_v2

### 2. Backend

    cd backend
    python -m venv .venv ; .venv\Scripts\activate
    pip install -r requirements.txt
    copy .env.example .env        # then edit DATABASE_URL password and JWT_SECRET
    alembic upgrade head          # creates the 43 tables; never drops anything
    python -m app.seed you@company.com "Your Name"     # first Admin, asks for a password
    uvicorn app.main:app --port 8000

API docs: http://localhost:8000/docs

Optional, development only: `python -m app.demo_seed` creates one account per role
(`<role>@workcode.local` / `Workcode@123`). It refuses to run if the database already has users.

### 3. Frontend

    cd frontend
    npm install
    npm run dev                   # http://localhost:5173

The browser only calls `/api` and `/ws`; Vite forwards them to http://127.0.0.1:8000.

### Tests

    cd backend  ; python -m pytest        # 168 tests, run on a throw-away SQLite file
    cd frontend ; npm test                # 92 tests

## Rules built into the backend (`app/core/permissions.py`)

| Action | Admin | Developer | On-Roll | Off-Roll | Intern |
|---|---|---|---|---|---|
| Manage people, teams, audit log | yes | no | no | no | no |
| Assign tasks to | developer, on-roll, off-roll, intern | own team only | on-roll, off-roll, intern | nobody | nobody |
| First review of Off-Roll / Intern work | no | own team (any Developer if the person has no team) | no | no | no |
| Final review | yes | no | no | no | no |
| Read another person's workspace | yes (read-only) | own team (read-only) | no | no | no |

Review flow: Off-Roll / Intern → Developer → Admin. On-Roll / Developer → Admin.

## Time tracking
The browser sends a heartbeat every 15 s saying only `active`, `away` (tab hidden or not focused)
or `idle` (no input for 5 minutes). The server measures the time itself, credits at most 45 s per
gap, keeps one session per user and accepts reports from one tab only.

## Offline Monaco
The editor engine is loaded from the jsDelivr CDN on first use. To self-host it, run
`npm install monaco-editor` and call `loader.config({ monaco })` in
`src/pages/workspace/monacoSetup.js` (building that bundle needs about 4 GB of RAM).

## Not built yet
See the phase list in STATUS.md.


## Two servers in one workspace (Build 34.6)

The terminal tabs are shells in **one** container, so an API and a dev server can share it. A tab keeps running
only while it is open - closing the tab (or **Close terminal**) ends the program in it.

Simplest for a full-stack project: run the API in the background of the same tab and leave the client in the
foreground, so there is only one thing to keep open:

```
cd /workspace/server && nohup npm start > /tmp/api.log 2>&1 & echo $! > /tmp/api.pid
cd /workspace/client && npm run dev -- --host 0.0.0.0
```

- API log: `tail -f /tmp/api.log`
- stop the API later: `kill $(cat /tmp/api.pid)`
- client: `Ctrl+C` as usual
- Preview tab -> **Terminal server** -> port **5173** (the React page; 3000 is the JSON API)

Without `--host 0.0.0.0` Vite listens on localhost inside the container only and the Preview tab cannot reach it.
Switching terminal tabs moves the keyboard to the tab you clicked (before 34.6 you had to click inside the black
area first, otherwise typing seemed to do nothing).

Why the second/third tab used to look dead (Build 34.8, root cause): React calls mount effects twice in
development, so the terminal opened a socket, the first mount's socket was closed by its cleanup, and that late
close emptied the "current socket" although the second socket was already connected and printing. Every key then
went nowhere - the prompt was on screen and the status said connected. Each socket's handlers now check that they
still belong to the current connection. On top of that, a terminal that loses its connection before the shell
answers retries twice by itself, and `WORKCODE_WS` lets the browser talk to the backend directly instead of through
the dev server's WebSocket proxy (Docker sets it; the proxy drops upgrades now and then).

The status next to the terminal button tells the truth about the shell, not just about the socket: `starting…` while
connecting, `connected, waiting for the shell…` when the socket is up but nothing has come back yet, `connected`
once the shell has printed something. If a connection dies the terminal says why - `[the terminal service did not
answer (code 1006). Press New terminal to try again]` when nothing ever arrived, `[connection closed (code …)]`
when the shell had been working. A terminal container left over from an earlier backend start (a rebuild, a
restart) cannot be reached by the new process, so WORKCODE removes those containers at start-up instead of leaving
them running.

## Running code (Docker)

1. Install Docker Desktop, start it, keep it in Linux containers mode.
2. Restart the backend. Sign in as admin → **Languages** → press **Install** for the languages you need (or `docker pull python:3.12-alpine` etc.).
3. In the coding workspace open a file and press **▶ Run**.

Programs run in a container with no internet, limited memory/CPU/time, and are deleted afterwards. If Docker is not running, Run shows the reason and nothing is executed.

## Automatic work timer and Chrome extension (build 15)
After updating, run `alembic upgrade head` in `backend` once (migration 0003). The timer starts by itself and pauses after
5 minutes without input or when you leave WORKCODE. To keep it running on approved websites (Google Meet, ChatGPT, others the
admin adds under Monitoring), install the extension from the `extension` folder. Full rules, API and permissions: `TIMER.md`.


## Build 16

Task assignment, On-Roll review, Admin final approval and version control: see `TASKS.md`. After updating run `alembic upgrade head` in `backend`. Demo logins are now `admin`, `reviewer` (On-Roll team lead), `onroll`, `offroll`, `intern` `@workcode.local`.


## AI coding assistant (build 17)

See `AI.md`. Short version: set `AI_KEY_SECRET` in `backend/.env`, run `pip install -r requirements.txt` and `alembic upgrade head`, then as Admin open **AI assistant** and add a provider with your API key. In the workspace press **✦ AI** (Ctrl+I).
