@echo off
setlocal
rem Starts the WORKCODE API on http://127.0.0.1:8000 (keep this window open).
cd /d "%~dp0backend"
if not exist ".venv\Scripts\python.exe" goto :novenv
.venv\Scripts\python.exe -m alembic upgrade head || goto :error
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
exit /b 0

:novenv
echo There is no backend\.venv yet, so this window has nothing to start.
echo Run setup.bat once first (it creates that environment), or use Docker Desktop instead of both .bat files:
echo     cd /d "%~dp0" ^&^& docker compose up -d --build
pause
exit /b 1

:error
echo.
echo The API did not start. Most often backend\.env points at a PostgreSQL that is not running or has a
echo wrong password - open backend\.env and check DATABASE_URL, or run doctor.bat to see what is missing.
pause
exit /b 1
