#!/usr/bin/env python3
"""
SAFIR Leitstelle — Rettungsstation (Role 1)
Taktische Lagekarte + Live-Dashboard für eingehende Verwundete.

Empfängt Patientendaten und GPS-Positionen von Feldgeräten (Jetsons/BATs),
zeigt Truppenbewegungen auf der Karte und clustert Patienten nach Transport.
"""

import asyncio
import json
import time
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

PROJECT_DIR = Path(__file__).parent
TEMPLATES_DIR = PROJECT_DIR / "templates"
STATIC_DIR = PROJECT_DIR / "static"
DATA_DIR = PROJECT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
PATIENTS_DIR = DATA_DIR / "patients"
PATIENTS_DIR.mkdir(exist_ok=True)

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
        self.transports: dict = {}        # unit_name -> transport info
        self.positions: dict = {}         # unit_name -> {lat, lon, timestamp, ...}
        self.ws_clients: list = []
        self.events: list = []            # Chronologischer Event-Feed

state = AppState()


# ---------------------------------------------------------------------------
# Persistenz: JSON-Dateien
# ---------------------------------------------------------------------------
def save_patient(patient: dict):
    """Speichert einen Patienten als JSON-Datei."""
    pid = patient.get("patient_id", "unknown")
    filepath = PATIENTS_DIR / f"{pid}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(patient, f, indent=2, ensure_ascii=False)


def load_patients():
    """Lädt alle Patienten aus JSON-Dateien."""
    for filepath in PATIENTS_DIR.glob("*.json"):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                patient = json.load(f)
                pid = patient.get("patient_id")
                if pid:
                    state.patients[pid] = patient
        except Exception as e:
            print(f"Fehler beim Laden von {filepath}: {e}")


def save_state():
    """Speichert globalen Zustand (Transporte, Positionen)."""
    state_file = DATA_DIR / "state.json"
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump({
            "transports": state.transports,
            "positions": state.positions,
            "events": state.events[-100:],  # Letzte 100 Events
        }, f, indent=2, ensure_ascii=False)


def load_state():
    """Lädt globalen Zustand."""
    state_file = DATA_DIR / "state.json"
    if state_file.exists():
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                state.transports = data.get("transports", {})
                state.positions = data.get("positions", {})
                state.events = data.get("events", [])
        except Exception:
            pass


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------
async def broadcast(msg: dict):
    dead = []
    for ws in state.ws_clients:
        try:
            await ws.send_json(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        state.ws_clients.remove(ws)


def add_event(event_type: str, details: str, unit: str = "", patient_id: str = ""):
    """Fügt ein Event zum chronologischen Feed hinzu."""
    event = {
        "time": datetime.now().isoformat(),
        "type": event_type,
        "details": details,
        "unit": unit,
        "patient_id": patient_id,
    }
    state.events.append(event)
    if len(state.events) > 200:
        state.events = state.events[-100:]
    return event


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    state.ws_clients.append(ws)
    # Init-Daten senden
    await ws.send_json({
        "type": "init",
        "patients": list(state.patients.values()),
        "transports": state.transports,
        "positions": state.positions,
        "events": state.events[-20:],
    })
    try:
        while True:
            data = await ws.receive_json()
            if data.get("type") == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        if ws in state.ws_clients:
            state.ws_clients.remove(ws)


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/status")
async def get_status():
    # Patienten nach Triage zählen
    triage_counts = {"T1": 0, "T2": 0, "T3": 0, "T4": 0}
    for p in state.patients.values():
        t = p.get("triage", "")
        if t in triage_counts:
            triage_counts[t] += 1

    return {
        "device": "leitstelle",
        "role": "role1",
        "patients_total": len(state.patients),
        "triage": triage_counts,
        "transports_active": len(state.transports),
        "positions": len(state.positions),
    }


@app.get("/api/patients")
async def get_patients():
    return {"patients": list(state.patients.values())}


@app.get("/api/patients/{patient_id}")
async def get_patient(patient_id: str):
    if patient_id not in state.patients:
        return {"error": "Patient nicht gefunden"}
    return state.patients[patient_id]


@app.get("/api/transports")
async def get_transports():
    """Alle aktiven Transporte mit zugehörigen Patienten."""
    result = {}
    for unit_name, transport in state.transports.items():
        patient_ids = transport.get("patient_ids", [])
        patients = [state.patients[pid] for pid in patient_ids if pid in state.patients]
        result[unit_name] = {
            **transport,
            "patients": patients,
            "position": state.positions.get(unit_name),
        }
    return {"transports": result}


@app.get("/api/positions")
async def get_positions():
    return {"positions": state.positions}


@app.get("/api/events")
async def get_events():
    return {"events": state.events[-50:]}


# ---------------------------------------------------------------------------
# Jetson → Backend: Patientendaten empfangen
# ---------------------------------------------------------------------------
@app.post("/api/ingest")
async def ingest_from_device(body: dict):
    """Empfängt Patientendaten von einem Feldgerät (Jetson/BAT)."""
    patient = body.get("patient", {})
    pid = patient.get("patient_id")
    if not pid:
        return {"error": "Keine patient_id"}

    unit_name = body.get("unit_name", "") or patient.get("unit", "") or body.get("device_id", "Unbekannt")
    device_id = body.get("device_id", "")
    is_new = pid not in state.patients

    # Patient speichern/aktualisieren
    if pid in state.patients:
        existing = state.patients[pid]
        # Felder aktualisieren (nicht-leere überschreiben)
        for key in ["name", "rank", "triage", "flow_status", "unit", "blood_type"]:
            val = patient.get(key)
            if val:
                existing[key] = val
        # Arrays mergen
        for key in ["transcripts", "timeline", "injuries", "treatments", "medications"]:
            new_items = patient.get(key, [])
            if new_items:
                existing.setdefault(key, []).extend(new_items)
        # Vitals überschreiben
        if patient.get("vitals"):
            for k, v in patient["vitals"].items():
                if v:
                    existing.setdefault("vitals", {})[k] = v
        # 9-Liner überschreiben
        if patient.get("nine_liner"):
            existing["nine_liner"] = patient["nine_liner"]
        existing["synced"] = True
        existing["current_role"] = patient.get("current_role", existing.get("current_role", "phase0"))
    else:
        patient["synced"] = True
        state.patients[pid] = patient

    # Persistieren
    save_patient(state.patients[pid])

    # Transport-Cluster aktualisieren
    if unit_name:
        if unit_name not in state.transports:
            state.transports[unit_name] = {
                "unit_name": unit_name,
                "device_id": device_id,
                "patient_ids": [],
                "first_seen": datetime.now().isoformat(),
                "last_update": datetime.now().isoformat(),
            }
        transport = state.transports[unit_name]
        if pid not in transport["patient_ids"]:
            transport["patient_ids"].append(pid)
        transport["last_update"] = datetime.now().isoformat()

    # Event
    patient_data = state.patients[pid]
    event_detail = f"{'Neuer Patient' if is_new else 'Update'}: {patient_data.get('name', 'Unbekannt')}"
    if patient_data.get("triage"):
        event_detail += f" ({patient_data['triage']})"
    event = add_event(
        "patient_ingest" if is_new else "patient_update",
        event_detail,
        unit=unit_name,
        patient_id=pid,
    )

    save_state()

    await broadcast({
        "type": "patient_new" if is_new else "patient_update",
        "patient": state.patients[pid],
        "unit_name": unit_name,
        "event": event,
    })

    return {"status": "ok", "patient_id": pid}


# ---------------------------------------------------------------------------
# GPS-Position empfangen
# ---------------------------------------------------------------------------
@app.post("/api/position")
async def update_position(body: dict):
    """Empfängt GPS-Position von einem Feldgerät."""
    unit_name = body.get("unit_name", "")
    if not unit_name:
        return {"error": "Kein unit_name"}

    position = {
        "lat": body.get("lat", 0),
        "lon": body.get("lon", 0),
        "heading": body.get("heading", 0),
        "speed_kmh": body.get("speed_kmh", 0),
        "timestamp": datetime.now().isoformat(),
        "unit_name": unit_name,
        "device_id": body.get("device_id", ""),
    }
    state.positions[unit_name] = position
    save_state()

    await broadcast({
        "type": "position_update",
        "position": position,
    })

    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Dashboard Stats
# ---------------------------------------------------------------------------
@app.get("/api/dashboard/stats")
async def dashboard_stats():
    """Aggregierte Statistiken für das Dashboard."""
    triage = {"T1": 0, "T2": 0, "T3": 0, "T4": 0, "": 0}
    for p in state.patients.values():
        t = p.get("triage", "")
        triage[t] = triage.get(t, 0) + 1

    return {
        "patients_total": len(state.patients),
        "triage": triage,
        "transports_active": len(state.transports),
        "transports": {
            name: {
                "patient_count": len(t.get("patient_ids", [])),
                "last_update": t.get("last_update"),
                "position": state.positions.get(name),
            }
            for name, t in state.transports.items()
        },
    }


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def startup():
    load_patients()
    load_state()
    print(f"SAFIR Leitstelle gestartet — Role 1 (Rettungsstation)")
    print(f"Geladene Patienten: {len(state.patients)}")
    print(f"Aktive Transporte: {len(state.transports)}")
    print("Warte auf Verbindungen von Feldgeräten...")
