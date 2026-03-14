# SAFIR — Projekt-Kontext fuer Claude Code

## Was ist SAFIR?
Sprachgestuetzte Assistenz fuer Informationserfassung in der Rettungskette. KI-gestuetztes Dokumentationssystem
entlang der Rettungskette der Bundeswehr. Demo fuer AFCEA Bonn / Bundeswehr-Delegation am **19.03.2026**.

Auftraggeber: CGI Deutschland. Zielgruppe: Bundeswehr Sanitaetsdienst.

## Zwei Geraete

### Jetson Orin Nano (`jetson/`) — Feldgeraet
- Hardware: NVIDIA Jetson Orin Nano, 7.4GB shared CPU/GPU RAM, CUDA 12.6
- Whisper small (whisper.cpp, GPU) fuer Echtzeit-Transkription
- Vosk (CPU) fuer Sprachbefehle ("Aufnahme starten/stoppen")
- Ollama Qwen2.5-1.5B (CPU) fuer 9-Liner Feldextraktion
- FastAPI + WebSocket Dashboard auf Port 8080
- Simuliert den Sanitaeter im Feld (Phase 0 / Role 1)
- **Status: funktionsfaehig** — Spracheingabe, Transkription, 9-Liner Extraktion laufen

### Alienware + RTX 5090 (`backend/`) — Leitstelle
- Hardware: NVIDIA RTX 5090, 24GB VRAM, Windows
- Whisper large-v3 (faster-whisper, GPU, ~3GB VRAM) fuer beste Transkriptionsqualitaet
- pyannote-audio 3.1 (~2GB VRAM) fuer Speaker Diarization (wer spricht wann)
- Ollama Qwen2.5-32B (Q4, ~18GB VRAM) fuer intelligente Analyse
- FastAPI Dashboard auf Port 8080
- Bildet die gesamte Rettungskette Role 1-4 ab
- **Status: Skeleton vorhanden, muss ausgebaut werden**

## Rettungskette der Bundeswehr (Goldene Stunde)

| Stufe | Name | Einrichtung | KI-Unterstuetzung |
|-------|------|-------------|-------------------|
| Phase 0 | Selbst-/Kameradenhilfe | Vor Ort | Jetson: Sprachdoku, 9-Liner |
| Role 1 | Erste aerztl. Behandlung | Rettungsstation | Triage, Vitalwerte, TCCC Card |
| Role 2 | Chirurgische Akutversorgung | Rettungszentrum | Uebergabeberichte, OP-Vorbereitung |
| Role 3 | Erweiterte Versorgung | Einsatzlazarett | Patientenakte, Diagnose-KI |
| Role 4 | Rehabilitation | BW-Krankenhaus | Statistik, Auswertung |

Kernprinzip: Verwundete muessen innerhalb von 60 Minuten medizinisch versorgt werden.

## Tech Stack
- Python 3, FastAPI, WebSocket, Jinja2 Templates (kein React/Vue — reines HTML+JS)
- Whisper: whisper.cpp auf Jetson, faster-whisper auf Alienware
- Vosk: Sprachbefehle auf Jetson (offline, leichtgewichtig)
- Ollama: Qwen2.5-1.5B auf Jetson (CPU), Qwen2.5-32B auf Alienware (GPU)
- pyannote-audio: Speaker Diarization nur auf Alienware
- python-docx: DOCX-Export fuer Protokolle

## CGI Corporate Design
- Primaerfarbe: Rot #E11937
- Font: Inter (Google Fonts)
- Dark Mode als Standard, Light Mode optional
- Professionell, militaerisch-sachlich, keine verspielten Elemente

## Datenfluss
1. Sanitaeter spricht im Feld → Jetson nimmt auf
2. Whisper transkribiert → LLM extrahiert 9-Liner Felder
3. Jetson sendet Patientendaten an Backend: `POST /api/ingest`
4. Backend verarbeitet: Speaker Diarization, LLM-Analyse, Uebergabeberichte
5. Dashboard zeigt Patient in der Rettungskette, verschiebbar zwischen Roles

## Gemeinsame Datenmodelle
Siehe `shared/models.py`:
- `PATIENT_SCHEMA`: Kompletter Patientendatensatz (Stammdaten, 9-Liner, Vitals, Verletzungen, Timeline)
- `TRANSFER_SCHEMA`: Format fuer Jetson→Backend Datenuebertragung
- `RoleLevel`: Enum Phase0, Role1-4
- `TriagePriority`: T1 (sofort) bis T4 (abwartend)

## Was auf dem Alienware zu tun ist (Prioritaet)
1. **Speaker Diarization** einrichten: faster-whisper + pyannote-audio, Audio hochladen, Sprecher erkennen
2. **Rettungsketten-Dashboard** ausbauen: Patient durch Roles schieben, Detail-Ansicht, Timeline
3. **LLM-Analyse**: Uebergabeberichte generieren, Zusammenfassungen, Triage-Empfehlung
4. **Jetson-Anbindung**: /api/ingest testen, Echtzeit-Updates via WebSocket
5. **DOCX-Export**: Uebergabeprotokolle, Patientenakten

## Konventionen
- Deutsche Umlaute verwenden (ä, ö, ü, ß) — NICHT ae, oe, ue, ss
- Kommentare auf Deutsch
- API-Endpunkte auf Englisch (/api/patients, /api/ingest)
- Kein TypeScript, kein Build-System — alles inline in HTML Templates
