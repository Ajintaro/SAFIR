# SAFIR — Sprachgestützte Assistenz für Informationserfassung in der Rettungskette

KI-gestütztes Dokumentationssystem entlang der Rettungskette der Bundeswehr.
Auftraggeber: **CGI Deutschland**. Zielgruppe: **Bundeswehr Sanitätsdienst**.

> **Demo-Termin:** AFCEA Bonn — Mittwoch 29.04.2026
> **Stand:** Stable, eingefroren (`docs/PROGRESS.md` Session 26.04.2026)

## Hardware & Rollenverteilung

```
Jetson (BAT / Phase 0)              Surface (Leitstelle / Role 1)
━━━━━━━━━━━━━━━━━━━━━━━            ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Spracheingabe + Whisper.cpp ───>    Taktische Lagekarte (Leaflet)
9-Liner MEDEVAC                      Patientendatenbank + Triage
Vosk-Sprachbefehle                   KI-Review (Gemma 4)
Gemma 3 4B Segmenter                 4 Tactical/Medical Exporte
Piper TTS · OLED · RFID
```

| Gerät | Hardware | Rolle | KI-Modelle |
|---|---|---|---|
| **Jetson Orin Nano** | 7.4 GB Unified Memory, CUDA 12.6 | **Phase 0 — Feldgerät** | Whisper small (GPU) · Gemma 3 4B (`gemma3:4b`, permanent VRAM) · Vosk (CPU) · Piper TTS (CPU) |
| **MS Surface** | RTX 4060 / 8 GB VRAM | **Role 1 — Leitstelle** | Gemma 4 E4B (`gemma4:e4b`, on-demand für KI-Review) |

### Netzwerk (Tailscale)

| Gerät | Tailscale-Hostname | Tailscale-IP | HTTPS-URL (Mesh) |
|---|---|---|---|
| Jetson Orin | `jetson-orin` | 100.126.179.27 | https://jetson-orin.tail0fe60f.ts.net/ |
| MS Surface | `ai-station` | 100.101.80.64 | https://ai-station.tail0fe60f.ts.net/ |

HTTPS via `tailscale serve` mit echtem Let's-Encrypt-Cert (grünes Schloss, mesh-intern).
HTTP `localhost:8080` läuft parallel weiter für lokale Diagnose.

## Rettungskette der Bundeswehr

| Stufe | Bezeichnung | Status in SAFIR |
|---|---|---|
| **Phase 0** | Feldgerät (BAT) | ✅ Sprachgestützte Dokumentation, 9-Liner, RFID, Multi-Patient-Diktat |
| **Role 1** | Rettungsstation | ✅ Lagekarte, Triage, KI-Review, Patientendatenbank, Export |
| Role 2 | Rettungszentrum | V2-Roadmap |
| Role 3 | Einsatzlazarett | V2-Roadmap |
| Role 4 | BW-Krankenhaus | V2-Roadmap |

## Tech Stack

- Python 3.10+ · FastAPI · WebSocket · Jinja2 (kein Build-System, alles inline)
- Whisper.cpp (Jetson, GPU) · Vosk (Jetson, CPU mit `SetWords(True)`) · Piper TTS (Jetson, CPU)
- Ollama: `gemma3:4b` (Jetson) + `gemma4:e4b` (Surface)
- Tailscale Mesh-VPN (WireGuard, ChaCha20-Poly1305) mit HTTPS-Serve (LE-Cert)
- python-docx + reportlab für DOCX/PDF · `shared/sitaware.py` für CoT/NVG/MEDEVAC-9-Liner/HL7-FHIR-Exports

## Projektstruktur

```
SAFIR/
├── app.py                    # Jetson-Hauptcode (FastAPI + Whisper + Vosk + Ollama + Hardware)
├── backend/                  # Surface-Backend
│   ├── app.py                # Leitstelle (Lagekarte, KI-Review, Export)
│   ├── start_backend.bat     # User-Selbstbedienung Start (auf Desktop)
│   ├── stop_backend.bat      # User-Selbstbedienung Stop
│   └── config.json
├── shared/                   # Geteilte Module
│   ├── models.py             # PATIENT_SCHEMA, TRANSFER_SCHEMA
│   ├── tts.py                # Piper TTS Multi-Output
│   ├── rfid.py               # RC522 Bit-Bang + MIFARE Read/Write (3-Stufen-Recovery)
│   ├── exports.py            # DOCX/PDF/JSON/XML
│   ├── sitaware.py           # CoT/NVG/MEDEVAC-9-Liner/HL7-FHIR (echte Standards)
│   └── version.py            # Single Source of Truth für Version + Build-Hash
├── jetson/
│   ├── oled.py               # SSD1306 OLED-Menü (4 Pages, Submenu-Scroll)
│   └── hardware.py           # GPIO-Taster, RfidService, LEDs
├── templates/
│   ├── index.html            # Gemeinsames Dashboard (5000+ Zeilen)
│   └── handbook.html         # Handbuch (12 Sektionen)
├── docs/
│   ├── PROGRESS.md           # Session-Continuity, immer zuerst lesen
│   ├── messe-hardening-plan.md
│   ├── demo-disaster-recovery.md
│   ├── security-architecture.md
│   ├── nine-liner-template.md
│   └── vision-mocks/         # 6 Use-Case-HTMLs (Polizei, Feuerwehr, …)
├── CLAUDE.md                 # Projekt-Kontext für Claude Code
├── SESSION-HANDOVER.md       # Account-Wechsel-Notizen
└── config.json               # Jetson-Config: voice_commands, ollama, BAT-Presets
```

## Schnellstart

### Jetson (Feldgerät — autostart)

Boot ist headless, `safir.service` läuft automatisch. Manueller Restart:
```bash
sudo systemctl restart safir.service
```
Logs:
```bash
sudo journalctl -u safir.service -f
```

### Surface (Leitstelle — Doppelklick)

Doppelklick auf `start_backend.bat` (Desktop). Backend läuft in eigenem cmd-Fenster, Dashboard auf https://ai-station.tail0fe60f.ts.net/.

Zum Stoppen: `stop_backend.bat` (Doppelklick).

## Demo-Szenarien

In Settings → System → Demo-Szenarien stehen 4 Presets bereit:

- **Standard-Mix** — 2 analysierte Patienten (warten auf Melden) + 2 schon gemeldete (auf Surface) + 1 langes Multi-Patient-Diktat (4 Verwundete am Stück) zum Live-Analysieren
- **Massenanfall** — 10 Patienten in Role 1, Triage offen
- **9-Liner MEDEVAC** — 1 Patient mit vollständig ausgefülltem NATO-9-Liner
- **Role-1-Übergabe** — 2 schon gemeldete Patienten in Role 1

## Doku-Quellen für Entwickler

- `docs/PROGRESS.md` — Session-Continuity + alle Phase-Status
- `CLAUDE.md` — High-Level-Kontext für AI-Agenten
- `docs/security-architecture.md` — Verschlüsselung & Talking Points
- `docs/demo-disaster-recovery.md` — 7 Notfall-Rezepte für Demo-Tag

---
*CGI Deutschland — SAFIR Projekt*
