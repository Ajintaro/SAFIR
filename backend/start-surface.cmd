@echo off
REM SAFIR Surface-Backend Starter
REM
REM KEIN --reload! Das State-Problem (uvicorn killt den Worker beim
REM save_patient() weil --reload-dir . auch backend/data/ watched
REM und dort werden JSONs geschrieben. Resultat: state.sessions und
REM alle anderen In-Memory-Strukturen gehen verloren mitten im Flow.
REM
REM Fuer Code-Updates: Dieses Fenster mit Ctrl+C stoppen und neu
REM starten. Patient-Daten bleiben durch save_patient() persistent.

cd /d "%~dp0"
python -m uvicorn app:app --host 0.0.0.0 --port 8080
