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

REM Port 8080 passt zum Jetson-config.json (backend.url=...:8080).
REM Die alte SETUP-SURFACE.md erwaehnt Port 9090, aber die aktuelle
REM Produktions-Konfig nutzt 8080 — dort lauscht auch der bisherige
REM Surface-Prozess.

REM WICHTIG: --reload-exclude fuer data/ und config.json — sonst triggert
REM jeder save_patient()-Call einen Reload, was zu File-Locks auf
REM Windows fuehrt (WinError 32 beim naechsten Boot). Auch die
REM backend/config.json soll nicht reloaden, weil sie sich bei
REM Operator-Registrierung aendert und mitten im Flow kein Restart
REM passieren darf.

cd /d "%~dp0"
python -m uvicorn app:app ^
    --host 0.0.0.0 ^
    --port 8080 ^
    --reload ^
    --reload-dir . ^
    --reload-dir ..\shared ^
    --reload-dir ..\templates ^
    --reload-include "*.py" ^
    --reload-include "*.html" ^
    --reload-exclude "data/*" ^
    --reload-exclude "data/**/*" ^
    --reload-exclude "config.json"
