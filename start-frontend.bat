@echo off
setlocal
rem Starts the WORKCODE website on http://localhost:5173 (keep this window open).
cd /d "%~dp0frontend"
npm --version >nul 2>nul
if errorlevel 1 goto :nonode
if not exist node_modules ( call npm install || goto :error )
call npm run dev
pause
exit /b 0

:nonode
echo npm was not found, so the website cannot be started this way.
echo Install Node.js:  winget install -e --id OpenJS.NodeJS.LTS
echo then open a NEW terminal and run this file again - or use Docker Desktop, which needs no Node at all:
echo     cd /d "%~dp0" ^&^& docker compose up -d --build
pause
exit /b 1

:error
echo.
echo npm install failed. A company proxy or a blocked npm registry usually does that.
pause
exit /b 1
