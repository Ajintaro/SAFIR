# SAFIR — Implementierungs-Fortschritt vor AFCEA-Messe

> **Für Claude Code beim Session-Start lesen.** Wenn der User sagt
> „mit dem Plan fortfahren" oder „weiter mit Phase X" — diese Datei ist
> die Wahrheit über aktuelle Phasen-Status, Befunde, Limitations und
> nächste Schritte. Der ursprüngliche Plan liegt unter
> `C:\Users\the_s\.claude\plans\effervescent-brewing-alpaca.md` (lokal,
> nicht im Repo).

**Letzte Session:** 16.04.2026 (Phase 7 abgeschlossen, Phase 8 deferred, Phase 9 gestartet)
**Demo-Ziel:** AFCEA-Messe in 3–4 Wochen
**Nächste Aktion:** Phase 9 — Final Polish + E2E Demo-Runs + RAM-Stress-Test
**Phase 8 Entscheidung:** User hat "Überspringen für jetzt" gewählt — Remote-Audio wird als "konzeptionell vorhanden, V2-Roadmap" in der Messe-Präsentation erwähnt, aber nicht implementiert. Priorität auf Demo-Robustheit.

---

## Wie wir arbeiten

- **Surface** = Microsoft Surface, Hostname `ai-station`, Tailscale `100.101.80.64`. Lokales Repo unter `C:\Users\the_s\Documents\SAFIR`. Hier sitze ich (Claude Code) und editiere den Code.
- **Jetson** = NVIDIA Jetson Orin Nano, Hostname `jetson-orin`, Tailscale `100.126.179.27`. Repo unter `/home/jetson/cgi-afcea-san/`. Erreichbar via `ssh jetson@jetson-orin` (Tailscale SSH + Public-Key-Auth, kein Passwort nötig).
- **Workflow**: Lokal auf Surface editieren → committen → push → Jetson `git pull` → `sudo systemctl restart safir`. Manchmal direkt-Upload via `ssh jetson "cat > path" < file` für schnelle Test-Iteration, dann Commit nach Erfolg.
- Beide Repos teilen sich `templates/index.html` im Repo-Root, das wird vom Backend bevorzugt vor `backend/templates/index.html` gerendert.

## Tools die der User bereitstellt

- **Hardware-Tests am Jetson**: User sitzt physisch beim Jetson. Bei RFID/OLED/Audio-Tests stoppe ich `safir.service`, führe Diagnose-Skript aus, User reagiert (Karte auflegen, Stecker rein/raus), ich starte Service neu. **TTS-Audio-Signale verwenden** für User-Prompts statt Bildschirm-Watch — der User hört das Jetson direkt.
- **Voice-Trigger der RFID-Karte für Audio-Tests**: User wurde wegen Tailscale-SSH-Auth-Cache-Ablauf manchmal aufgefordert, einen Browser-Auth-Link zu klicken (https://login.tailscale.com/a/...).

## Architektur-Entscheidungen (User-bestätigt)

| Entscheidung | Wahl | Begründung |
|---|---|---|
| Zeitrahmen | 3–4 Wochen | Komfortabel, alles im Scope außer Custom-Crypto |
| Remote Audio (Phase 8) | MVP-Variante | Browser-Mic via WebSocket → Jetson, ~2 Tage |
| Encryption (Phase 7) | Talking Points + Architektur-Diagramm | Tailscale-WireGuard erklären, kein Custom-Crypto |
| PDF-Library (Phase 6) | reportlab | Self-contained, Jetson-tauglich |
| Segmenter-Modell | qwen2.5:1.5b mit Post-Merge 3 | 3B getestet, sprengt VRAM neben Whisper |

---

## Phasen-Übersicht

| Phase | Inhalt | Status | Commit |
|---|---|---|---|
| **Setup** | WIP-Änderungen auf Jetson verworfen, beide Repos clean | ✅ DONE | (kein commit) |
| **Phase 1** | Quick Wins: Bundeswehr-Theme, Datenbereinigung, Triage Role 0 raus, Aufnahme-Bug | ✅ DONE | `ecebe02` |
| **Phase 2** | Segmenter-Migration (3B versucht → Rollback), num_ctx + Post-Merge 3 | ✅ DONE (mit Caveat) | `34aafba` + `d13ea38` |
| **Phase 3** | Demo-Story Refactor: Sim raus, BAT-Standort, Rückfahrt-Animation, Testdaten-Generator | ✅ DONE | `e638323` |
| **Phase 4.1** | RFID Sektor-2-Bug behoben (Hardware-Reset zwischen Sektoren) | ✅ DONE | `d878b48` |
| **Phase 4.2** | OLED NETZWERK-Seite mit großen Fonts | ✅ DONE | `a17e7aa` |
| **Phase 4.3** | Audio Multi-Output + Hot-Plug-Watcher (mit Restart-Hinweis) | ✅ DONE (mit Caveat) | `5e1535a` |
| **Phase 5** | 9-Liner Voice-Recognition (Template + Auto-Detect + UI) | ✅ DONE | `9dd4411` + `dbf86a3` |
| **Phase 6** | Export & Interoperabilität (DOCX/PDF/JSON/XML) + Refactor | ✅ DONE | `1a397dd` + `7e987ea` |
| **Phase 7** | Encryption-Story + Use-Case-Vision-Page | ✅ DONE | `4a804ca` |
| **Phase 8** | Remote Audio MVP (Browser → WebSocket → Jetson) | 🟡 DEFERRED | — |
| **Phase 9** | Final Polish, E2E Demo-Run, RAM-Stress-Test | ⏳ IN PROGRESS | — |

**Git-Stand zuletzt:** `85afefc` (origin/main). Jetson ist auf demselben Commit, Service läuft.

**Phase 8 ist absichtlich deferred** — User hat beim Phase-Übergang entschieden dass Demo-Robustheit wichtiger ist als ein nice-to-have Feature. Phase 8 wird auf der Messe als "V2-Roadmap" erwähnt.

---

## Was Phase 1–4 gemacht haben (Details)

### Phase 1 — Quick Wins (`ecebe02`)

- **1.1 Bundeswehr-Olive Theme freigeschaltet**: CSS-Variablen waren schon vollständig in `templates/index.html` Zeilen 92–117, JS-Maps `THEMES`/`THEME_ICONS`/`THEME_LABELS` enthielten `bundeswehr` schon — fehlte nur die `<option>` im Settings-Dropdown. 1-Zeilen-Fix.
- **1.2 `/api/data/reset` vervollständigt**:
  - **Jetson `app.py`**: leerte vorher nur 4 von ~10 State-Feldern. Jetzt zusätzlich: `pending_transcripts`, `sessions`, `vosk_command_queue`, `audio_chunks`, `current_operator`, `last_rfid_uid`, `peers`. Sendet auch `operator_changed`-Broadcast für UI-Logout.
  - **Surface `backend/app.py`**: `state.peers` wurde übersehen → alte BAT-Marker blieben nach Reset auf der Karte. Jetzt mit drin.
- **1.3 Triage aus Role 0 entfernt** (User-Wunsch: Triage erfolgt erst in Rettungsstation):
  - `voice_set_triage()` und `update_patient()` blocken Triage-Updates wenn `current_role == "phase0"`. TTS-Hinweis: „Triage erfolgt erst in der Rettungsstation".
  - Frontend: Triage-Buttons im Fahrzeug-Modus werden nur gerendert wenn `p.current_role !== 'phase0'` (siehe `templates/index.html` Patient-Card-Render).
  - Hilfetext im Sprachbefehl-Guide angepasst.
- **1.4 `_split_sentences` Aufnahme-Bug**: Kurze End-Fragmente (< 15 chars wie „Aufnahme") werden jetzt auch dann ans vorherige angehängt wenn das vorherige bereits ≥ 30 chars hat. Verhindert dass „Aufnahme" als 4. Patient rausfällt.

### Phase 2 — Segmenter-Migration (`34aafba` + Rollback `d13ea38`)

- **2.1 `_call_ollama` `num_ctx` Parameter eingebaut**, default 2048, lesbar aus `config.json` als `ollama.num_ctx`. Auch im `/api/config` Hot-Reload-Pfad.
- **2.2 + 2.5 Modell-Wechsel auf qwen2.5:3b versucht und gerollback**:
  - 3B startete mit num_ctx=2048 (Hybrid 40% CPU / 60% GPU, 2.6 GB), aber Whisper-Modell konnte danach nicht mehr geladen werden (`whisper_init_from_file_with_params_no_state` failed → `WARNUNG: Modell konnte nicht geladen werden!`). Free RAM nur 110 MB nach 3B-Load — kein 1.2 GB zusammenhängender Block für Whisper.
  - Rollback: `config.json` wieder auf `qwen2.5:1.5b` (`num_ctx=2048` bleibt), `safir-start.sh` Preload zurück auf 1.5b.
  - **Lessons-Learned-Kommentar in `safir-start.sh`** dokumentiert den Befund und die kritische `num_ctx`-Setting.
- **2.3 Post-Merge 3 in `segment_transcript_to_patients`**: Defense-in-Depth gegen LLM-Halluzinationen. Jetson `app.py` ~Z. 1890. Segmente ohne explizites Patient-Start-Signal UND ohne Rang/Patient-Marker werden ans vorherige gemerged. Fängt z.B. „Wir müssten Blutkonserven bereithalten" als Fortsetzung von Meyer ab.
- **`scripts/ab_test_segmenter.py`** als Tool für künftige Modell-Vergleiche. Stoppt safir nicht, callt Ollama direkt mit beiden Modellen + identischen Optionen.

### Phase 3 — Demo-Story Refactor (`e638323`)

- **3.1 Simulation-Button entfernt** (sowohl Surface backend `/api/simulation/reset` als auch Jetson Stub und Frontend `role1StartSimulation`/`role1ResetSimulation`/`role1FetchRoute`). `role1ArrivedBats` als leeres Object behalten für die neue Rückfahrt-Animation.
- **3.2 + 3.3 BAT-Standort-Setting + Rückfahrt zur Rettungsstation**:
  - Refactor des früheren `GPS_ROUTE`-Loops (10s, hardcoded) zu `bat_position_loop()` mit `_bat_pos_state`-Maschine. 40 Steps × 1.5s = 60 s Gesamtdauer.
  - **Bonn-Presets** (`BAT_POSITION_PRESETS`): Beuel, Hardthöhe, Bad Godesberg, Endenich, Rheinaue.
  - **Rettungsstation-Koordinaten** in `config.json` als `rescue_station: {lat, lon, label}`, default 50.7374 / 7.0982 (Bonn).
  - **Neue API-Endpoints** auf dem Jetson:
    - `GET /api/bat/position/presets`
    - `GET /api/bat/position`
    - `POST /api/bat/position/set` (`{preset_id}` oder `{lat, lon}`)
    - `POST /api/bat/return-to-station`
    - `POST /api/bat/return-to-station/stop`
  - **Frontend**: Standort-Dropdown + Rückfahrt-Button im Fahrzeug-Modus. Lädt Presets beim ersten Wechsel in den Fahrzeug-Modus.
  - **Voice-Command** „rückfahrt zur rettungsstation" mit vielen Variants in `config.json`. Fällt auf Hardthöhe-Preset zurück wenn vorher kein Standort gesetzt.
  - Auto-Start beim Patient-Senden entfernt (war Demo-Zufall in der alten Version).
- **3.4 Testdaten-Generator** (Jetson + Surface, beide mit `/api/data/test-generate`):
  - Jetson erzeugt 6 realistische Test-Patienten in verschiedenen Status (registered/analyzed/synced, Phase0/Role1, mit/ohne Triage).
  - Surface erzeugt 6 Patienten alle synced+role1+triage, plus einen Test-BAT auf der Karte bei Bonn-Endenich.
  - Patient-IDs alle mit `TEST-` Prefix.
  - Frontend-Button in Settings → System neben dem Reset-Button.

### Phase 4.1 — RFID-Write-Bug (`d878b48`)

- **Problem**: User-Beschwerde „Karten werden nicht richtig überschrieben — alte Daten bleiben drauf". `rc522_write_patient_to_card` meldete `success=True`, aber Sektor 2 (Block 8/9/10 = Name + Mechanismus) blieb unverändert.
- **Diagnose**: `scripts/rfid_write_diag.py` — schreibt Test-Patient + liest sofort wieder + vergleicht hex. Mit TTS-Audio-Prompts ("Jetzt Karte auflegen") damit User nicht den Bildschirm beobachten muss.
- **Root Cause**: Nach erfolgreichem Sektor-1-Auth + Operations sind RC522-Register und Karten-Crypto1-State so verwoben, dass weder REQA, WUPA noch `_rc522_stop_crypto` allein die Karte für Sektor-2-Auth zurückholen. `_rc522_auth` meldete fälschlich `True` (wegen Status2-Bit vom alten Sektor 1), der Write ging mit dem alten Crypto1-Sektor-1-State, Karte lehnte still ab, Verify-Read sah „alte Daten" ohne Mismatch zu erkennen.
- **Fix in `shared/rfid.py`**: Vor jedem neuen Sektor-Auth einen kompletten **Hardware-Reset des RC522** (`_rc522_stop_crypto` + `_rc522_halt` + `rc522_init()` + neue REQA + Anticoll + Select). Latenz pro Karte: ~0.65s → ~1.04s. Auch zusätzliche `log.info`-Logs für Sektor-Auth und Block-Write hinzugefügt.
- **`_PICC_WUPA = 0x52`** als Konstante hinzugefügt (war Zwischenversuch).
- **Live-Test verifiziert**: `diag exit: 0`, alle Block 5/6/8/9/10 stimmen exakt mit erwarteten Bytes überein.

### Phase 4.2 — OLED NETZWERK-Seite (`a17e7aa`)

- **Vierte Page** zwischen `models` und `operator`: `PAGES = ["models", "network", "operator", "patient"]`.
- **`_render_network` Methode** in `jetson/oled.py` mit FONT_LG (13 px) und FONT_MD (11 px), nicht FONT_SM (9 px) wie alte Diagnose-Pages. Layout:
  - Z. 14 (FONT_LG): SSID oder „WLAN OK"/„OHNE WLAN"
  - Z. 30 (FONT_MD): „IP 192.168.x.y"
  - Z. 44 (FONT_MD): „Tailnet ON/OFF/--"
  - Z. 56 invertierter Bottom-Bar: „ALLES OK" (wenn WLAN+Tailscale+Backend) oder „WARN: WLAN TS BE"
- **Backend-Polling**: 4 neue Helper in `app.py`:
  - `_get_wifi_status()` via `nmcli` + `ip addr show wlan0`
  - `_get_eth_ip()` via `ip addr show eth0`
  - `_get_tailscale_state()` via `tailscale status --json` → BackendState
  - `_get_tailscale_ip()` (existierte schon) via `tailscale ip -4`
- `_oled_update_loop` befüllt `oled_menu.network_info` alle 2 s mit allen Feldern (`wifi_state`, `wifi_ssid`, `wifi_ip`, `eth_ip`, `tailscale`, `tailscale_ip`, `backend_ok`).
- **User-Verifikation am Jetson**: NETZWERK-Seite ist gut lesbar (User-Antwort auf AskUserQuestion).

### Phase 6 — Export & Interoperabilität (`1a397dd` + `7e987ea`)

- **`shared/exports.py`** (NEU, ~560 Zeilen): Zentrale Export-Logik, von beiden Backends importiert:
  - `generate_json(patients, device_id, unit_name) -> bytes` — schema-versioniert
  - `generate_xml(patients, device_id, unit_name) -> bytes` — rekursiv für verschachtelte Dicts/Listen
  - `generate_docx(patients, device_id, unit_name, output_dir) -> Path` — via python-docx
  - `generate_pdf(patients, device_id, unit_name, output_dir) -> Path` — via reportlab, Bundeswehr-Olive-Styling
  - Lazy-Imports für python-docx / reportlab — ImportError wird mit klarem Hinweis an den Caller gereicht.

- **reportlab in Jetson-Venv installiert**: `pip install reportlab` (4.4.10). Im Surface-Venv noch NICHT — beim ersten PDF-Export-Versuch im Surface kommt ein `{"error":"reportlab nicht installiert", ...}`-JSON.

- **4 Endpoints auf beiden Backends** (Jetson `app.py` + Surface `backend/app.py`):
  - `GET /api/export/json/all`
  - `GET /api/export/xml/all`
  - `POST /api/export/docx/all`
  - `POST /api/export/pdf/all`

- **Frontend `templates/index.html` Settings → System**: Neue Karte "Patientendatenbank exportieren" mit 4 Buttons. `exportPatientsFormat(fmt)` JS-Funktion: GET für JSON/XML (direkt `<a href>`-Download), POST für DOCX/PDF (fetch + Blob + URL.createObjectURL). Content-Disposition-Filename wird aus Response ausgelesen.

- **Live verifiziert auf Jetson** mit 6 Test-Patienten:
  - JSON: 8738 bytes, `application/json`, schema-version 1.0
  - XML: 9260 bytes, well-formed, verschachtelt
  - DOCX: 38 KB, Microsoft OOXML (file-command bestätigt)
  - PDF: 11 KB, **7 Seiten** (1 Übersicht + 6 Patienten-Details)
  - Alle HTTP 200, korrekte Content-Type-Header.

- **Refactor-Commit** `7e987ea` zieht 442 Zeilen inline aus `app.py` raus in `shared/exports.py`. Jetson läuft identisch, Surface-Backend bekommt die Endpoints via `from shared import exports` (mit sys.path-Fix für das Repo-Root).

### Phase 5 — 9-Liner MEDEVAC Voice-Recognition (`9dd4411` + `dbf86a3`)

- **`docs/nine-liner-template.md`** (NEU): Laminierbares A5-Dokument mit allen 9 NATO-Zeilen, Buchstaben-Codes, Kurz-Referenz und **Beispiel-Diktat** für Messebesucher.
- **`NINE_LINER_PROMPT`** mit Halluzinations-Schutz (2 Beispiele: Nicht-9-Liner → alle leer; echter 9-Liner → 9 Codes).
- **`extract_nine_liner(transcript) -> dict`**: garantiert alle 9 Felder.
- **`looks_like_nine_liner(transcript) -> bool`**: Auto-Detect via 20+ Keywords, greift bei ≥2 Treffern (false-positive-safe).
- **`_segment_and_create_patients()` erweitert** um `is_nine_liner`-Branch: Wenn aktiv, skip Segmenter → direkt `extract_nine_liner` → einzelner Patient mit `template_type="9liner"`.
- **`state.next_recording_is_nine_liner`** Flag + Voice-Command `nine_liner_mode` (7 Trigger in config.json: neun liner, medevac, etc.). Beim Recording-Stop wird Flag ans pending_transcript übertragen.
- **`/api/test/nine-liner`** POST Endpoint für Proof-of-Concept-Tests ohne Recording.
- **`template_type`**-Feld im PATIENT_SCHEMA, wird automatisch via TRANSFER_SCHEMA ans Surface übertragen.
- **UI**: 9-Liner-Card im Role1-Detail-Modal (Grid) + kompakter Monospace-Block im Jetson Phase0-Patient-Card + "9-Liner"-Badge in der Summary.
- **Live verifiziert**: Echter 9-Liner → 9/9 Felder, Patient-Diktat → 0/9 (keine Halluzination), Auto-Detect unterscheidet korrekt. Latenz ~11 s mit qwen2.5:1.5b.

### Phase 4.3 — Audio Multi-Output (`5e1535a`)

- **`shared/tts.py`**:
  - `_output_devices: list[int]` (statt singular) — alle passenden Speaker-Devices werden parallel bespielt.
  - `_is_speaker_device()` Filter (USB/HDA/Jabra/Logitech/Plantronics/Creative/etc.), schließt HDMI/Loopback/dmix/iec958/etc. aus, plus Duplikat-Filter.
  - `_speak_internal`: Pro Device einen Thread mit eigenem Sample-Rate-Picking + Resample (USB-Headset 48 kHz vs. C-Media 44.1 kHz). `threading.Thread.join()` syncronisiert.
  - `rescan_devices()`, `get_output_device_count()` als reusable Helpers.
- **`app.py` Audio-Hotplug-Watcher**:
  - `_audio_device_watcher_loop()`: Background-Task, prüft alle 3 s die `/proc/asound/cards`-MD5-Signatur, triggert Refresh bei Änderung.
  - `_refresh_audio_devices_async()`: Stoppt Vosk-Stream → `sd._terminate` → `importlib.reload(sounddevice)` → `tts.rescan_devices()` → Vosk-Stream wieder hochfahren. Im Executor damit der Event-Loop nicht blockiert.
  - **OLED-Status + TTS-Ansage** je nach Befund:
    - new > old → "AUDIO + N Lautsprecher" / „N Audiogerate aktiv"
    - new < old → "AUDIO - N Lautsprecher" / „Audiogerat entfernt"
    - sig change aber gleiche Anzahl → "AUDIO NEU, SAFIR neu starten" / „Audiogerat erkannt. Service neu starten."
- **Verifizierung am Jetson** mit Jabra SPEAK 510 + C-Media USB Audio Device:
  - ✅ Service-Start mit beiden: `TTS: 2 Speaker-Device(s) — Multi-Output`
  - ✅ Abziehen während Betrieb: `Hot-Reload 2 → 1`, OLED + TTS auf verbleibendem Jabra
  - ⚠ **Einstecken während Betrieb** (Limitation): OLED zeigt „AUDIO NEU", TTS sagt „Service neu starten", aber **Multi-Output greift erst nach `systemctl restart safir`**. Linux/PortAudio cached die ALSA-Geräteliste in einem internen Pool, den auch `sd._terminate; sd._initialize` und `importlib.reload(sounddevice)` nicht zur Laufzeit aufgelöst kriegen.
- **`scripts/list_audio_devices.py`**: Standalone-Diagnose-Tool das alle PortAudio-Devices listet.

---

## Bekannte Limitations

1. **Qwen 2.5 3B passt nicht parallel zu Whisper auf 7.4 GB Unified Memory.** Auch mit `num_ctx=2048` reicht der zusammenhängende RAM-Block nicht für Whispers 1.2 GB Modell. Wir bleiben bei 1.5b + Code-Workaround. Dokumentiert in `scripts/safir-start.sh` Kommentar.
2. **PortAudio Hot-Plug auf Linux**: Neu eingestecktes USB-Audio wird vom `/proc/asound/cards`-Watcher erkannt, OLED + TTS reagieren, aber PortAudio's interner Cache liefert das neue Device erst nach Service-Restart. Workaround: User-Notification "SAFIR neu starten" beim Insert.
3. **1.5b Determinismus**: Auch mit `temperature=0.0` und `top_k=1` ist Qwen 2.5 1.5b nicht 100% deterministisch zwischen Service-Restarts. Selber Input → manchmal andere Boundary-Liste. Post-Merge 3 fängt das ab.
4. **Tailscale-SSH-Auth-Cache läuft alle ~20 Minuten ab**. Browser-Klick auf `https://login.tailscale.com/a/...` jeweils nötig wenn neuer SSH-Connect aus einer kalten Session. Workaround für AFCEA: Tailscale-SSH auf dem Jetson deaktivieren oder `checkPeriod` in der ACL verlängern (siehe Plan Phase 7+ Open Decisions).

## Hardware-Setup (Stand 15.04.)

- **Jetson Orin Nano Super DevKit** mit Headless-Boot (`multi-user.target`). Boot-RAM ~6.7 GB available, Service-RAM ~3.5 GB used.
- **Audio**: Jabra SPEAK 510 USB als Mikro+Speaker (default), beim Audio-Test war zusätzlich ein C-Media USB Audio Device angeschlossen. Beide sind heute Abend noch dran (User-Bestätigung beim Hotplug-Test).
- **RFID**: RC522 Reader mit MIFARE Classic 1K Karten. Karten haben Standard-Key A (`FFFFFFFFFFFF`) auf Sektor 1 und 2.
- **OLED**: SSD1306 128×64 auf I2C Bus 7, Adresse 0x3C.
- **Tailscale**: beide Geräte aktiv, Direct-Connection meistens (`direct 192.168.178.152:41641` im Heim-Netz).

---

### Phase 7 — Encryption-Story + Use-Case-Vision-Page (`4a804ca`)

- **`docs/security-architecture.md`** (NEU, 234 Zeilen): Dreischichtige Sicherheits-Architektur-Dokumentation:
  - Schicht 1: WireGuard-Tunnel mit Curve25519 (Key-Agreement), ChaCha20 (Payload-Encryption), Poly1305 (MAC), Blake2s (Hashing). Re-Keying alle 2 min / 60 MB.
  - Schicht 2: Tailscale als Identity-Management, Zero-Trust (Tailscale Inc. sieht nur Public Keys, keine Payloads). NAT-Traversal, ACL.
  - Schicht 3: Anwendungs-Authentifizierung (UUID-Patient-IDs, RFID-UID-Pointer).
  - 3 Angriffs-Szenarien: WLAN-Sniffing, verlorener Jetson, NATO-Secret-Einsatz.
  - Transparente Limits: keine App-Layer-Crypto, keine Hardware-Attestation, keine TPM, keine BSI-Freigabe.
  - 5 Talking Points für AFCEA-Messebesucher + Appendix mit aktuellem Demo-Status.
- **Vision-Page** in `templates/index.html` (~130 CSS + ~180 HTML Zeilen):
  - Hero-Section: "Mehr als Rettungskette"
  - 4 Prinzip-Karten: Voice-First, Edge/Offline, Hardware-Integriert, E2E-Verschlüsselt
  - 6 Anwendungsbereich-Karten: Feuerwehr, Polizei, THW, Logistik, zivile Sanitätsdienste, Forschung
  - Pro Use-Case: Hardware-Anpassung, Modifikationen, Integration
- **Settings "Sicherheit"-Section**: ASCII-Architekturdiagramm + 5 Talking Points + Kryptographie-Primitives-Tabelle (Curve25519/ChaCha20/Poly1305/Blake2s mit RFC-Referenzen) + Transparente-Limits-Karte.
- **`config.json` Navigation**: Neuer Eintrag `vision` zwischen Dokumente und Einstellungen.
- **Settings-Sidebar**: Neuer Eintrag "Sicherheit" (🔑).
- **Live verifiziert** via Chrome auf http://jetson-orin:8080/: Vision-Page rendert alle 6 Use-Cases korrekt, Sicherheits-Section zeigt Diagramm + Talking Points + Tabelle lesbar.

---

## Nächste Aktion: Phase 8 — Remote Audio MVP (~16 h, riskant)

- Browser MediaRecorder (`audio/webm;codecs=opus`) → WebSocket Audio-Chunks → Jetson decode (`pyav`/`ffmpeg-python`) → Whisper. Fallback auf lokales Mikro.
- Ziel: Messebesucher kann auf seinem Handy/Tablet sprechen, Jetson transkribiert (statt lokales Mikro).

## Phase 9 — Final Polish, Demo-Run, Stress-Test (~6 h)

- 5–10 Diktate hintereinander ohne Service-Restart, `tegrastats` parallel, kein OOM erlaubt.
- Latenz-Targets: Diktat-Stopp → Whisper < 5 s, Analyse → Patient < 15 s, Sync zum Surface < 2 s.
- Backup: Git-Tag `pre-demo`, USB-Stick mit Repo-Snapshot.

---

## Open Decisions (User-Entscheidung steht aus)

1. **Tailscale-SSH-Cache verlängern oder deaktivieren?** Aktuell läuft alle ~20 min ab. Für AFCEA-Demo am besten `sudo tailscale set --ssh=false` auf dem Jetson — der Public Key in `~/.ssh/authorized_keys` reicht für SSH-Auth ohne Browser-Flow.
2. **Bundeswehr-Theme**: Sind die im CSS schon definierten Farben final, oder gibt es ein offizielles CGI-Bundeswehr-Branding-Doc?
3. **Phase 8 Browser-Codec**: opus (modern, klein) oder wav (einfach, groß)?

---

## Wichtige Files (Übersicht für Quick-Reference)

| Datei | Was | Phasen |
|---|---|---|
| `app.py` (Repo-Root) | **Jetson Hauptcode** (~4400 Zeilen). FastAPI + Whisper + Vosk + Ollama + Hardware-Integration. Nur auf dem Jetson lauffähig — der Surface-Spiegel ist nur für Editieren. | 1.2, 1.3, 1.4, 2.1–2.5, 3.2, 3.3, 3.4, 4.2, 4.3 |
| `backend/app.py` | **Surface Backend** (~900 Zeilen). FastAPI Leitstelle mit Lagekarte. Hier läuft `preview_start` lokal. | 1.2, 3.1, 3.4 |
| `templates/index.html` (Repo-Root) | **Gemeinsames Frontend**, beide Backends servieren das. ~5000 Zeilen, alles inline (kein Build-System). | 1.1, 1.3, 3.1, 3.4, 4.3-OLED-indirect |
| `shared/rfid.py` | RC522 Bit-Bang SPI + MIFARE Classic Read/Write. | 4.1 |
| `shared/tts.py` | Piper TTS + Multi-Output Audio | 4.3 |
| `shared/models.py` | `PATIENT_SCHEMA`, `TRANSFER_SCHEMA`, Enums | (Phase 5 Read) |
| `jetson/oled.py` | SSD1306 OLED-Menü, Pages, Render | 4.2 |
| `config.json` (Repo-Root) | Jetson-Config: voice_commands, ollama, backend, BAT_POSITION, rescue_station, voice_triggers | 2.2, 3.2, 3.3 |
| `backend/config.json` | Surface-Config: device_id, unit_name, role | (lokaler Override für Surface) |
| `scripts/safir-start.sh` | systemd-Boot-Skript, Ollama-Preload, Whisper-Start | 2.5 (Lessons-Learned) |
| `scripts/rfid_write_diag.py` | Standalone RFID Diagnose-Tool mit TTS-Prompts | 4.1 |
| `scripts/ab_test_segmenter.py` | A/B-Test-Tool für Modell-Vergleich | 2 |
| `scripts/list_audio_devices.py` | Listet alle PortAudio Output-Devices | 4.3 |
| `docs/PROGRESS.md` | **DIESE DATEI** — Single-Source-of-Truth für Session-Continuity | (alle) |
| `docs/surface-diagnose-setup.md` | SSH-Setup-Guide vom Jetson für den Surface | (Setup) |

---

## Wenn der User sagt „weiter mit dem Plan"

1. Diese Datei (`docs/PROGRESS.md`) lesen
2. TodoWrite-Liste neu anlegen mit Phase 1–7 als `completed`, Phase 8 als `in_progress`, Phase 9 als `pending`.
3. **Phase 8** starten — drei Teilschritte:
   - **8.1 Browser MediaRecorder**: `templates/index.html` um "Mikrofon-Modus"-Toggle erweitern (lokal vs. Browser). Bei Browser-Modus: `navigator.mediaDevices.getUserMedia({audio: true})` → `MediaRecorder` mit `audio/webm;codecs=opus`, 250-ms-Chunks via `ondataavailable`.
   - **8.2 WebSocket-Streaming**: Chunks als `{type: "audio_chunk", seq, data: base64}` an WebSocket `/ws` senden. Serverseitig in `_broadcast_task` neuen Handler `_handle_audio_chunk()`.
   - **8.3 Jetson Decode + Whisper**: pyav/ffmpeg-python für opus→PCM, Buffer bis N Sekunden, dann an Whisper-Pipeline. Fallback: Wenn keine aktive Browser-Session, nutze `arecord`/lokales Mikro wie bisher.
   - Voice-Command zum Umschalten: "Browser Mikrofon" / "Lokales Mikrofon".
4. Commit + Push + Jetson pull.
5. PROGRESS.md updaten mit Phase 8 als `completed` oder `nice-to-have` (wenn's zu riskant wird), Phase 9 als `in_progress`.

**Bei Unsicherheit** über Code-Stellen oder Architektur: **erst grep/read im Repo**, nicht annehmen. Im Zweifel den User fragen.

**Wichtig für Phase 8**: Das ist der riskanteste Phase-Block. Wenn die Latenz/Qualität nicht reicht, rolle zurück und verkaufe es als "konzeptionell vorhanden, wird in V2 vollständig implementiert". Nicht die ganze Messe gefährden für ein nice-to-have.
