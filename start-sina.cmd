@echo off
REM SAFIR SINA-Rettungsstation Backend Starter (Windows 11, ohne LLM)
REM
REM Nutzt das venv unter .venv\ und uvicorn ohne --reload.
REM (--reload kollidiert mit save_patient() in backend/data\ und killt
REM den Worker mitten im Flow — siehe SESSION-HANDOVER.md.)
REM
REM Doppelklick startet das Backend in einem Konsolenfenster.
REM stdout + stderr werden zusaetzlich in logs\backend.log geschrieben,
REM damit Crashes und Stack-Traces nachvollziehbar sind, auch wenn das
REM Fenster zu schnell zugeht.
REM
REM Stoppen: Ctrl+C im Fenster, Fenster schliessen, oder
REM   stop-safir.bat auf dem Desktop.

setlocal

set "ROOT=%~dp0"
if not exist "%ROOT%logs" mkdir "%ROOT%logs"

set "LOGFILE=%ROOT%logs\backend.log"
echo. >> "%LOGFILE%"
echo ==== %DATE% %TIME%  start-sina.cmd ==== >> "%LOGFILE%"

cd /d "%ROOT%backend"
"%ROOT%.venv\Scripts\python.exe" -m uvicorn app:app --host 0.0.0.0 --port 8080 >> "%LOGFILE%" 2>&1
