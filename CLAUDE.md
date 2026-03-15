# SAFIR — Projekt-Kontext für Claude Code

## Was ist SAFIR?
Sprachgestützte Assistenz für Informationserfassung in der Rettungskette. KI-gestütztes Dokumentationssystem
entlang der Rettungskette der Bundeswehr. Demo für AFCEA Bonn / Bundeswehr-Delegation am **19.03.2026**.

Auftraggeber: CGI Deutschland. Zielgruppe: Bundeswehr Sanitätsdienst.

## Zwei Geräte

### Jetson Orin Nano (`jetson/`) — Feldgerät
- Hardware: NVIDIA Jetson Orin Nano, 7.4GB shared CPU/GPU RAM, CUDA 12.6
- Whisper small (whisper.cpp, GPU) für Echtzeit-Transkription
- Vosk (CPU) für Sprachbefehle ("Aufnahme starten/stoppen")
- Ollama Qwen2.5-1.5B (CPU) für 9-Liner Feldextraktion
- FastAPI + WebSocket Dashboard auf Port 8080
- Simuliert den Sanitäter im Feld (Phase 0 / Role 1)
- **Status: funktionsfähig** — Spracheingabe, Transkription, 9-Liner Extraktion laufen
- **TODO: Backend-Sync implementieren** (siehe Abschnitt "Jetson → Backend Anbindung")

### Alienware + RTX 5090 (`backend/`) — Leitstelle
- Hardware: NVIDIA RTX 5090, 24GB VRAM, Windows
- Whisper large-v3 (faster-whisper, GPU, ~3GB VRAM) für beste Transkriptionsqualität
- pyannote-audio 3.1 (~2GB VRAM) für Speaker Diarization (wer spricht wann)
- Ollama Qwen2.5-32B (Q4, ~18GB VRAM) für intelligente Analyse
- FastAPI Dashboard auf Port 8080
- Bildet die gesamte Rettungskette Role 1-4 ab
- **Status: Role 1 Lagekarte funktionsfähig** — Taktische NATO-Symbole, BAT-Bewegung, Simulation

## Rettungskette der Bundeswehr (Goldene Stunde)

| Stufe | Name | Einrichtung | KI-Unterstützung |
|-------|------|-------------|-------------------|
| Phase 0 | Selbst-/Kameradenhilfe | Vor Ort | Jetson: Sprachdoku, 9-Liner |
| Role 1 | Erste ärztl. Behandlung | Rettungsstation | Triage, Vitalwerte, TCCC Card |
| Role 2 | Chirurgische Akutversorgung | Rettungszentrum | Übergabeberichte, OP-Vorbereitung |
| Role 3 | Erweiterte Versorgung | Einsatzlazarett | Patientenakte, Diagnose-KI |
| Role 4 | Rehabilitation | BW-Krankenhaus | Statistik, Auswertung |

Kernprinzip: Verwundete müssen innerhalb von 60 Minuten medizinisch versorgt werden.

## Tech Stack
- Python 3, FastAPI, WebSocket, Jinja2 Templates (kein React/Vue — reines HTML+JS)
- Whisper: whisper.cpp auf Jetson, faster-whisper auf Alienware
- Vosk: Sprachbefehle auf Jetson (offline, leichtgewichtig)
- Ollama: Qwen2.5-1.5B auf Jetson (CPU), Qwen2.5-32B auf Alienware (GPU)
- pyannote-audio: Speaker Diarization nur auf Alienware
- python-docx: DOCX-Export für Protokolle

## CGI Corporate Design
- Primärfarbe: Rot #E11937
- Font: Inter (Google Fonts)
- Dark Mode als Standard, Light Mode optional
- Professionell, militärisch-sachlich, keine verspielten Elemente

## Datenfluss
1. Sanitäter spricht im Feld → Jetson nimmt auf
2. Whisper transkribiert → LLM extrahiert 9-Liner Felder
3. Jetson sendet Patientendaten an Backend: `POST /api/ingest`
4. Backend verarbeitet: LLM-Analyse, Übergabeberichte
5. Dashboard zeigt Patient in der Rettungskette auf der taktischen Lagekarte

## Gemeinsame Datenmodelle
Siehe `shared/models.py`:
- `PATIENT_SCHEMA`: Kompletter Patientendatensatz (Stammdaten, 9-Liner, Vitals, Verletzungen, Timeline)
- `TRANSFER_SCHEMA`: Format für Jetson→Backend Datenübertragung
- `RoleLevel`: Enum Phase0, Role1-4
- `TriagePriority`: T1 (sofort) bis T4 (abwartend)

## Jetson → Backend Anbindung (AKTUELL WICHTIGSTE AUFGABE)

### Was existiert
- **Backend-Empfang**: `POST /api/ingest` in `backend/app.py` — empfängt Patientendaten, speichert sie, sendet `patient_new` WebSocket-Event an alle Clients
- **Jetson-Seite**: Transkription und LLM-Extraktion funktionieren lokal. Es fehlt der HTTP-Push ans Backend.

### Was auf dem Jetson implementiert werden muss
1. **Backend-URL konfigurierbar machen**:
   - Umgebungsvariable `BACKEND_URL` (z.B. `http://192.168.1.100:8080`)
   - Fallback: `http://127.0.0.1:8080` für lokale Tests
2. **Sync-Funktion implementieren** (`sync_to_backend()`):
   - Nach Registrierung eines Patienten oder nach KI-Analyse
   - `POST /api/ingest` mit Payload nach `TRANSFER_SCHEMA`
   - Retry-Logik bei Netzwerkfehlern (max 3 Versuche)
   - Status "übermittelt" im Jetson-UI anzeigen
3. **Payload-Format** (was das Backend erwartet):
   ```json
   {
     "patient": {
       "patient_id": "uuid",
       "name": "Nachname, Vorname",
       "triage": "T1",
       "injuries": ["Schusswunde li. Oberschenkel"],
       "vitals": {"pulse": "120", "spo2": "92", "blood_pressure": "90/60"},
       "nine_liner": {...},
       "transcripts": ["freitext..."],
       "current_role": "phase0"
     },
     "unit_name": "BAT Alpha42",
     "device_id": "jetson-01"
   }
   ```
4. **Wann senden**:
   - Automatisch nach Patient-Registrierung (RFID-Scan oder manuell)
   - Automatisch nach KI-Analyse (wenn neue Felder extrahiert wurden)
   - Manueller "Übermitteln"-Button als Fallback
5. **WebSocket-Event auf dem Backend**:
   - Backend sendet automatisch `patient_new` an alle Dashboard-Clients
   - Jetson muss sich NICHT um das Dashboard kümmern

### Netzwerk-Setup für die Demo
- Jetson und Alienware im gleichen WLAN/LAN
- Alienware-IP muss auf dem Jetson als `BACKEND_URL` gesetzt werden
- Port 8080 muss erreichbar sein

## Konventionen
- Deutsche Umlaute verwenden (ä, ö, ü, ß) — NICHT ae, oe, ue, ss
- Kommentare auf Deutsch
- API-Endpunkte auf Englisch (/api/patients, /api/ingest)
- Kein TypeScript, kein Build-System — alles inline in HTML Templates
