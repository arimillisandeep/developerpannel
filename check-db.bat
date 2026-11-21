@echo off
rem Double-click this to check whether WORKCODE can reach your PostgreSQL. Read-only.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0check-db.ps1"
echo.
pause
