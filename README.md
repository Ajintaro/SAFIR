# SAFIR — Sanitäts-Assistenz für Feld-Informations-Reporting

KI-gestütztes Dokumentationssystem entlang der Rettungskette der Bundeswehr.

## Architektur

```
┌──────────────────────┐            ┌─────────────────────────────┐
│   JETSON ORIN NANO    │   ─────>  │    ALIENWARE + RTX 5090     │
│   (Feldgerät)         │   Daten   │    (Leitstelle / Backend)   │
├──────────────────────┤            ├─────────────────────────────┤
│ Phase 0 / Role 1     │            │ Role 1–4 Verwaltung         │
│ • Spracheingabe       │            │ • Speaker Diarization       │
│ • Whisper small (GPU) │            │ • Whisper large-v3 (GPU)    │
│ • 9-Liner Extraktion  │            │ • LLM Qwen2.5-32B (GPU)    │
│ • Vosk Sprachbefehle  │            │ • Patientenakte komplett    │
│ • Echtzeit-Dashboard  │            │ • Übergabeberichte          │
│                       │            │ • Kapazitätsmanagement      │
│ 8GB shared RAM        │            │ • Auswertung & Statistik    │
│ Feld-tauglich         │            │ 24GB VRAM — volle Power     │
└──────────────────────┘            └─────────────────────────────┘
```

## Rettungskette der Bundeswehr

| Stufe | Bezeichnung | KI-Unterstützung |
|-------|------------|------------------|
| **Phase 0** | Selbst-/Kameradenhilfe | Sprachgesteuerte Dokumentation (Jetson) |
| **Role 1** | Rettungsstation | 9-Liner, TCCC Card, Erstbefund per Sprache |
| **Role 2** | Rettungszentrum | Automatische Übergabeberichte, Triage-Unterstützung |
| **Role 3** | Einsatzlazarett | Patientenakte, Diagnose-Zusammenfassung, OP-Vorbereitung |
| **Role 4** | BW-Krankenhaus | Auswertung, Statistik, Rehabilitation-Tracking |

## Projektstruktur

```
safir/
├── jetson/              # Feldgerät (NVIDIA Jetson Orin Nano)
│   ├── app.py           # FastAPI Backend
│   ├── templates/       # Web-Dashboard
│   └── requirements.txt
├── backend/             # Leitstelle (Alienware + RTX 5090)
│   ├── app.py           # FastAPI Backend
│   ├── templates/       # Web-Dashboard
│   └── requirements.txt
├── shared/              # Gemeinsame Datenmodelle
└── docs/                # Dokumentation & Demo-Material
```

## Schnellstart

### Jetson (Feldgerät)
```bash
cd jetson
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# Whisper.cpp und Vosk-Modell separat installieren (siehe docs/)
python3 -m uvicorn app:app --host 0.0.0.0 --port 8080
```

### Backend (Alienware)
```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# Ollama mit Qwen2.5-32B installieren
python3 -m uvicorn app:app --host 0.0.0.0 --port 8080
```

## Hardware

- **Jetson**: NVIDIA Jetson Orin Nano, JetPack 6, 7.4GB shared RAM, CUDA 12.6
- **Alienware**: NVIDIA RTX 5090 24GB VRAM, Windows + WSL2/Python

## Demo

Für die AFCEA Bonn / Bundeswehr-Delegation — 19.03.2026

---
*CGI Deutschland — SAFIR Projekt*
