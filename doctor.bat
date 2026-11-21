@echo off
setlocal
rem What does this PC have, and what should be started? Read-only: nothing is installed or changed here.
echo WORKCODE - environment check            (folder: %~dp0)
echo ---------------------------------------------------------
echo.
echo [0] Is this the project folder?
if exist "%~dp0docker-compose.yml" goto root_ok
echo     docker-compose.yml is NOT here, so "docker compose" cannot work in this folder.
for /d %%d in ("%~dp0*") do if exist "%%d\docker-compose.yml" echo     the project itself is in: %%d
echo     the zip unpacks into one folder named workcode - go in there first:
echo         cd /d "%~dp0workcode"
echo     (then run this file again:  doctor.bat  )
goto after_root
:root_ok
echo     OK - docker-compose.yml, backend and frontend are in this folder.
:after_root
echo.
echo [1] Python  (venv mode needs it, Docker mode does not)
python -c "import sys;print('    usable: python', sys.version.split()[0])" 2>nul
if errorlevel 1 echo     not usable - Windows has the Microsoft Store placeholder. winget install -e --id Python.Python.3.12
py -3 -c "import sys;print('    usable: py -3 =', sys.version.split()[0])" 2>nul
if errorlevel 1 echo     the py launcher is not there either
echo.
echo [2] Node.js  (only for the website in venv mode)
node --version 2>nul || echo     node: not found
npm --version 2>nul || echo     npm: not found - winget install -e --id OpenJS.NodeJS.LTS
echo.
echo [3] Docker Desktop  (this mode needs no Python and no Node)
docker compose version 2>nul || echo     docker compose: not usable - install Docker Desktop and start it
echo.
echo [4] PostgreSQL (venv mode and docker-compose.localdb.yml use the one on this PC; plain Docker uses its own container on 5434)
set "P432="
set "P434="
for /f "delims=" %%a in ('netstat -ano ^| findstr /c:"LISTENING" ^| findstr /c:":5432 "') do set "P432=1"
for /f "delims=" %%a in ('netstat -ano ^| findstr /c:"LISTENING" ^| findstr /c:":5434 "') do set "P434=1"
if defined P432 (echo     port 5432: open  - a PostgreSQL installed on this PC) else (echo     port 5432: closed)
if defined P434 (echo     port 5434: open  - the WORKCODE PostgreSQL container) else (echo     port 5434: closed)
if not defined P432 if not defined P434 echo     neither is up: start the Windows service postgresql-x64-... or use plain Docker mode
echo.
echo [5] Ports WORKCODE wants for itself (8000 = API, 5173 = website)
set "P8000="
set "P5173="
for /f "delims=" %%a in ('netstat -ano ^| findstr /c:"LISTENING" ^| findstr /c:":8000 "') do set "P8000=1"
for /f "delims=" %%a in ('netstat -ano ^| findstr /c:"LISTENING" ^| findstr /c:":5173 "') do set "P5173=1"
if defined P8000 (echo     8000: in use - something is already running) else (echo     8000: free)
if defined P5173 (echo     5173: in use - something is already running) else (echo     5173: free)
echo.
echo Next step, pick one:
echo     with your own PostgreSQL :  cd /d "%~dp0" ^&^& copy .env.example .env  ^&^& docker compose -f docker-compose.yml -f docker-compose.localdb.yml up -d --build
echo     with Docker's database   :  cd /d "%~dp0" ^&^& docker compose up -d --build
echo     without Docker           :  cd /d "%~dp0" ^&^& setup.bat  (then start-backend.bat + start-frontend.bat)
pause
