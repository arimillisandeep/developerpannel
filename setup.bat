@echo off
setlocal
rem One-time setup on Windows: Python packages, PostgreSQL database, tables, accounts, frontend packages.
rem You do NOT need this at all when you run WORKCODE with Docker Desktop:
rem     cd /d "%~dp0" && docker compose up -d --build
cd /d "%~dp0backend"

rem 1. find a real Python. Windows answers "Python was not found" for the Microsoft Store placeholder,
rem    so this runs code instead of trusting that a "python" command exists on the PATH.
set "PY="
python -c "print(1)" >nul 2>nul && set "PY=python"
if not defined PY ( py -3 -c "print(1)" >nul 2>nul && set "PY=py -3" )
if defined PY %PY% --version
if not defined PY goto :nopy

rem 2. the venv, the packages, the database and the first accounts (setup_local.py asks 5 short questions)
if not exist .venv ( %PY% -m venv .venv || goto :error )
.venv\Scripts\python.exe -m pip install -r requirements.txt || goto :error
.venv\Scripts\python.exe setup_local.py || goto :error

rem 3. the website packages
cd /d "%~dp0frontend"
npm --version >nul 2>nul
if errorlevel 1 goto :nonode
call npm install || goto :error

echo.
echo Setup finished. Now run start-backend.bat in one window and start-frontend.bat in another.
echo The website is http://localhost:5173 (the API on http://127.0.0.1:8000 is only its backend).
pause
exit /b 0

:nopy
echo.
echo Python 3.11 or newer was not found on this PC: Windows only has the Microsoft Store placeholder for it.
echo Install Python:   winget install -e --id Python.Python.3.12
echo Then CLOSE this window and open a NEW terminal, because a fresh PATH is only seen by new windows,
echo and run setup.bat again. Or skip Python and Node completely with Docker Desktop:
echo     cd /d "%~dp0" ^&^& docker compose up -d --build
pause
exit /b 1

:nonode
echo.
echo Node.js / npm was not found, so this script cannot install the website packages.
echo Install Node:     winget install -e --id OpenJS.NodeJS.LTS
echo Then open a NEW terminal and run:  cd /d "%~dp0frontend" ^&^& npm install
echo The backend above is already set up: start-backend.bat works without Node.
echo (Docker mode needs neither:  cd /d "%~dp0" ^&^& docker compose up -d --build )
pause
exit /b 1

:error
echo.
echo Setup stopped because of the error above. doctor.bat in this folder shows what is missing on this PC.
pause
exit /b 1
