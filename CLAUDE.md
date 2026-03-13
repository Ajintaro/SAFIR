# SAFIR — Projekt-Kontext fuer Claude Code

## Was ist SAFIR?
Sanitaets-Assistenz fuer Feld-Informations-Reporting. KI-gestuetztes Dokumentationssystem
entlang der Rettungskette der Bundeswehr. Demo fuer AFCEA Bonn / Bundeswehr-Delegation am 19.03.2026.

## Zwei Geraete
- **Jetson Orin Nano** (`jetson/`): Feldgeraet, 8GB shared RAM, Whisper small + Vosk, 9-Liner per Sprache
- **Alienware + RTX 5090** (`backend/`): Leitstelle, 24GB VRAM, Whisper large-v3, Speaker Diarization, Qwen2.5-32B

## Rettungskette
Phase 0 (Ersthelfer) → Role 1 (Rettungsstation) → Role 2 (Rettungszentrum/OP) → Role 3 (Einsatzlazarett) → Role 4 (BW-Krankenhaus)

## Tech Stack
- Python 3, FastAPI, WebSocket, Jinja2 Templates
- Whisper (whisper.cpp auf Jetson, faster-whisper auf Alienware)
- Vosk (Sprachbefehle auf Jetson)
- Ollama (Qwen2.5-1.5B auf Jetson CPU, Qwen2.5-32B auf Alienware GPU)
- pyannote-audio (Speaker Diarization auf Alienware)
- CGI Corporate Design: Rot #E11937, Font Inter, Dark Mode

## Datenfluss
Jetson erfasst im Feld → POST /api/ingest an Backend → Backend verarbeitet weiter (LLM, Diarization) → Dashboard zeigt Rettungskette

## Gemeinsame Datenmodelle
Siehe `shared/models.py` — PATIENT_SCHEMA und TRANSFER_SCHEMA definieren den Datenaustausch.
