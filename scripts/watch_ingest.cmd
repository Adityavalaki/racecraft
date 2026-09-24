@echo off
rem Keep the lake up to date by itself. Registered with Task Scheduler to run at
rem logon; see the README. Ingest writes its own log under data/logs, and this
rem file catches anything that happens before logging starts (a broken venv, a
rem missing drive) which would otherwise vanish with the console window.
cd /d "%~dp0.."
if not exist "data\logs" mkdir "data\logs"
".venv\Scripts\racecraft-ingest.exe" --season 2026 --watch --every 15 >> "data\logs\watch.out" 2>&1
