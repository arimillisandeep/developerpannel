# WORKCODE – run it on your PC with PostgreSQL (Windows)

Tested on 13 Nov 2026 with a real PostgreSQL 17 server (details at the end).

## What you need

| Software | Version | Check in a terminal |
|---|---|---|
| Python | 3.11 or newer | `python --version` |
| Node.js | 20 or newer | `node --version` |
| PostgreSQL | 13 or newer, running | you need the port (5432 or 5433) and the `postgres` password |
| Docker Desktop | optional | only for the ▶ Run button and the terminal inside the workspace |

## Easy way (3 double-clicks)

1. Unzip the zip, then open the **`workcode` folder that is inside it** - the one that contains
   `docker-compose.yml`, `backend` and `frontend`. Unzipping into `Downloads\workcode-build34-9` gives
   `Downloads\workcode-build34-9\workcode\docker-compose.yml`: the outer folder is only a wrapper, and
   `docker compose` in it says *"compose file ... is invalid: ... The system cannot find the file specified"*.
   To be sure, the project folder is the one where this prints a path:
   ```
   Get-ChildItem -Recurse -Depth 2 -Filter docker-compose.yml | Select-Object -ExpandProperty FullName
   ```
   and this enters it:
   ```
   Set-Location (Get-ChildItem -Recurse -Depth 2 -Filter docker-compose.yml | Select-Object -First 1).DirectoryName
   ```
   `doctor.bat` says the same thing at the top: *"docker-compose.yml is NOT here ... the project itself is in: ..."*.
2. Double-click **`setup.bat`**. It installs the Python packages, then asks:

   | Question | What to type |
   |---|---|
   | PostgreSQL host | Enter (127.0.0.1) |
   | PostgreSQL port | `5433` (Enter) or `5432`, whichever your PostgreSQL uses |
   | PostgreSQL user | Enter (`postgres`) |
   | Password | your PostgreSQL password (nothing is shown while you type) |
   | Database name | Enter (`workcode_v2`). It is created if missing. An existing database is never dropped. |
   | Accounts | `d` = demo accounts for all roles, `a` = only your own admin |

   It then writes `backend\.env` with new random secrets, creates the tables (43) and installs the frontend packages.
3. Double-click **`start-backend.bat`** (keep the window open).
4. Double-click **`start-frontend.bat`** (keep the window open).
5. Open **http://localhost:5173**

Demo logins (if you chose `d`), password `Workcode@123` for all:
`admin@workcode.local`, `reviewer@workcode.local`, `onroll@workcode.local`, `offroll@workcode.local`, `intern@workcode.local`.
Change these passwords before real use.

## Manual way (PowerShell)

```
cd workcode\backend
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python setup_local.py                 # database + .env + tables + accounts
python -m uvicorn app.main:app --port 8000      # terminal 1, keep open
```

```
cd workcode\frontend
npm install
npm run dev                           # terminal 2, keep open -> http://localhost:5173
```

Without the script: `createdb -p 5433 -U postgres workcode_v2`, copy `.env.example` to `.env`, set `DATABASE_URL`
and a long random `JWT_SECRET`, then `alembic upgrade head` and `python -m app.demo_seed`
(or `python -m app.seed you@company.com "Your Name"`).

## Check that it works

| Check | Expected |
|---|---|
| http://127.0.0.1:8000/api/health | `{"status":"ok"}` |
| http://127.0.0.1:8000/docs | list of all APIs |
| Backend window | no line that starts with `JWT_SECRET is the built-in default` |
| Sign in as admin → People | 5 people (demo) |
| pgAdmin → database `workcode_v2` → Tables | 43 tables, `alembic_version` = `0010` |

Run the automatic tests (optional):

```
cd backend
python -m pytest                      # 168 tests on a throw-away SQLite file
```

To run the same 168 tests on PostgreSQL, create an **empty** database with `test` in its name (the tests delete all
tables in it), then in PowerShell:

```
createdb -p 5433 -U postgres workcode_test
$env:TEST_DATABASE_URL="postgresql+psycopg2://postgres:YOUR_PASSWORD@127.0.0.1:5433/workcode_test"
python -m pytest
```

## Open the folder in VS Code (Build 34.1)
VS Code is only an editor and a terminal here — nothing has to be installed in it. `File → Open Folder…` → the
`workcode` folder (the one that contains `docker-compose.yml`, `backend` and `frontend`), then `` Ctrl+` `` for a
terminal inside VS Code and use exactly the commands from the sections above:

- **Docker mode** (needs Docker Desktop running): `docker compose up -d --build`, open http://localhost:5173 .
  Stop with `docker compose down`. The code is mounted into the container, so after copying new files over the
  folder run `docker compose up -d --build` again (a `docker compose restart` is enough after a `.env` change).
- **Python/venv mode**: `setup.bat` once, then `start-backend.bat` and `start-frontend.bat` (double-click them, or
  run them from this terminal). Two windows stay open: the API on http://127.0.0.1:8000 and the site on
  http://localhost:5173.
- Tests from that same terminal: `cd backend` + `python -m pytest -q` (venv mode: activate `.venv` first),
  `cd frontend` + `npx vitest run`, `cd extension` + `npm test`.
- In the Source Control panel nothing needs to be committed to run the app; the `.venv`, `node_modules`,
  `storage` and `*.db` folders are already in `.gitignore`.

Useful settings: `Files: Exclude` hides `node_modules` and `.venv`. If `python` opens the Microsoft Store instead of
running (Windows does that when Python is not on the PATH), use the venv's own interpreter — from the `backend` folder:
`& .\.venv\Scripts\python.exe -m pytest -q`.

**Nothing is installed by hand in Docker mode** — that is the point of it: `docker compose up -d --build` needs only
Docker Desktop, while `setup.bat` needs Python 3.11+ *and* Node.js on this PC. `doctor.bat` (double-click it, or run
it in this terminal) prints what this machine has: a usable `python` / `py -3` (it runs code, so the Store placeholder
is not mistaken for Python), `node` and `npm`, `docker compose`, whether PostgreSQL answers on 5432 or 5434, and
whether 8000 / 5173 are free. It installs and changes nothing.

## Look inside the database from VS Code (Build 34.9)

The app connects to PostgreSQL by itself; nothing has to be "connected" for WORKCODE to work. This section is only
for looking at the tables while the app is running. The values depend on **how you started WORKCODE** - the ports
differ on purpose so two databases never fight over one port:

| How it runs | Server | Port | User | Password | Database |
|---|---|---|---|---|---|
| Docker, `docker compose up -d --build` (the PostgreSQL container) | `127.0.0.1` | `5434` | `postgres` | `workcode` | `workcode_v2` |
| Docker + **your own** PostgreSQL (`-f docker-compose.localdb.yml`) | `127.0.0.1` | the `LOCAL_PGPORT` in `.env` (usually `5432`) | `LOCAL_PGUSER` (`postgres`) | `LOCAL_PGPASSWORD` | `LOCAL_PGDATABASE` (`workcode_v2`) |
| venv mode (`setup.bat`, no Docker) | `127.0.0.1` | what you typed in `setup.bat` (usually `5433`) | `postgres` | the password you typed | `workcode_v2` |

`127.0.0.1` is right even for Docker mode: only the *backend container* calls the database `db`, while a program on
Windows (VS Code, pgAdmin) reaches it through the forwarded port on the PC.

**Is PostgreSQL really usable by WORKCODE?** (Build 34.12) Double-click **`check-db.bat`** in the project folder,
or run `powershell -NoProfile -ExecutionPolicy Bypass -File .\check-db.ps1`. It reads `.env` itself and answers three
separate questions, because they fail for different reasons: is a PostgreSQL running and on which port (plus the Windows
service state), do the user name and password in `.env` really work (through `psql`), and - the one that decides it - can
a **Docker container** reach it. It changes nothing (one throw-away `postgres` container is started and removed again).
Three example endings, none of them typed by you:

```
  CONTAINER OK - reached your PostgreSQL as postgres
----------------------------------------------------------
Everything the app needs is there. Next step:
  docker compose -f docker-compose.yml -f docker-compose.localdb.yml up -d --build
```
```
  CONTAINER FAILED: psql: error: connection to server at "host.docker.internal" (172.17.0.1), port 5432 failed: Connection refused
  hint: 'no pg_hba.conf entry' means your PostgreSQL accepts only 127.0.0.1. Either add
        host all all 0.0.0.0/0 scram-sha-256  to pg_hba.conf and set listen_addresses = '*'
        in postgresql.conf, restart the service, or use Docker's own database
```
```
  password        NOT set - password tests below are skipped
Next step: copy .env.example to .env, put your PostgreSQL password in it, run this file again.
```

**Which ports actually answer** - paste in the VS Code terminal, it prints only the open ones:

```
'5432','5433','5434' | Where-Object { Test-NetConnection 127.0.0.1 -Port $_ -InformationLevel Quiet }
```

**What the app itself uses** (venv mode) - prints the line from `backend/.env` with the password hidden:

```
$l = (Select-String -Path backend\.env -Pattern '^DATABASE_URL=').Line; $l -replace ':[^:@/]+@', ':***@'
```
Do not type this - it shows for example `DATABASE_URL=postgresql+psycopg2://postgres:***@127.0.0.1:5433/workcode_v2`.

### Option 1 - pgAdmin 4 (installed with PostgreSQL, nothing to add)

`pgAdmin → right-click Servers → Register → Server…` → **Name** `WORKCODE` → **Connection** tab: host `127.0.0.1`,
port from the table above, user `postgres`, password from the table above, tick *Save password* → **Save**. Then
`Databases → workcode_v2 → Schemas → public → Tables`.

### Option 2 - PostgreSQL extension inside VS Code

1. `Ctrl+Shift+X` → search `postgresql` → install **PostgreSQL** by **Microsoft** (id `ms-ossdata.vscode-pgsql`).
2. Click the PostgreSQL icon in the Activity Bar → **Connections** → `+` **Add New Connection** (or the Command
   Palette, `Ctrl+Shift+P` → `PGSQL: Add New Connection`).
3. Leave the tab on **Parameters** and fill in **Server name** `127.0.0.1`, **Authentication Type** `Password`,
   **User name** `postgres`, **Password** (from the table), **Database name** `workcode_v2`, **Connection Name**
   `WORKCODE local`. The **Port** field is not on the first screen: open **Advanced Connection Settings** and set it
   (default `5432` is wrong for Docker mode - it must be `5434`).
4. Or use the **Connection String** tab and paste one line:
   ```
   postgresql://postgres:workcode@127.0.0.1:5434/workcode_v2
   ```

`PostgreSQL Client` by Weijan Chen (`cweijan.vscode-postgresql-client2`) works too: `Ctrl+Alt+D` → **Create
Connection** → same host / port / user / password / database values.

### Check that you are in the right database

Right-click the connection → **New Query** and run:

```
select count(*) from information_schema.tables where table_schema = 'public';
select version_num from alembic_version;
```
Do not type this - the answers for a healthy install are `43` and `0010`.

Two databases on one PC are normal here: `workcode` (or `workcode_v2` from an older install) on `5432`/`5433` holds
data from before, `workcode_v2` on `5434` is the one the Docker app writes to. If the table count is `0`, you are
connected to an empty database - check the port, not the password.

| What VS Code shows | Reason | Fix |
|---|---|---|
| `password authentication failed for user "postgres"` | the password belongs to another PostgreSQL on this PC | use the password from the table for **that** port; for Docker mode it is `workcode` |
| `connection refused` / timeout | the port is wrong or the database is not running | run the port check above; Docker mode needs `docker compose up -d` first |
| `database "workcode_v2" does not exist` | you are on the wrong server (the other PostgreSQL) | Docker mode: port `5434`. venv mode: the database is created by `setup.bat`; run it again |
| `no pg_hba.conf entry ... SSL off` | the server demands SSL | in the connection's **Advanced Connection Settings → SSL**, set mode `require` |

The database schema is never edited by hand: migrations do it (`alembic upgrade head`, which the app runs when it
starts). Editing rows directly is fine for a look, but a column that is dropped by hand breaks the next start.

## Every page says "Request failed (500)" (Build 34.11)

That text is not a WORKCODE message. It means the browser got an answer that came from the wrong place: the
backend did not answer at all (the website is only the proxy in front of it), or the backend crashed. Nothing you
typed is wrong - and it is not about the page you were on. Open this address in the same browser, on the same port:

```
http://localhost:5173/api/health/db
```
Do not type this - the four possible answers and what each one means:

| The address shows | Meaning | What to do |
|---|---|---|
| `{"status":"ok","users":7,"schema":"0010"}` | backend and database are both fine | the fault is in the request itself: `docker compose logs backend --tail 80` |
| `{"detail":"Database problem: ..."}` (503) | the backend runs, the database does not: the text is the driver's own reason | fix what it names - see the rows below |
| `Request failed (500)` again, or `Error occurred while trying to proxy` | the backend container is not running at all | `docker compose ps` then `docker compose logs backend --tail 80` |
| `Cannot reach the server` | nothing is listening on 5173 | start it again |

What the database reason means:

| Reason in the answer | Fix |
|---|---|
| `password authentication failed for user "postgres"` | the password in `.env` (the one next to `docker-compose.yml`) is not the password of that PostgreSQL |
| `no pg_hba.conf entry for host "172.18.0.x"` | your PostgreSQL accepts only `127.0.0.1`, not the Docker containers. Either add `host all all 0.0.0.0/0 scram-sha-256` to `C:\Program Files\PostgreSQL\<version>\data\pg_hba.conf`, set `listen_addresses = '*'` in `postgresql.conf`, restart the Windows service, or simply use Docker's own database with plain `docker compose up -d --build` |
| `Connection refused` / timeout on `host.docker.internal:5432` | the service is stopped, or it listens only inside Windows. Start `postgresql-x64-...`; if that is not enough, use plain Docker mode |
| `relation "users" does not exist` | connected to the right server but the wrong/empty database: `LOCAL_PGDATABASE` must be `workcode_v2`, and the backend creates its tables on the first start |

To see the backend's own words, from the project folder (`workcode`):

```
docker compose -f docker-compose.yml -f docker-compose.localdb.yml ps
docker compose -f docker-compose.yml -f docker-compose.localdb.yml logs backend --tail 80
```
Drop the `-f ...localdb.yml` part when you started it with plain `docker compose up -d --build`. A healthy backend
log ends with `Application startup complete.`; a container that keeps restarting prints the reason and stops.

## If something goes wrong

| Message | Reason | Fix |
|---|---|---|
| `Cannot connect to PostgreSQL` / `password authentication failed` | wrong password or port | Open pgAdmin, check the port (server → Properties → Connection) and the password; run `setup.bat` again |
| `connection refused` | PostgreSQL service is not running | Windows → Services → `postgresql-x64-…` → Start |
| `Python was not found; run without arguments to install from the Microsoft Store` | no real Python: `python` on Windows is a Store placeholder | `winget install -e --id Python.Python.3.12`, then **open a new terminal** (a fresh PATH is only seen by new windows). `python --version` must print `Python 3.12.x`. Or skip Python entirely and use Docker mode |
| `'npm' is not recognized as an internal or external command` | Node.js is not installed (only needed for the website in venv mode) | `winget install -e --id OpenJS.NodeJS.LTS`, new terminal, run `start-frontend.bat` again. Or use Docker mode, which installs it inside the container |
| `The system cannot find the path specified.` from `start-backend.bat` | `backend\.venv` does not exist yet (the setup never finished) | run `setup.bat` once; if it stops, `doctor.bat` in this folder says what is missing |
| `Setup stopped because of the error above.` | the line just above it is the real reason | `doctor.bat` checks Python, Node, Docker, PostgreSQL and the ports in one go (it changes nothing) |
| `python is not recognized` | Python not on PATH | Reinstall Python with "Add python.exe to PATH" ticked |
| `npm is not recognized` | Node.js missing | Install Node.js 20 LTS |
| `An Application Control policy has blocked this file` on `pip` / `uvicorn` | Windows blocks the small launcher programs | Use `python -m pip …`, `python -m uvicorn …`, `python -m alembic …`, `python -m pytest` instead |
| `Activate.ps1 cannot be loaded` (PowerShell) | script policy | Use `setup.bat`, or run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once |
| `address already in use` on 8000 or 5173 | an old window is still running | Close the old backend / frontend window |
| Login page says "Network Error" or 502 | backend is not running | Start `start-backend.bat` first |
| ▶ Run says "runner is not available" | Docker Desktop is not running | Start Docker Desktop (Linux containers mode) |
| Special characters in the PostgreSQL password | – | `setup_local.py` encodes them for you; if you write `.env` by hand, `@` must be `%40`, `#` → `%23`, space → `%20` |

## Later

- **Update to a newer zip**: copy your `backend\.env` into the new folder, then start `start-backend.bat`
  (it runs `alembic upgrade head` each time, which only adds what is missing).
- **Backup**: `pg_dump -p 5433 -U postgres -Fc workcode_v2 > workcode_backup.dump` is the complete data. Also keep
  `backend\.env` (the secrets; without `AI_KEY_SECRET` the saved AI keys cannot be read).
- **Other PCs in the office**: start the frontend with `npm run dev -- --host` and open `http://YOUR-PC-IP:5173`;
  add that address to `CORS_ORIGINS` in `.env`.
- **AI assistant**: sign in as admin → AI assistant → add your provider and key (keys from the online preview are not in the zip).

## Where the data is stored

Since build 20 **all application data is in PostgreSQL**. The `storage` folder is no longer used for new data.

| Data | PostgreSQL table |
|---|---|
| People, roles, profiles, teams, projects | `users`, `employee_profiles`, `teams`, `team_members`, `projects`, … |
| Tasks, assignments, status history | `tasks`, `task_assignments`, `task_history`, … |
| Code written in the workspace, every saved version | `workspace_files`, `file_versions`, `file_events` |
| Submissions (frozen copy of the project), reviews, comments | `submissions`, `reviews`, `review_comments` |
| Files uploaded to a task (attachments) | `task_attachments.data` |
| Screen recording videos | `recording_chunks` (one row per uploaded piece) |
| Timer, attendance, website reports | `work_sessions`, `attendance`, `activity_logs`, … |
| Chat, meetings, notifications | `chat_messages`, `meetings`, `notifications`, … |
| AI providers (key encrypted), conversations, messages | `ai_providers`, `ai_conversations`, `ai_messages` |
| Audit log | `audit_logs` |

Not in PostgreSQL, on purpose:

| What | Where | Why |
|---|---|---|
| Login token of the signed-in person | that person's browser | a browser must hold its own token; the server stores only the token version |
| Editor layout choices (panel sizes, AI panel open) | that person's browser | per-browser display settings, no company data |
| Secrets (`JWT_SECRET`, `AI_KEY_SECRET`, database password) | `backend\.env` | they are the keys to the database, so they cannot be inside it |
| Login / AI rate-limit counters | server memory | short-lived, reset on restart |
| Temporary copy of a project while ▶ Run executes | temp folder, deleted after the run | Docker needs real files |

**Size note**: screen recordings are large (about 100–300 MB per hour). They now grow the database and the
`pg_dump` backup by the same amount. One recording may be at most 2 GB.

**Older installation**: `alembic upgrade head` (migration 0007) copies existing files from the `storage` folder into
the database and prints how many it copied. The files on disk are not deleted; remove the folder yourself after checking.

## What was tested on PostgreSQL (real server, PostgreSQL 17.11)

| Test | Result |
|---|---|
| `alembic upgrade head` on an empty database, `alembic check` | 43 tables, version 0010, models and tables match |
| Backend pytest on PostgreSQL | 94 of 94 |
| Negative matrix (tokens, roles, outsiders, bad input), 129 endpoints | 1280 of 1280, no 500 error |
| API workflows with rows checked in PostgreSQL | 190 PASS + 1 BLOCKED (Docker); extra task paths 14 of 14 |
| Task and review flow | 35 of 35 |
| AI assistant flow (local test provider) | 54 of 54 |
| Browser (headless Chromium): clicked workflows | 34 of 34 |
| Browser: every menu page for 5 logins | 72 of 72 |
| 80 MB recording uploaded in 4 pieces, downloaded again | byte-identical, 4 rows in `recording_chunks`, 0 files on disk |
| Migration 0007 on a database with files on disk | 3 attachments + 2 recordings copied, byte-identical |
| `setup_local.py`: new database, password with `@ : / # %` and a space, second run, wrong password | all behaved correctly |
| Start with only `backend\.env` + `npm run dev`, sign in, open 4 pages | works, 0 errors |

**Not tested**: the `.bat` files themselves and Windows (the tests ran on Linux), Docker Run and terminal,
the Chrome extension in real Chrome. If a `.bat` file stops, use the "Manual way" above; the commands are the same.

## Run with Docker Desktop (when Windows blocks Python packages)

Use this when `python -c "import pydantic_core"` fails with
`An Application Control policy has blocked this file` (Windows Smart App Control).
Nothing from Python or Node runs on Windows itself in this mode, so the policy does not apply.

1. Start Docker Desktop and wait until it says "Engine running".
2. In the `workcode` folder (the one with `docker-compose.yml`):

   ```
   docker compose up --build
   ```

   The first start downloads images and takes several minutes. It is ready when the log shows
   `Uvicorn running on http://0.0.0.0:8000` and `Local: http://localhost:5173/`.
3. Open http://localhost:5173 and sign in with `admin@workcode.local` / `Workcode@123`.

| What | Where |
|---|---|
| Data | PostgreSQL 17 in a container, Docker volume `workcode_pgdata` (kept between starts) |
| pgAdmin | host `localhost`, port `5434`, user `postgres`, password `workcode`, database `workcode_v2` |
| Secrets | `backend\.env`, written on the first start |
| Stop | `Ctrl+C`, or `docker compose down` (data is kept; `docker compose down -v` deletes the data) |
| After a code change in `frontend` or `requirements.txt` | `docker compose up --build` |

▶ Run and the terminal work in this mode too. The backend starts one throw-away container per run through
Docker Desktop (`/var/run/docker.sock` is mounted into the backend container). Each language needs its image once:
sign in as Admin, open **Languages**, and click download for the languages you use (Python is about 50 MB,
C / C++ about 1.4 GB). Until then Run answers "image is missing".

### The terminal (Build 21)

The Terminal tab is a real interactive terminal (xterm.js, the engine VS Code uses) attached to a shell in a container:

| Works | Notes |
|---|---|
| Typing directly, arrow keys, history, Tab completion, Ctrl+C, Ctrl+L, colours, `vi`, `top` | bash when the image has it, otherwise the image's `sh` |
| Files in both directions | A file the shell creates, changes or deletes shows up in the editor within about 2 seconds, and a file saved in the editor shows up in the shell. When both changed the same file, the editor wins. |
| `npm install`, `pip install` | Needs `TERMINAL_NETWORK: bridge` (set in `docker-compose.yml`). With `none` the terminal has no network. |
| `node_modules`, `.venv`, `.git`, `dist`, `build`, `target` | Stay in the terminal folder only (not in the workspace, not in a submission). They are kept between terminals of the same workspace. |

Not copied to the workspace: binary files, files over 1 MB, file names with characters the workspace does not allow.
After a task is submitted the files are locked: the shell can still run, but its changes no longer reach the workspace.
Limits per terminal: 1.5 GB memory, 1 CPU, 512 processes, no root, 10 minutes without input, 1 hour in total.
The tools are the ones in the chosen language image (the JavaScript terminal has `node` and `npm`, not `python`).
Without Docker mode on Windows (backend started with `python -m uvicorn`) the terminal is not available.

Limits of this mode: it uses its own PostgreSQL, not the one installed on Windows. Mounting the Docker socket gives
the backend control over Docker on this PC, which is fine for a local test but not for a shared server.

## Docker mode with the PostgreSQL installed on this PC (Build 25)

By default Docker mode stores the data in a PostgreSQL 17 container (pgAdmin: `localhost`, port `5434`, password `workcode`).
To store it in the PostgreSQL installed on Windows instead:

1. Create the file `.env` in the `workcode` folder (next to `docker-compose.yml`):
   ```
   LOCAL_PGPASSWORD=your-postgres-password
   LOCAL_PGPORT=5432
   ```
   Optional: `LOCAL_PGUSER` (default `postgres`), `LOCAL_PGDATABASE` (default `workcode_v2`).
2. Start with both compose files:
   ```
   docker compose -f docker-compose.yml -f docker-compose.localdb.yml up --build
   ```
The database and tables are created on the first start; an empty database gets the demo accounts.
`backend/.env` is rewritten for the new database (old one saved as `backend/.env.backup`), the secrets are kept.
To go back to the Docker database start with plain `docker compose up --build`.

**PostgreSQL 18 is verified as well** (Build 34.4): the full suite (156 tests), `setup_local.py` and both Alembic
checks were re-run against a real `postgres:18` server (18.7), and the live behaviour checks - the four timer
cards, the meeting timer, the report CSVs - passed 12/12 on it. 18.6 and 18.7 are the same major line, so nothing
in your install needs changing. The only thing `setup_local.py` refuses is a server below PostgreSQL 14.

## Which .env file, and who writes it (Build 34.2)
| Mode | What you must create | What WORKCODE writes by itself |
|---|---|---|
| Docker Desktop (`docker compose up -d --build`) | **nothing** | `backend/.env`: the database of the container (`db:5432`), `JWT_SECRET` and `AI_KEY_SECRET` freshly random, every other key from `backend/.env.example` |
| venv on Windows (`setup.bat`) | nothing (it asks 5 questions) | the same `backend/.env`, with the PostgreSQL you typed in |
| Docker + your own PostgreSQL (`docker-compose.localdb.yml`) | `.env` next to `docker-compose.yml` with `LOCAL_PGPASSWORD=...` — copy `/.env.example` | `backend/.env` again, built from those values |

- The file the app reads is **`backend/.env`**. A `.env` in the folder with `docker-compose.yml` is only for the
  `${LOCAL_*}` values of `docker-compose.localdb.yml`; in plain Docker mode it is not read at all.
- What was written: `docker compose exec backend cat /app/.env` (Docker) or open `backend\.env` in the editor.
- A `backend/.env` that points to another database is rewritten on the next start (Docker runs the setup with
  `WORKCODE_SETUP_AUTO=1`), the old file is kept as `backend/.env.backup`, and `JWT_SECRET`, `AI_KEY_SECRET` and the
  mail settings are carried over — so people are not signed out and stored AI keys stay readable.
- The keys you are most likely to touch (all of them are documented in `backend/.env.example`): `TIMEZONE`,
  `WORKDAY_TARGET_HOURS`, `RECORDING_RETENTION_DAYS`, `MAX_ADMINS`, and `RECORDING_AWAY_GRACE_SECONDS`
  (`0` = the workspace recording stops the moment the tab is left, `60` = you may be away a minute first).
- `.env` is in `.gitignore` on purpose: it contains secrets, so it is never committed and never shipped in a zip.
  Set something by hand by copying `backend/.env.example` to `backend/.env` — or just let the setup write it and

Two keys that get mixed up most often:

- **`DATABASE_URL=db:5432` is not a setting.** The real key is `DATABASE_URL=postgresql://user:password@host:port/db`
  and `setup_local.py` writes it for you. There is nothing to fill in.
- **A `LOCAL_PG*=...` line typed at a PowerShell prompt is not a config edit.** PowerShell tries to *run*
  `LOCAL_PGPORT=5432` as a command and says `The term 'LOCAL_PGPORT=5432' is not recognized`. Open `.env` in the
  editor (or `notepad .env`), put those lines **in the file**, save it, then run the `up` command.

To check your own PostgreSQL from inside the container before you touch any file (this only *reads*, it changes
nothing), use your **real** password - the `MEEPASS` you may have seen in a message here was a placeholder, and
using it as if it were literal is why the test answered `password authentication failed`:

```
docker compose exec backend python -c "import psycopg2 as p;c=p.connect(host='host.docker.internal',port=5432,user='postgres',password='<your real password>',dbname='postgres');c.autocommit=True;q=c.cursor();q.execute('show server_version');print('CONNECTED', q.fetchone()[0])"
```

  edit the one line you care about afterwards (`notepad backend\.env`).

## E-mail for "Forgot password" (Build 26)

The login page has **Forgot password?**. It mails a reset link to the address stored for that account.
Until e-mail is set up the page answers "Password reset by e-mail is not set up on this server" and sends nothing.

Add the settings to **`backend/.env`** - the file inside `backend`, **not** the `.env` that sits next to
`docker-compose.yml`. That second file is only read for the `LOCAL_PG*` lines of `docker-compose.localdb.yml`; a
`SMTP_HOST` written there is read by nobody and the page keeps saying "not set up".

After saving: Docker -> `docker compose restart backend` (no rebuild needed, `./backend` is mounted into the
container); venv -> close the backend window and run `start-backend.bat` again.

**Way 1 - Gmail with an app password (simplest)**

1. Google account -> Security -> turn on 2-Step Verification.
2. Open https://myaccount.google.com/apppasswords , create an app password named "WORKCODE". Google shows 16 letters.
3. `backend/.env`:
   ```
   APP_URL=http://localhost:5173
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USER=your.address@gmail.com
   SMTP_PASSWORD=the16letterswithoutspaces
   MAIL_FROM=your.address@gmail.com
   ```
   (`MAIL_FROM` empty = `SMTP_USER` is used as the sender, so it can be left out. Google shows the app password
   as four groups of four letters; pasting it **with** the spaces is fine - the space is stripped automatically,
   16 letters are what matters.)

**Way 2 - Gmail API (OAuth)**

1. Google Cloud console -> new project -> enable "Gmail API".
2. OAuth consent screen (External, add your own address as test user) -> Credentials -> OAuth client ID, type "Web application",
   redirect URI `https://developers.google.com/oauthplayground`.
3. https://developers.google.com/oauthplayground -> gear icon -> "Use your own OAuth credentials" -> scope
   `https://www.googleapis.com/auth/gmail.send` -> Authorize -> "Exchange authorization code for tokens" -> copy the refresh token.
4. `backend/.env`:
   ```
   APP_URL=http://localhost:5173
   GMAIL_CLIENT_ID=...
   GMAIL_CLIENT_SECRET=...
   GMAIL_REFRESH_TOKEN=...
   ```
When all three GMAIL_ values are set the Gmail API is used, otherwise SMTP.

**Check the settings without opening the website (Build 34.9)**

`backend/check_mail.py` reads the same `backend/.env` the API reads and prints what it found - never the password,
only how many characters it has. Run it in a VS Code terminal (`Ctrl+`` ` ``) from the `backend` folder:

```
cd backend
python check_mail.py
```
Do not type this - what it prints when nothing is set up yet:
```
backend/.env
  way            nothing - e-mail is OFF
  APP_URL        http://localhost:5173
  MAIL_ASYNC     True  (true = sent in the background; a failure is only in the backend log)

E-mail is OFF. "Forgot password" answers: "Password reset by e-mail is not set up on this server."
Fill in SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD and MAIL_FROM in backend/.env, then restart the backend.
```

Send one real test message to your own inbox:

```
python check_mail.py your.address@gmail.com
```
Do not type this - the two possible endings:
```
SENT. The mail server accepted the message - check the inbox (and the Spam folder).
```
```
NOT SENT: The mail server refused the login. For Gmail use an app password, not the normal password.
```
The line after `NOT SENT:` is the reason the mail server itself gave, so nothing has to be guessed: a wrong app
password, a wrong port, a server that does not offer `SMTP_STARTTLS`, or a rejected recipient address each have
their own sentence. Exit code: `0` sent, `1` e-mail not set up, `2` the server refused.

To check it: open http://localhost:5173/forgot-password , type the address of an existing account and press
**Send reset link**. The page then says a link was sent - if it still says "not set up", the keys are in the wrong
`.env`; if it says sending failed, the reason is in Admin -> Audit log as `password.reset_mail_failed` (a Gmail
"app password" typed with the spaces in it, or an app password made before 2-Step Verification was on, are the
two usual causes).

No e-mail at all is also a working choice: an administrator can set a new password for anybody in
**Admin -> People -> (open the person) -> New password**. The tests are run both with and without a mailbox
configured (Build 34.5), so adding these keys never turns the suite red.

`APP_URL` is the address people open WORKCODE at; the link in the mail starts with it.
A mail that could not be sent is written to the audit log as `password.reset_mail_failed` with the reason (Admin -> Audit log).
