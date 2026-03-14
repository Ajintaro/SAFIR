# SAFIR — Sanitäts-Assistenz für Feld-Informations-Reporting

KI-gestütztes Dokumentationssystem entlang der Rettungskette der Bundeswehr.

## Hardware & Rollenverteilung

```
Jetson (Feld)          Surface (Role 1)        Alienware (Role 2/3)     MacBook (Leitstelle)
━━━━━━━━━━━━━         ━━━━━━━━━━━━━━━         ━━━━━━━━━━━━━━━━━━       ━━━━━━━━━━━━━━━━━━
Spracheingabe    ───>  Taktische Karte    ───>  KI-Analyse          ───> Gesamtübersicht
9-Liner               Triage-Empfang           Whisper large-v3         Statistik
Whisper small          Qwen2.5-7B (opt.)       pyannote Diarization    Alle Rollen im Blick
Vosk Sprachbefehle    Eingehende Meldungen     Qwen2.5-32B
                                                Übergabeberichte
```

| Gerät | GPU / VRAM | Rolle | Aufgabe |
|---|---|---|---|
| **Jetson Orin Nano** | 7.4 GB shared | **Phase 0** — Feldgerät | Spracheingabe, Whisper small, Vosk, 9-Liner Extraktion (Qwen2.5-1.5B) |
| **MS Surface** | RTX 4060, 8 GB | **Role 1** — Rettungsstation | Taktische Karte, eintreffende Meldungen, Triage-Empfang, optional Qwen2.5-7B |
| **Alienware** | RTX 5090, 24 GB | **Role 2/3** — Rettungszentrum | Whisper large-v3 (~3 GB) + pyannote Diarization (~2 GB) + Qwen2.5-32B (~18 GB), Übergabeberichte, OP-Vorbereitung |
| **MacBook** | kein GPU | **Leitstelle / Role 4** | Reines Dashboard, Gesamtübersicht aller Rollen, Statistik |

### Warum diese Verteilung?

- **Alienware (Role 2/3)** braucht die meiste Compute-Power: Whisper large + pyannote + Qwen2.5-32B = ~23 GB VRAM → passt nur auf die RTX 5090
- **Surface (Role 1)** empfängt und sichtet — primär Dashboard + leichte Triage-Unterstützung, optional kleines LLM
- **MacBook** zeigt nur Dashboards an, keine KI lokal nötig

### Netzwerk (Tailscale)

Alle Geräte sind über Tailscale verbunden. Jedes Gerät hat eine feste Tailscale-IP.

| Gerät | Tailscale-Hostname | Rolle |
|---|---|---|
| Jetson Orin | `jetson-orin` | Phase 0 |
| MS Surface | *einzurichten* | Role 1 |
| Alienware | *einzurichten* | Role 2/3 |
| MacBook | `de-d656g021f2` | Leitstelle |

## Rettungskette der Bundeswehr

| Stufe | Bezeichnung | KI-Unterstützung |
|-------|------------|------------------|
| **Phase 0** | Selbst-/Kameradenhilfe | Sprachgesteuerte Dokumentation (Jetson) |
| **Role 1** | Rettungsstation | Taktische Karte, Triage-Empfang, Eingehende Meldungen |
| **Role 2** | Rettungszentrum | Automatische Übergabeberichte, Triage-Unterstützung, Speaker Diarization |
| **Role 3** | Einsatzlazarett | Patientenakte, Diagnose-Zusammenfassung, OP-Vorbereitung |
| **Role 4** | BW-Krankenhaus | Auswertung, Statistik, Rehabilitation-Tracking |

## Projektstruktur

```
safir/
├── app.py                # Jetson Haupt-App (Spracheingabe, 9-Liner)
├── san_transcribe.py     # Standalone Transkriptions-Tool
├── config.json           # Voice Commands, Whisper/Ollama Config
├── jetson/               # Feldgerät (NVIDIA Jetson Orin Nano)
│   ├── app.py            # FastAPI Backend
│   ├── templates/        # Web-Dashboard
│   └── requirements.txt
├── backend/              # Leitstelle / Role 1+ (Surface, Alienware, MacBook)
│   ├── app.py            # FastAPI Backend
│   ├── templates/        # Web-Dashboard (taktische Karte)
│   └── requirements.txt
├── shared/               # Gemeinsame Datenmodelle
│   ├── models.py         # Patient, Transfer, Triage Schemas
│   ├── tts.py            # Piper TTS (deutsche Sprachausgabe)
│   └── rfid.py           # RFID-Simulation + Patienten-ID
└── templates/            # Jetson Dashboard Template
```

## Schnellstart

### Jetson (Feldgerät)
```bash
cd jetson
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# Whisper.cpp und Vosk-Modell separat installieren
python3 -m uvicorn app:app --host 0.0.0.0 --port 8080
```

### Surface / Backend (Role 1)
```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python3 -m uvicorn app:app --host 0.0.0.0 --port 8080
```

### Alienware (Role 2/3)
```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# Ollama mit Qwen2.5-32B installieren
ollama pull qwen2.5:32b
python3 -m uvicorn app:app --host 0.0.0.0 --port 8080
```

## Demo

Für die AFCEA Bonn / Bundeswehr-Delegation — **19.03.2026**

---
*CGI Deutschland — SAFIR Projekt*
