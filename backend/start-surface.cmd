@echo off
REM SAFIR Surface-Backend Starter mit Auto-Reload
REM
REM uvicorn --reload aktiviert einen File-Watcher der Python-Dateien auf
REM Aenderungen ueberwacht und das Backend automatisch neu startet (~1s
REM Downtime, WebSocket-Clients reconnecten automatisch).
REM
REM Nutzen:
REM   - Kein manuelles Neustarten nach git pull noetig
REM   - Code-Fixes aus dem Jetson-Repo werden nach sync automatisch aktiv
REM   - Fuer Demo-Betrieb ideal: geaenderte Dateien -> ~1s spaeter live
REM
REM --reload-dir schraenkt den Watcher auf das backend/-Verzeichnis ein
REM damit nicht jede kleine Aenderung im Gesamtrepo (z.B. docs/) einen
REM Reload ausloest.
REM
REM Mit Ctrl+C stoppen.

cd /d "%~dp0"
python -m uvicorn app:app ^
    --host 0.0.0.0 ^
    --port 9090 ^
    --reload ^
    --reload-dir . ^
    --reload-dir ..\shared ^
    --reload-dir ..\templates ^
    --reload-include "*.py" ^
    --reload-include "*.html" ^
    --reload-include "*.json"
