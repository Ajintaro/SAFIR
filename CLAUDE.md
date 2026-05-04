# SAFIR — Projekt-Kontext für Claude Code

> ## 🟢 AKTUELLER STAND — IMMER ZUERST `docs/PROGRESS.md` LESEN
>
> **System ist eingefroren für die Demo am Mittwoch 29.04.2026.** Alle
> Hardening-Phasen (A1–A5, B, C, D), Demo-Szenarien-Refactor, RFID-Single-
> Write, Recording-Guard, HTTPS-via-Tailscale-Serve und Doku-Updates sind
> abgeschlossen. Stand auf GitHub als Stable-Snapshot.
>
> **Demo-URL fuer Messebesucher (Tailscale-Mesh-intern, gruenes Schloss):**
> - SINA Workstation (Leitstelle): `https://ai-station.tail0fe60f.ts.net/`
> - Jetson (Feldgerät): `https://jetson-orin.tail0fe60f.ts.net/`
> - HTTP `localhost:8080` läuft parallel weiter für Diagnose
>
> **Hardware-Wechsel 04.05.2026**: Die Microsoft Surface ist als
> Leitstelle ausgeschieden, ersetzt durch eine **SINA Workstation**
> (secunet, BSI-zugelassen für VS-NfD). Tailscale-Hostname und
> Backend-URL bleiben identisch (`ai-station` / Tailnet-IP), die
> SAFIR-Backend-Software ist die gleiche. Nur Hardware-Plattform
> + `system_name` + `device_id` (`sina-01`) sind angepasst.
>
> Wenn der User nach der Messe Folge-Aenderungen wünscht, lies erst
> `docs/PROGRESS.md` Abschnitt **„Session 26.04.2026"** für den aktuellen
> Refactor-Stand (Voice-Recognition-Hardening, RFID-Workflow, Tactical &
> Medical Standards, Demo-Szenarien, OLED-Refactor, BAT-Position-UX).
>
> **Urspruengliche Roadmap-Plan-Datei lokal:** `C:\Users\the_s\.claude\plans\effervescent-brewing-alpaca.md`
> (lokal, nicht im Repo, aber durch `docs/PROGRESS.md` im Repo gespiegelt).

## Was ist SAFIR?
Sprachgestützte Assistenz für Informationserfassung in der Rettungskette. KI-gestütztes Dokumentationssystem
entlang der Rettungskette der Bundeswehr. Erste Demo für Bundeswehr-Delegation war am **19.03.2026**.

Auftraggeber: CGI Deutschland. Zielgruppe: Bundeswehr Sanitätsdienst.

## Zwei Geräte

### Jetson Orin Nano (`jetson/`, Hauptcode `app.py`) — Feldgerät (BAT)
- Hardware: NVIDIA Jetson Orin Nano Super, 7.4 GB shared CPU/GPU RAM (Unified Memory), CUDA 12.6
- Whisper small (whisper.cpp, GPU, ~862 MB VRAM) für Echtzeit-Transkription
- Vosk (CPU) für Sprachbefehle — routen auf die shared `_start_record_flow` / `_stop_record_flow` wie der Taster
- Ollama Gemma 3 4B (`gemma3:4b`, 4.3 GB Q4_K_M, 100% GPU via `num_gpu=-1`, permanent im VRAM via `keep_alive=-1`) für Segmentierung (Multi-Patient-Diktat) und 9-Liner-Feldextraktion. **Eiserne Regel: num_gpu=-1 — Gemma hat 34 Layer, num_gpu=20 aus Qwen-Zeiten laesst sonst 40% auf CPU.** Upgrade von Qwen 1.5B am 17.04.2026 (bessere Extraktionsqualitaet, ~15s/Patient).
- Piper TTS (CPU, de_DE-thorsten-medium) mit `check_output_settings` Resample auf device-rate
- FastAPI + WebSocket Dashboard auf Port 8080
- Hardware-Integration: 2 Taster (Rot/Grün, GPIO Pin 11/26), OLED SSD1306 (I2C Bus 7), RFID RC522, LEDs, Shutdown-Combo
- Headless-Autostart via `safir.service` (systemd, User=root) + OLED-Status-Monitor (`safir-oled-ready.service`)
- Live-Sync: Backend-WS-Client (`_backend_ws_loop`) verbindet sich persistent zur Leitstelle, mergt eingehende Patient-Events in `state.patients`
- **Status: funktionsfähig** — Multi-Patient-Flow, Segmentierung, Batch-RFID-Schreiben, bi-direktionaler Live-Sync

### SINA Workstation (`backend/`) — Leitstelle (Role 1)
- Hardware: **SINA Workstation** (secunet, BSI-zugelassen VS-NfD), Windows
- Vorgaenger war eine Microsoft Surface — Hardware-Wechsel am 04.05.2026, Software ist identisch geblieben.
- Tailscale-Hostname: `ai-station`, Backend-URL im Jetson-Config: `http://100.101.80.64:8080`
- `device_id`: `sina-01`, `system_name`: `SINA Workstation`
- FastAPI Backend mit `/api/ingest` (Jetson-Push), `/api/patients`, `/api/units`, WebSocket `/ws`
- Taktische Lagekarte (Leaflet), Event-Feed, Triage-Counts, BAT-Transport-Marker
- Peer-Discovery-Heartbeat (pullt alle aktiven Feldgeräte)
- **Ollama Gemma 4 E4B** (`gemma4:e4b`, 9.6 GB Q4_K_M) für KI-Review (zweite Instanz prüft Jetson-Extraktion gegen Original-Transkript). On-demand geladen, nicht permanent im RAM.
- **Backend-Start**: `start_backend.bat` / `stop_backend.bat` auf Desktop. Backend läuft via `Win32_Process.Create` detached (überlebt SSH-Disconnect).
- **Status: alle Endpoints + Lagekarte + Sync-Empfang + KI-Review funktioniert** — Jetson-Patienten kommen via POST und per WebSocket-Broadcast rein. SitaWare-Exports (CoT/NVG/MEDEVAC/FHIR) auf beiden Backends gespiegelt.

## Tailscale Serve — HTTPS-Zugang im Mesh

Beide Geräte sind via `tailscale serve --bg --https=443` als HTTPS-
Endpunkte im Tailnet erreichbar. Echte Let's-Encrypt-Zertifikate, grünes
Schloss im Browser, **nur** für Mitglieder des Tailnets erreichbar (kein
öffentliches Internet — `tailscale funnel` wäre dafür nötig).

| Gerät | URL |
|---|---|
| Jetson (Feldgerät) | `https://jetson-orin.tail0fe60f.ts.net/` |
| SINA Workstation (Leitstelle) | `https://ai-station.tail0fe60f.ts.net/` |

HTTP `localhost:8080` bleibt parallel verfügbar (Diagnose, lokales Testen).
Cert-Erneuerung erfolgt automatisch alle 60 Tage durch Tailscale.

**Vor erstmaligem `tailscale serve`** musste HTTPS-Cert-Support im
Admin-Panel (`https://login.tailscale.com/admin/dns`) aktiviert werden.
Plus MagicDNS muss aktiv sein (`MagicDNSSuffix: tail0fe60f.ts.net`).

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
- Vosk: Sprachbefehle auf Jetson (offline, leichtgewichtig). Mit `SetWords(True)` für Per-Wort-Confidence (Recording-Guard)
- Ollama:
  - Jetson: **Gemma 3 4B** (`gemma3:4b`, 4.3 GB Q4_K_M, permanent im VRAM via `keep_alive=-1`, `num_gpu=-1` Pflicht — sonst 40% auf CPU)
  - SINA Workstation: **Gemma 4 E4B** (`gemma4:e4b`, 9.6 GB Q4_K_M, on-demand, KI-Review der Jetson-Extraktion)
- Piper TTS auf Jetson (CPU, de_DE-thorsten-medium)
- python-docx + reportlab: DOCX/PDF-Export für Protokolle
- Tailscale Serve: HTTPS-Zugang im Mesh-Netz (LE-Zertifikate, grünes Schloss)
- `shared/version.py`: Single Source of Truth für VERSION (lazy git-rev-Hash). Beide Backends exposen via `/api/status`

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

### Ausgehend: Jetson → Leitstelle (SINA)
- **POST `/api/ingest`** nach erfolgreichem "Melden" (`sync_all_patients()` in `app.py`) — sendet Patient + Transfer-Schema
- Trigger: Sprachbefehl "Patienten melden", OLED-Menü "Melden", GUI-Button
- `patient["synced"] = True` wird nach 200 OK gesetzt
- Auto-Retry über exponential backoff nicht implementiert — Manual-Retry via "Melden" erneut auslösen

### Eingehend: Leitstelle (SINA) → Jetson (Live-Sync)
- **Persistenter WebSocket-Client** `_backend_ws_loop()` verbindet sich zu `ws://<backend>/ws`
- Auto-Reconnect mit exponential backoff (2 s → 30 s)
- Event-Handler `_handle_backend_event()` mergt `init`/`patient_new`/`patient_update`/`patient_deleted`/`transfer_update` in `state.patients` und re-broadcastet an die Jetson-eigenen Dashboard-Clients
- Verbindungsstatus in `state.backend_ws_connected`, Broadcast-Event `backend_link`

### Netzwerk-Setup
- Beide Geräte hängen via **Tailscale** (Mesh-VPN) zusammen — kein gemeinsames WLAN nötig
- Backend-URL in `config.json`: `http://100.101.80.64:8080` (Tailscale-IP der SINA Workstation)
- Jetson-Tailscale-IP: `100.126.179.27`, Hostname `jetson-orin`
- SINA-Workstation-Tailscale-Hostname: `ai-station`

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

## Status AFCEA-Implementierungsplan (siehe `docs/PROGRESS.md`)

| Phase | Inhalt | Status |
|---|---|---|
| **1** | Quick Wins (Theme, Reset, Triage Role 0 raus, Aufnahme-Bug) | ✓ |
| **2** | Segmenter num_ctx + Post-Merge 3 (Defense in Depth) | ✓ |
| **3** | Demo-Story (Sim raus, BAT-Standort + Rückfahrt, Testdaten-Generator) | ✓ |
| **4.1–4.3** | RFID-Sektor-2-Fix, OLED NETZWERK, Audio Multi-Output | ✓ |
| **5** | 9-Liner Voice-Recognition (Template + Auto-Detect + UI) | ✓ |
| **6** | Export & Interoperabilität (DOCX/PDF/JSON/XML) | ✓ |
| **7** | Encryption-Story + Use-Case-Vision-Page | ✓ |
| **8** | Remote Audio MVP | 🟡 deferred (V2-Roadmap) |
| **9** | Final Polish, E2E Demo-Run, RAM-Stress-Test | ✓ |
| **A1–A5** | Messe-Hardening: Prompt-Injection, Vitals-Plausibility, Content-Guardrails, Rate-Limit, Length-Limits | ✓ |
| **B1** | Confidence-Badges grün/gelb/rot pro Feld | ✓ |
| **Polish 26.04** | HTTPS via Tailscale, RFID-Single-Write, Recording-Guard, Demo-Szenarien-Refactor, Tactical/Medical Standards (CoT/NVG/MEDEVAC/FHIR), Patient-Detail-OLED, Version-Display dynamisch | ✓ |

## Multi-Patient-Flow (BAT-Workflow)

1. Sanitäter **startet Aufnahme** (Taster B lang / Sprachbefehl "Neuer Patient" / "Aufnahme starten") — kein Patient-Record wird vorab angelegt
2. Diktiert frei durch (bis ~10 Min), mehrere Verwundete nacheinander. Typisches Trenn-Signal: *"Der nächste Patient ist ..."*, *"Weiter mit dem nächsten"*
3. **Aufnahme stoppen** (Taster B lang / "Aufnahme beenden") — TTS sofort, Whisper transkribiert im Hintergrund in 25-s-Chunks
4. Transkript landet als **neuer Eintrag** in `state.pending_transcripts` (Liste, nie überschrieben). Auf dem Dashboard erscheint eine aufklappbare Karte mit Status `UNANALYSIERT`
5. Sanitäter **prüft das Transkript** visuell. Optional: neue Aufnahme anhängen (weitere Aufnahmen werden parallel gesammelt)
6. **Analyse** (OLED-Menü "Analysieren" / Sprachbefehl / Button) — Gemma 3 4B segmentiert an Satzgrenzen (`BOUNDARY_PROMPT`), Post-Merge für Übergangs- und Pronomen-Segmente, dann pro Segment `run_patient_enrichment` für 9-Liner-Felder (Name, Rank, Verletzungen, Vitals — **keine Auto-Triage**)
7. **RFID-Schreiben** (zwei Pfade):
   - **Batch** (OLED "RFID schreiben" / Sprachbefehl / Fahrzeug-Button "RFID-Batch") — iteriert durch alle Patienten ohne Karte
   - **Per-Patient** (Fahrzeug-Modus: `📇 Karte`-Button pro Patient-Card, oder `POST /api/rfid/write-single` mit `{patient_id}`) — Use-Case: Sanitäter mit nur 3 Karten für 8 Patienten wählt gezielt aus
   - 3-Stufen-Recovery (Direkt → Soft-Reauth → Hard-Recovery via RC522-Reset). Inter-Block-Delay 50 ms. Warm-up 100 ms vor erstem Sektor.
8. **Melden** sendet alle `analyzed && !synced` Patienten via `POST /api/ingest` an das Leitstellen-Backend (SINA). Die Leitstelle broadcastet via WS zurück an alle BATs.

**Wichtig: RFID-Write meldet Patient NICHT automatisch** (User-Wunsch).
Differenziertes Verhalten:
- Patient `synced=False` (lokal, nie gemeldet): RFID-Write nur lokal, kein Leitstellen-Push. Sanitäter muss explizit „Patienten melden" sagen.
- Patient `synced=True` (schon gemeldet): UID-Update wird sofort an die Leitstelle geschickt — sonst kennt sie die Karten-UID nicht beim Omnikey-Scan an der Rettungsstation.

Triage wird **erst in Role 1 (Rettungsstation)** manuell gesetzt — Triage-Buttons im Dashboard oder Sprachbefehl "Triage rot/gelb/grün/blau". In Phase 0 (BAT) sind Triage-Updates **deaktiviert** (`voice_set_triage` und `update_patient` ignorieren das Feld bei `current_role == "phase0"`, TTS-Hinweis: "Triage erfolgt erst in der Rettungsstation"). Gemma erfindet sonst Werte die nicht im Text stehen — deshalb auch keine Auto-Triage im LLM-Prompt.

## Voice-Recognition-Hardening (Recording-Guard)

Während aktiver Aufnahme (`state.recording == True`) blockt der Recording-
Guard in `persistent_audio_callback` versehentliche Trigger-Auslösungen:

1. **Action-Whitelist**: nur `record_stop`, `patient_ready`, `new_patient`
   werden überhaupt ausgewertet. Triage / Export / RFID / 9-Liner-Modus
   etc. sind während Aufnahme stumm.
2. **Trigger-am-Ende-Check**: max. 1 Filler-Wort nach dem Trigger. Erlaubt
   "...stabilisieren. Aufnahme beenden", blockt "die Blutung **stoppen**
   und stabilisieren" (Trigger als Substring mitten in Diktatsatz).
3. **Confidence-Gate**: Vosk muss avg-Confidence ≥ 0.6 melden — filtert
   offensichtliche Hintergrund-Halluzinationen.

Plus: Single-Wort-Trigger sind aus `config.json` entfernt (`dringend`,
`abbrechen`, `aufschiebbar`, `abwartend`, `sofort behandlung`) — die
kamen zu oft im normalen Sprachfluss vor und feuerten Triage/Cancel-
Aktionen auf.

Logging: jedes Vosk-Final wird mit `[VOSK] text=... words=N conf=0.XX
match=ACTION rec=BOOL` geloggt, inkl. Guard-Entscheidungen
(`[VOSK-GUARD] ACTION blockiert: ...`).

## Demo-Story: BAT-Standort + Rückfahrt zur Rettungsstation (Phase 3)

Ersetzt die alte Frontend-Simulation. Voreingestellte Bonn-Standorte
(Beuel, Hardthöhe, Bad Godesberg, Endenich, Rheinaue) als Dropdown im
Fahrzeug-Modus. Sanitäter wählt Standort → drückt "Rückfahrt zur
Rettungsstation" → BAT-Marker bewegt sich animiert (40 Steps × 1.5 s
= 60 s) auf der Leitstellen-Karte zur Rettungsstation
(`config.json:rescue_station`, default 50.7374/7.0982 Bonn).
Voice-Command "rückfahrt zur rettungsstation" mit Variants. API:
`/api/bat/position/presets`, `/api/bat/position`, `/api/bat/position/set`,
`/api/bat/return-to-station`. Background-Task: `bat_position_loop()`.

## OLED-Pages (4 Stück seit Phase 4.2)

`PAGES = ["models", "network", "operator", "patient"]`. Wechseln per
Taster A (rot, Pin 11) Short-Press. NETZWERK-Seite zeigt WLAN-SSID, IP,
Tailscale-Status, Backend-Erreichbarkeit mit großen Fonts (FONT_LG/MD,
nicht FONT_SM). Datenquelle: `oled_menu.network_info`, alle 2 s
befüllt vom `_oled_update_loop` via `_get_wifi_status()`,
`_get_tailscale_state()`, `_get_eth_ip()`, `_get_primary_ip()`.

## Audio Multi-Output (Phase 4.3)

`shared/tts.py` spielt parallel auf ALLEN erkannten Speaker-Devices
(`_output_devices` als Liste, ein Thread pro Device). USB-Headset +
Lautsprecher gleichzeitig — der Messebesucher mit Headset hört
genauso wie die Umstehenden über den Lautsprecher.
Hot-Plug-Watcher (`_audio_device_watcher_loop`) überwacht
`/proc/asound/cards` alle 3 s und triggert Refresh + OLED-/TTS-
Notification. **Bekannte Limitation**: Beim Einstecken eines neuen
USB-Audio-Devices während des Betriebs wird es OLED+TTS angekündigt,
aber Multi-Output greift erst nach `systemctl restart safir`
(PortAudio cached die ALSA-Geräteliste auf Linux hartnäckig).

## Konventionen
- Deutsche Umlaute verwenden (ä, ö, ü, ß) — NICHT ae, oe, ue, ss
- Kommentare auf Deutsch
- API-Endpunkte auf Englisch (/api/patients, /api/ingest)
- Kein TypeScript, kein Build-System — alles inline in HTML Templates
