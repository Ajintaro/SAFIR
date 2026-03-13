#!/usr/bin/env python3
"""
SAFIR Backend — Leitstelle / Rettungskette Role 1-4
Laeuft auf Alienware Laptop mit RTX 5090 (24GB VRAM).

Komponenten:
- Whisper large-v3 fuer hochqualitative Transkription
- pyannote-audio fuer Speaker Diarization
- Qwen2.5-32B via Ollama fuer intelligente Analyse
- FastAPI Dashboard fuer Rettungskette-Visualisierung
"""

import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

import httpx

PROJECT_DIR = Path(__file__).parent
TEMPLATES_DIR = PROJECT_DIR / "templates"
STATIC_DIR = PROJECT_DIR / "static"
DATA_DIR = PROJECT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
UPLOAD_DIR = PROJECT_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

OLLAMA_URL = "http://127.0.0.1:11434"
OLLAMA_MODEL = "qwen2.5:32b"

app = FastAPI(title="SAFIR Leitstelle")
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
class AppState:
    def __init__(self):
        self.patients: dict = {}          # patient_id -> patient data
        self.connected_devices: dict = {} # device_id -> info
        self.ws_clients: list = []

state = AppState()


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------
async def broadcast(msg: dict):
    for ws in state.ws_clients[:]:
        try:
            await ws.send_json(msg)
        except Exception:
            state.ws_clients.remove(ws)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    state.ws_clients.append(ws)
    try:
        while True:
            data = await ws.receive_json()
            await handle_ws_message(data)
    except WebSocketDisconnect:
        state.ws_clients.remove(ws)


async def handle_ws_message(data: dict):
    msg_type = data.get("type", "")
    if msg_type == "device_update":
        # Jetson sendet Patientendaten
        patient = data.get("patient", {})
        pid = patient.get("patient_id")
        if pid:
            state.patients[pid] = patient
            await broadcast({"type": "patient_update", "patient": patient})


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/status")
async def get_status():
    return {
        "device": "alienware",
        "patients": len(state.patients),
        "connected_devices": len(state.connected_devices),
        "ollama_model": OLLAMA_MODEL,
    }


@app.get("/api/patients")
async def get_patients():
    return {"patients": list(state.patients.values())}


@app.get("/api/patients/{patient_id}")
async def get_patient(patient_id: str):
    if patient_id not in state.patients:
        return {"error": "Patient nicht gefunden"}
    return state.patients[patient_id]


# ---------------------------------------------------------------------------
# Jetson -> Backend: Patientendaten empfangen
# ---------------------------------------------------------------------------
@app.post("/api/ingest")
async def ingest_from_jetson(body: dict):
    """Empfaengt Patientendaten vom Jetson Feldgeraet."""
    patient = body.get("patient", {})
    pid = patient.get("patient_id")
    if not pid:
        return {"error": "Keine patient_id"}

    # Merge mit bestehenden Daten
    if pid in state.patients:
        existing = state.patients[pid]
        # Neue Transkripte anhaengen
        existing.setdefault("transcripts", []).extend(
            patient.get("transcripts", [])
        )
        # Timeline aktualisieren
        existing.setdefault("timeline", []).extend(
            patient.get("timeline", [])
        )
        # 9-Liner aktualisieren falls vorhanden
        if patient.get("nine_liner"):
            existing["nine_liner"] = patient["nine_liner"]
        existing["current_role"] = patient.get("current_role", existing["current_role"])
    else:
        state.patients[pid] = patient

    await broadcast({"type": "patient_update", "patient": state.patients[pid]})
    return {"status": "ok", "patient_id": pid}


# ---------------------------------------------------------------------------
# Audio Upload + Transkription + Speaker Diarization
# ---------------------------------------------------------------------------
@app.post("/api/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    """Transkribiert Audio mit Whisper large-v3 + Speaker Diarization."""
    # Datei speichern
    filepath = UPLOAD_DIR / file.filename
    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)

    # TODO: faster-whisper + pyannote-audio Integration
    # Platzhalter fuer die eigentliche Implementierung
    return {
        "status": "ok",
        "filename": file.filename,
        "message": "Transkription wird implementiert",
    }


# ---------------------------------------------------------------------------
# LLM-Analyse: Uebergabeberichte, Zusammenfassungen
# ---------------------------------------------------------------------------
@app.post("/api/analyze/handover")
async def generate_handover(body: dict):
    """Generiert einen Uebergabebericht fuer den Role-Wechsel."""
    patient_id = body.get("patient_id")
    from_role = body.get("from_role", "role1")
    to_role = body.get("to_role", "role2")

    if patient_id not in state.patients:
        return {"error": "Patient nicht gefunden"}

    patient = state.patients[patient_id]

    # TODO: LLM-basierte Uebergabebericht-Generierung
    return {
        "status": "ok",
        "message": "Uebergabebericht-Generierung wird implementiert",
    }


@app.post("/api/analyze/summary")
async def generate_summary(body: dict):
    """Erstellt eine KI-Zusammenfassung der Patientenakte."""
    patient_id = body.get("patient_id")

    if patient_id not in state.patients:
        return {"error": "Patient nicht gefunden"}

    # TODO: LLM-basierte Zusammenfassung
    return {
        "status": "ok",
        "message": "Zusammenfassung wird implementiert",
    }


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def startup():
    print("SAFIR Leitstelle gestartet")
    print(f"Ollama Model: {OLLAMA_MODEL}")
    print("Warte auf Verbindungen von Feldgeraeten...")
