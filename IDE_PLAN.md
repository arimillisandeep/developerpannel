# WORKCODE IDE – plan and honest status

The IDE lives inside the existing coding workspace (`/workspace/:taskId`). Auth, roles, timer, review flow and existing APIs are unchanged.

## Phase A – done and tested here (build 13)

| Area | What works | How it was tested |
|---|---|---|
| Layout | Top bar, activity bar, explorer, editor tabs + breadcrumbs, bottom panel (Terminal, Output, Problems, Preview, Activity log), status bar; sidebar and bottom panel resize by dragging; dark / light theme; full screen | frontend tests |
| Explorer | Nested folders, create file/folder, rename, move (also drag and drop), duplicate file/folder, delete file/folder (soft, versions kept), upload (button or drop files on a folder), download file, download project zip, filter | backend + frontend tests |
| Search | Go to file (Ctrl+P), find in all files (Ctrl+Shift+F) with jump to line | frontend tests |
| Commands | Command palette (Ctrl+Shift+P), Ctrl+S, Ctrl+B, Ctrl+`, F11 | frontend tests |
| Storage | Files in the database per user/task, autosave, version history + restore, quota: 2000 files / 50 MB per workspace (`MAX_FILES_PER_WORKSPACE`, `MAX_WORKSPACE_BYTES`) | backend tests (60 files, quota) |
| Templates | 16 project templates. 11 were really installed/built/run with `scripts/verify_templates.py`: HTML, React, Vue, Node, Express, Python, Flask, FastAPI, Django, Java, React+Express. 5 are NOT test-run (no toolchain here): Spring Boot, C#, ASP.NET Core, PHP, Flutter – the wizard says so | script output + tests |
| Preview | HTML/CSS/JS live preview from project files (relative paths, sub-folders), updates while typing, console.log and JS errors shown in a Console pane | frontend tests |
| Problems | Editor diagnostics (JS/TS/JSON/CSS/HTML) listed; click jumps to the line | manual code path only |

## Written but NOT verified (needs Docker on the server)

- Run button for 39 languages and the line-based terminal (`app/services/runner.py`). Containers have no internet, so no `npm install` / `pip install`, no dev servers.

## Not built yet – needs the Phase B infrastructure

Phase B is one persistent Docker "dev container" per workspace (project files on a volume, internet access limited to package registries, CPU/RAM/disk limits). Everything below depends on it:

1. Real PTY terminal (xterm.js, multiple tabs, resize, Ctrl+C) – acceptance tests 4, 10, 18, 21
2. Package installation (npm/yarn/pnpm, pip, Maven/Gradle, NuGet, Pub, Composer, Cargo)
3. Dev servers + secure reverse-proxy preview (React/Vue/Angular/Next, Express, FastAPI, …) – tests 5–8
4. API tester (requests sent only to the project's own container, to avoid SSRF)
5. Project databases (PostgreSQL/MySQL/MongoDB/Redis side containers, SQLite file) + query UI – tests 14–15
6. Git panel (git inside the container) – test 17
7. Test runner panel (Jest/Vitest/Pytest/JUnit/…) 
8. Language servers (IntelliSense beyond Monaco's built-in JS/TS/JSON/CSS/HTML) and debuggers (DAP) – largest item
9. .NET, Flutter/Android images (several GB each; Android emulators need a Linux host with KVM) – tests 12–13
10. Admin: runtime availability, resource limits, execution logs, health
11. Practice projects not tied to a task (needs a DB migration: `workspaces.task_id` nullable)

## Acceptance tests from the prompt

| # | Test | Status |
|---|---|---|
| 1 | New HTML project and run it | ✅ template + preview (frontend/back tests) |
| 2 | 50+ HTML/CSS/JS files | ✅ tested with 60 files |
| 3 | Create a React application | ✅ files (template built with npm here) |
| 4–8 | Install packages, run React, see it in WORKCODE, Node backend, front+back | ❌ Phase B |
| 9 | Create and execute Python | ⚠ Run exists, unverified (Docker) |
| 10 | Install Python dependencies | ❌ Phase B |
| 11 | Compile and run Java | ⚠ Run exists, unverified (Docker) |
| 12–13 | .NET, Flutter | ❌ Phase B + big images |
| 14–15 | Project database, SQL queries | ⚠ SQL file run (SQLite/PostgreSQL) unverified; DB explorer ❌ |
| 16–17 | API tests, Git | ❌ Phase B |
| 18 | Multiple terminals | ❌ (one line-based terminal today) |
| 19 | Persistence after logout/login | ✅ files are in the database (tested) |
| 20 | No unauthorised access | ✅ backend tests (403 for other users on every new endpoint) |
| 21 | Processes stop when terminated | ⚠ kill-on-stop/timeout tested with a fake Docker only |
| 22 | All logs/outputs inside WORKCODE | ✅ for preview/save/run output; ❌ for dev servers |
