# SAFIR — Projekt-Kontext für Claude Code

## Was ist SAFIR?
Sprachgestützte Assistenz für Informationserfassung in der Rettungskette. KI-gestütztes Dokumentationssystem
entlang der Rettungskette der Bundeswehr. Erste Demo für Bundeswehr-Delegation war am **19.03.2026**.

Auftraggeber: CGI Deutschland. Zielgruppe: Bundeswehr Sanitätsdienst.

## Zwei Geräte

### Jetson Orin Nano (`jetson/`, Hauptcode `app.py`) — Feldgerät (BAT)
- Hardware: NVIDIA Jetson Orin Nano Super, 7.4 GB shared CPU/GPU RAM (Unified Memory), CUDA 12.6
- Whisper small (whisper.cpp, GPU, ~862 MB VRAM) für Echtzeit-Transkription
- Vosk (CPU) für Sprachbefehle — routen auf die shared `_start_record_flow` / `_stop_record_flow` wie der Taster
- Ollama Qwen2.5-1.5B (permanent im VRAM, `keep_alive: -1`) für Segmentierung (Multi-Patient-Diktat) und 9-Liner-Feldextraktion
- Piper TTS (CPU, de_DE-thorsten-medium) mit `check_output_settings` Resample auf device-rate
- FastAPI + WebSocket Dashboard auf Port 8080
- Hardware-Integration: 2 Taster (Rot/Grün, GPIO Pin 11/26), OLED SSD1306 (I2C Bus 7), RFID RC522, LEDs, Shutdown-Combo
- Headless-Autostart via `safir.service` (systemd, User=root) + OLED-Status-Monitor (`safir-oled-ready.service`)
- Live-Sync: Backend-WS-Client (`_backend_ws_loop`) verbindet sich persistent zum Surface, mergt eingehende Patient-Events in `state.patients`
- **Status: funktionsfähig** — Multi-Patient-Flow, Segmentierung, Batch-RFID-Schreiben, bi-direktionaler Live-Sync

### Microsoft Surface (`backend/`) — Leitstelle (Role 1)
- Hardware: Microsoft Surface, Windows
- Tailscale-Hostname: `ai-station`, Backend-URL im Jetson-Config: `http://100.101.80.64:8080`
- FastAPI Backend mit `/api/ingest` (Jetson-Push), `/api/patients`, `/api/units`, WebSocket `/ws`
- Taktische Lagekarte (Leaflet), Event-Feed, Triage-Counts, BAT-Transport-Marker
- Peer-Discovery-Heartbeat (pullt alle aktiven Feldgeräte)
- **Status: Lagekarte + Sync-Empfang funktioniert** — Jetson-Patienten kommen via POST und per WebSocket-Broadcast rein
- Hardware-Specs/Modelle (Whisper, Ollama, pyannote): **TODO — beim nächsten Setup aktualisieren**

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
- Whisper: whisper.cpp auf Jetson (Feldgerät)
- Vosk: Sprachbefehle auf Jetson (offline, leichtgewichtig)
- Ollama: Qwen2.5-1.5B auf Jetson, permanent im VRAM (`keep_alive: -1`)
- Piper TTS auf Jetson (CPU, de_DE-thorsten-medium)
- Surface (Leitstelle): Hardware-Specs/Modelle bei Bedarf einsetzen
- python-docx: DOCX-Export für Protokolle

## UI Design — Military Tactical HUD
- Farben: --mil-bg #0f1209, --mil-tan #c8b878, --mil-green #5a9e3a, --mil-amber #d4871a, --mil-red #cc2222
- Fonts: Share Tech Mono (Daten), Rajdhani (Labels/Buttons), beide Google Fonts
- Labels: UPPERCASE, letter-spacing 0.12-0.18em
- Panels: KEIN border-radius, stattdessen Bracket-Corners (L-förmige Ecken in --mil-tan)
- Verboten: Tailwind, Inter/Roboto, border-radius>2px, weiße Hintergründe, Material Design

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

## Jetson ↔ Backend Anbindung (IMPLEMENTIERT, bi-direktional)

### Ausgehend: Jetson → Surface
- **POST `/api/ingest`** nach erfolgreichem "Melden" (`sync_all_patients()` in `app.py`) — sendet Patient + Transfer-Schema
- Trigger: Sprachbefehl "Patienten melden", OLED-Menü "Melden", GUI-Button
- `patient["synced"] = True` wird nach 200 OK gesetzt
- Auto-Retry über exponential backoff nicht implementiert — Manual-Retry via "Melden" erneut auslösen

### Eingehend: Surface → Jetson (Live-Sync)
- **Persistenter WebSocket-Client** `_backend_ws_loop()` verbindet sich zu `ws://<backend>/ws`
- Auto-Reconnect mit exponential backoff (2 s → 30 s)
- Event-Handler `_handle_backend_event()` mergt `init`/`patient_new`/`patient_update`/`patient_deleted`/`transfer_update` in `state.patients` und re-broadcastet an die Jetson-eigenen Dashboard-Clients
- Verbindungsstatus in `state.backend_ws_connected`, Broadcast-Event `backend_link`

### Netzwerk-Setup
- Beide Geräte hängen via **Tailscale** (Mesh-VPN) zusammen — kein gemeinsames WLAN nötig
- Backend-URL in `config.json`: `http://100.101.80.64:8080` (Tailscale-IP des Surface)
- Jetson-Tailscale-IP: `100.126.179.27`, Hostname `jetson-orin`
- Surface-Tailscale-Hostname: `ai-station`

## GPU-Speicher-Management (Jetson Orin Nano)

Das Jetson hat 7.4 GB Unified Memory (CPU+GPU shared). **Whisper + Qwen laufen parallel permanent im Speicher** (kein GPU-Swap mehr):
- Whisper small: ~1.2 GB RSS (inkl. Server-Overhead)
- Ollama qwen2.5:1.5b (`keep_alive: -1`): ~1.1 GB VRAM
- CUDA/Tegra Overhead: ~1 GB
- Verfügbar nach beiden Modellen: **~3.5 GB** (im Headless-Mode)

### Kritisch: Startreihenfolge
**Ollama MUSS vor Whisper gestartet werden!** Andernfalls schlägt `cudaMalloc` fehl (Speicherfragmentierung).
`scripts/safir-start.sh` macht das in der richtigen Reihenfolge:
1. Ollama starten + Qwen permanent vorladen (`keep_alive: -1`)
2. Whisper-Server starten (durch uvicorn/app.py triggered)
3. SAFIR FastAPI App `exec uvicorn app:app` als Vordergrund-Prozess

### Speicher sparen
- **Headless-Boot aktiv**: `systemctl set-default multi-user.target` → ~800 MB GUI weg, ~3.5 GiB statt 2.5 GiB verfügbar
- Claude Code Agent kostet ~340 MB → Remote per `ssh jetson@jetson-orin` starten
- Powerbank: 20.000 mAh / 15 V / 65 W — reicht für ganzen Demo-Tag (~20 h bei 15 W)
- **Wichtig**: Nicht an USB-Hubs mit nur 12 V / 0.5 A betreiben — brownout + Reboot (Hardware-Problem, nicht Software)

### Tailscale SSH
Tailscale SSH ist aktiviert auf dem Jetson (`sudo tailscale set --ssh`).
MacBook kann sich verbinden: `ssh jetson@jetson-orin` oder `ssh jetson@100.126.179.27`

## Status der früheren Aufgaben (nach Demo 19.03.2026)

| # | Aufgabe | Status |
|---|---------|--------|
| 1 | Aufnahmedauer erhöhen + Multi-Patient pro Diktat | ✓ MAX_RECORD_SECONDS 600, Chunk-basierte Segmentierung via Qwen |
| 2 | NFC Abstrahlsicherheit prüfen (TEMPEST/EmSec) | offen, braucht zertifiziertes Labor (BWB, Rohde & Schwarz) |
| 3 | Backend-Sync finalisieren | ✓ bi-direktional (`/api/ingest` + WS-Client) |
| 4 | Headless-Boot für Messe | ✓ `systemctl set-default multi-user.target` + Autostart via `safir.service` |

## Multi-Patient-Flow (BAT-Workflow)

1. Sanitäter **startet Aufnahme** (Taster B lang / Sprachbefehl "Neuer Patient" / "Aufnahme starten") — kein Patient-Record wird vorab angelegt
2. Diktiert frei durch (bis ~10 Min), mehrere Verwundete nacheinander. Typisches Trenn-Signal: *"Der nächste Patient ist ..."*, *"Weiter mit dem nächsten"*
3. **Aufnahme stoppen** (Taster B lang / "Aufnahme beenden") — TTS sofort, Whisper transkribiert im Hintergrund in 25-s-Chunks
4. Transkript landet als **neuer Eintrag** in `state.pending_transcripts` (Liste, nie überschrieben). Auf dem Dashboard erscheint eine aufklappbare Karte mit Status `UNANALYSIERT`
5. Sanitäter **prüft das Transkript** visuell. Optional: neue Aufnahme anhängen (weitere Aufnahmen werden parallel gesammelt)
6. **Analyse** (OLED-Menü "Analysieren" / Sprachbefehl / Button) — Qwen segmentiert an Satzgrenzen (`BOUNDARY_PROMPT`), Post-Merge für Übergangs- und Pronomen-Segmente, dann pro Segment `run_patient_enrichment` für 9-Liner-Felder (Name, Rank, Verletzungen, Vitals — **keine Auto-Triage**)
7. **RFID-Batch schreiben** (OLED "RFID schreiben" / Sprachbefehl / Fahrzeug-GUI-Button) — iteriert durch alle Patienten ohne `rfid_written`-Timeline-Event, OLED/TTS führt Karte für Karte durch
8. **Melden** sendet alle `analyzed && !synced` Patienten via `POST /api/ingest` an das Surface-Backend. Surface broadcastet via WS zurück an alle BATs.

Triage wird **manuell** gesetzt (Triage-Buttons im Dashboard oder Sprachbefehl "Triage rot/gelb/grün/blau") — Qwen erfindet sonst Werte die nicht im Text stehen.

## Konventionen
- Deutsche Umlaute verwenden (ä, ö, ü, ß) — NICHT ae, oe, ue, ss
- Kommentare auf Deutsch
- API-Endpunkte auf Englisch (/api/patients, /api/ingest)
- Kein TypeScript, kein Build-System — alles inline in HTML Templates
