@echo off
rem Keep the lake up to date by itself. Started at logon from the Startup folder;
rem see the README.
rem
rem Runs under pythonw, which has no console window. The first version ran in a
rem minimised console, and closing that window - the obvious thing to do with a
rem stray black box - killed the watcher twice on the Baku weekend, once midway
rem through fetching a session. With no window there is nothing to close; stop it
rem from Task Manager (pythonw.exe) if you need to. Everything it does is logged
rem to data\logs\ingest-*.log.
cd /d "%~dp0.."
start "" ".venv\Scripts\pythonw.exe" -m racecraft.ingest.cli --season 2026 --watch --every 15
