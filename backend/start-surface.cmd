@echo off
REM SAFIR Surface-Backend Starter mit Auto-Reload
REM
REM uvicorn --reload aktiviert einen File-Watcher der Python-Dateien auf
REM Aenderungen ueberwacht und das Backend automatisch neu startet.
REM
REM WICHTIG: Keine --reload-include/--reload-exclude mit Globs — die
REM werden vom MSYS2/Bash in Git-Bash noch vor cmd.exe expandiert was
REM uvicorn dann als extra-Args bekommt. Stattdessen: Nur --reload-dir
REM auf spezifische Unterverzeichnisse, data/ wird NICHT gewatched weil
REM nicht in der Dir-Liste.

cd /d "%~dp0"
python -m uvicorn app:app --host 0.0.0.0 --port 8080 --reload --reload-dir . --reload-dir ..\shared --reload-dir ..\templates
