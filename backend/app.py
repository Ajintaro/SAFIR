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
ROOT_DIR = PROJECT_DIR.parent
TEMPLATES_DIR = ROOT_DIR / "templates"          # Einheitliches Template
TEMPLATES_DIR_LOCAL = PROJECT_DIR / "templates"  # Fallback
STATIC_DIR = PROJECT_DIR / "static"
DATA_DIR = PROJECT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
PATIENTS_DIR = DATA_DIR / "patients"
PATIENTS_DIR.mkdir(exist_ok=True)

app = FastAPI(title="SAFIR Leitstelle")
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
# Einheitliches Template bevorzugen, Fallback auf lokales
_tpl_dir = TEMPLATES_DIR if TEMPLATES_DIR.exists() else TEMPLATES_DIR_LOCAL
templates = Jinja2Templates(directory=str(_tpl_dir))


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
        self.peers: dict = {}             # device_id -> {unit_name, ip, port, ...}

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
    """Lädt alle Patienten aus JSON-Dateien.
    SIM-Patienten (Prefix SIM-) werden beim Start übersprungen und gelöscht,
    da sie nur während einer aktiven Simulation existieren sollen."""
    for filepath in PATIENTS_DIR.glob("*.json"):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                patient = json.load(f)
                pid = patient.get("patient_id")
                if pid:
                    # Simulations-/Test-Patienten beim Start entfernen
                    if pid.startswith("SIM-") or pid.startswith("TEST-") or pid.startswith("P0-"):
                        filepath.unlink()
                        print(f"  Simulations-Patient {pid} entfernt")
                        continue
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
    """Lädt globalen Zustand.
    Simulations-Transporte und -Positionen werden beim Start bereinigt."""
    state_file = DATA_DIR / "state.json"
    if state_file.exists():
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                state.transports = data.get("transports", {})
                state.positions = data.get("positions", {})
                state.events = data.get("events", [])
            # Simulations-Transporte und -Positionen beim Start aufräumen
            sim_keys = [k for k, v in state.transports.items()
                        if v.get("device_id", "").startswith("sim-")]
            for k in sim_keys:
                del state.transports[k]
                print(f"  Simulations-Transport {k} entfernt")
            sim_pos = [k for k, v in state.positions.items()
                       if v.get("device_id", "").startswith("sim-")]
            for k in sim_pos:
                del state.positions[k]
                print(f"  Simulations-Position {k} entfernt")
            if sim_keys or sim_pos:
                save_state()
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
        "peers": list(state.peers.values()),
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
    return templates.TemplateResponse("index.html", {"request": request, "config": load_backend_config()})


@app.get("/api/status")
async def get_status():
    # Patienten nach Triage zählen
    triage_counts = {"T1": 0, "T2": 0, "T3": 0, "T4": 0}
    for p in state.patients.values():
        t = p.get("triage", "")
        if t in triage_counts:
            triage_counts[t] += 1

    cfg = load_backend_config()
    return {
        "device": "leitstelle",
        "device_id": cfg.get("device_id", "surface-01"),
        "unit_name": cfg.get("unit_name", "Rettungsstation"),
        "role": cfg.get("role", "role1"),
        "patients_total": len(state.patients),
        "triage": triage_counts,
        "transports_active": len(state.transports),
        "positions": len(state.positions),
        # Feature-Flags für die einheitliche UI
        "has_whisper": False,
        "has_vosk": False,
        "has_audio": True,
        "has_map": True,
        "default_page": "role1",
    }


BACKEND_CONFIG_PATH = PROJECT_DIR / "config.json"


def load_backend_config() -> dict:
    """Lädt die Backend-eigene Config."""
    if BACKEND_CONFIG_PATH.exists():
        with open(BACKEND_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "device_id": "surface-01",
        "unit_name": "Rettungsstation",
        "role": "role1",
        "navigation": [
            {"id": "role1", "label": "Role 1", "icon": "&#9769;", "subtitle": "Rettungsstation", "default": True},
            {"id": "patients", "label": "Patienten", "icon": "&#9764;"},
            {"id": "settings", "label": "Einstellungen", "icon": "&#9881;"},
        ],
    }


def save_backend_config(cfg: dict):
    """Speichert die Backend-eigene Config."""
    with open(BACKEND_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)


@app.get("/api/config")
@app.get("/api/config/navigation")
async def get_config():
    return load_backend_config()


@app.post("/api/config")
async def update_config(body: dict):
    """Config aktualisieren und speichern."""
    cfg = load_backend_config()
    for key, value in body.items():
        if isinstance(value, dict) and isinstance(cfg.get(key), dict):
            cfg[key].update(value)
        else:
            cfg[key] = value
    save_backend_config(cfg)
    return {"status": "ok"}


# Stub-Endpunkte die das einheitliche Template erwartet
@app.get("/api/templates")
async def get_templates():
    return {"templates": []}


@app.get("/api/sessions")
async def get_sessions():
    return {"sessions": []}


@app.get("/api/models")
async def get_models():
    return {"models": [], "current": None}


@app.get("/api/devices")
async def get_devices():
    """Listet verfügbare Audio-Eingabegeräte."""
    devices = []
    try:
        import sounddevice as sd
        for i, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] > 0:
                devices.append({
                    "id": i,
                    "name": dev["name"],
                    "channels": dev["max_input_channels"],
                    "sample_rate": int(dev["default_samplerate"]),
                    "is_default": i == sd.default.device[0],
                })
    except ImportError:
        # sounddevice nicht installiert — pyaudio als Fallback
        try:
            import pyaudio
            pa = pyaudio.PyAudio()
            for i in range(pa.get_device_count()):
                dev = pa.get_device_info_by_index(i)
                if dev["maxInputChannels"] > 0:
                    devices.append({
                        "id": i,
                        "name": dev["name"],
                        "channels": dev["maxInputChannels"],
                        "sample_rate": int(dev["defaultSampleRate"]),
                        "is_default": i == pa.get_default_input_device_info()["index"],
                    })
            pa.terminate()
        except Exception:
            pass
    except Exception:
        pass
    return {"devices": devices}


@app.get("/api/files")
async def get_files():
    return {"files": []}


@app.get("/api/patients")
async def get_patients():
    # Unit-Name an Patienten anhängen (aus Transport-Cluster)
    pid_to_unit = {}
    for unit_name, transport in state.transports.items():
        for pid in transport.get("patient_ids", []):
            pid_to_unit[pid] = unit_name

    patients_with_unit = []
    for p in state.patients.values():
        patient = {**p}
        if patient["patient_id"] in pid_to_unit:
            patient["unit_name"] = pid_to_unit[patient["patient_id"]]
        patients_with_unit.append(patient)

    return {"patients": patients_with_unit}


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
async def _do_ingest(body: dict) -> dict:
    """Kernlogik für Patientenaufnahme. Wird von /api/ingest und /api/phase0/send genutzt."""
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
        # rfid_tag_id mit in die Scalar-Merge-Liste aufnehmen — nötig damit
        # der Jetson uns die RFID-UID nach dem Write-Flow zusenden kann
        # und der Omnikey-Scan am Surface den Patient wiederfindet.
        for key in ["name", "rank", "triage", "flow_status", "unit", "blood_type", "rfid_tag_id"]:
            val = patient.get(key)
            if val:
                existing[key] = val
        for key in ["transcripts", "timeline", "injuries", "treatments", "medications"]:
            new_items = patient.get(key, [])
            if new_items:
                existing_list = existing.setdefault(key, [])
                for item in new_items:
                    if item not in existing_list:
                        existing_list.append(item)
        if patient.get("vitals"):
            for k, v in patient["vitals"].items():
                if v:
                    existing.setdefault("vitals", {})[k] = v
        if patient.get("nine_liner"):
            existing["nine_liner"] = patient["nine_liner"]
        existing["synced"] = True
        existing["current_role"] = patient.get("current_role", existing.get("current_role", "phase0"))
    else:
        patient["synced"] = True
        state.patients[pid] = patient

    # Unit-Name am Patienten speichern (für UI-Gruppierung)
    if unit_name and unit_name != "Unbekannt":
        state.patients[pid]["unit_name"] = unit_name

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

    cfg = load_backend_config()
    ack_id = f"ACK-{pid}-{int(time.time())}"
    return {
        "status": "ok",
        "patient_id": pid,
        "ack_id": ack_id,
        "received_at": datetime.now().isoformat(),
        "unit_name": cfg.get("unit_name", ""),
        "role": cfg.get("role", "role1"),
    }


@app.post("/api/ingest")
async def ingest_from_device(body: dict):
    """Empfängt Patientendaten von einem Feldgerät (Jetson/BAT)."""
    return await _do_ingest(body)


# ---------------------------------------------------------------------------
# Omnikey RFID Lookup — Kern-Feature für die Role 1 Leitstelle
# ---------------------------------------------------------------------------
async def _handle_rfid_uid(uid: str) -> dict:
    """Sucht einen Patienten anhand einer RFID-UID und broadcastet
    das Ergebnis an alle verbundenen Clients. Wird sowohl vom
    Omnikey-Background-Loop als auch vom manuellen /api/rfid/lookup
    Endpoint aufgerufen.

    Match erfolgt gegen ``patient["rfid_tag_id"]`` — das Feld das der
    Jetson nach erfolgreichem RC522-Write setzt und via /api/ingest an
    uns schickt.
    """
    uid_norm = (uid or "").strip().upper()
    patient = None
    patient_id = None

    # Linearsuche ist OK — selbst bei 1000 Patienten <1 ms
    for pid, p in state.patients.items():
        tag = (p.get("rfid_tag_id") or "").strip().upper()
        if tag and tag == uid_norm:
            patient = p
            patient_id = pid
            break

    result = {
        "type": "rfid_scan_result",
        "uid": uid_norm,
        "found": patient is not None,
        "patient_id": patient_id,
        "patient": patient,
        "timestamp": datetime.now().isoformat(),
    }

    # Event in den Feed damit man den Scan im Verlauf sieht
    if patient:
        add_event(
            "rfid_scan",
            f"Karte gelesen: {patient.get('name', 'Unbekannt')} ({uid_norm})",
            patient_id=patient_id,
        )
    else:
        add_event("rfid_scan", f"Unbekannte Karte gelesen: {uid_norm}")

    await broadcast(result)
    return result


@app.post("/api/rfid/lookup")
async def rfid_lookup(body: dict):
    """Manueller Lookup-Endpoint — nimmt eine UID entgegen und
    broadcastet das Match-Ergebnis. Für Tests per ``curl`` oder als
    Fallback wenn pyscard/Omnikey nicht verfügbar ist.

    Beispiel:
        curl -X POST http://ai-station:8080/api/rfid/lookup \\
             -H 'Content-Type: application/json' \\
             -d '{"uid":"8AEF10C3"}'
    """
    uid = (body.get("uid") or "").strip()
    if not uid:
        return {"status": "error", "error": "uid fehlt"}
    return await _handle_rfid_uid(uid)


# ---------------------------------------------------------------------------
# Phase 0 — Simulation (Patienten ohne Spracheingabe erstellen & senden)
# ---------------------------------------------------------------------------
@app.post("/api/phase0/create")
async def phase0_create_patient(body: dict):
    """Erstellt einen Patienten in der Phase 0 Simulation (ohne Spracheingabe)."""
    pid = f"P0-{int(time.time() * 1000)}"
    patient = {
        "patient_id": pid,
        "name": body.get("name", "Unbekannt"),
        "triage": body.get("triage", ""),
        "injuries": body.get("injuries", []),
        "vitals": body.get("vitals", {}),
        "current_role": "phase0",
        "flow_status": "registered",
        "synced": False,
        "transfer_state": "pending",
        "timestamp_created": datetime.now().isoformat(),
        "transcripts": [],
        "timeline": [],
        "treatments": [],
        "medications": [],
    }
    state.patients[pid] = patient
    save_patient(patient)
    await broadcast({"type": "patient_new", "patient": patient})
    return {"status": "ok", "patient_id": pid}


@app.post("/api/phase0/send")
async def phase0_send_patient(body: dict):
    """Sendet einen Phase-0-Patienten an die nächste Rolle (Self-Ingest oder Remote)."""
    pid = body.get("patient_id")
    patient = state.patients.get(pid)
    if not patient:
        return {"error": "Patient nicht gefunden"}

    # Status auf GESENDET setzen
    patient["transfer_state"] = "sent"
    patient["transfer_time"] = datetime.now().isoformat()
    save_patient(patient)
    await broadcast({"type": "transfer_update", "patient_id": pid, "transfer_state": "sent"})

    cfg = load_backend_config()
    target_url = cfg.get("phase0_target_url", "")

    # Self-Ingest: gleicher Server → direkte Verarbeitung
    if not target_url or target_url.startswith("http://127.0.0.1") or target_url.startswith("http://localhost"):
        try:
            payload = {
                "patient": patient,
                "unit_name": cfg.get("phase0_unit_name", "BAT Simulation"),
                "device_id": cfg.get("device_id", "phase0-sim"),
            }
            result = await _do_ingest(payload)
            if result.get("status") == "ok":
                patient["transfer_state"] = "acknowledged"
                patient["transfer_ack_id"] = result.get("ack_id", "")
                patient["transfer_ack_time"] = datetime.now().isoformat()
                save_patient(patient)
                await broadcast({
                    "type": "transfer_update",
                    "patient_id": pid,
                    "transfer_state": "acknowledged",
                    "ack_id": result.get("ack_id"),
                })
                return {"status": "ok", "ack_id": result.get("ack_id")}
            else:
                patient["transfer_state"] = "failed"
                patient["transfer_error"] = result.get("error", "Unbekannter Fehler")
                save_patient(patient)
                await broadcast({"type": "transfer_update", "patient_id": pid, "transfer_state": "failed"})
                return {"status": "error", "detail": result.get("error")}
        except Exception as e:
            patient["transfer_state"] = "failed"
            patient["transfer_error"] = str(e)
            save_patient(patient)
            await broadcast({"type": "transfer_update", "patient_id": pid, "transfer_state": "failed", "error": str(e)})
            return {"status": "error", "detail": str(e)}
    else:
        # Remote-Ingest: HTTP POST an externes Gerät
        import httpx
        try:
            payload = {
                "patient": patient,
                "unit_name": cfg.get("phase0_unit_name", "BAT Simulation"),
                "device_id": cfg.get("device_id", "phase0-sim"),
            }
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(f"{target_url}/api/ingest", json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    patient["transfer_state"] = "acknowledged"
                    patient["transfer_ack_id"] = data.get("ack_id", "")
                    patient["transfer_ack_time"] = datetime.now().isoformat()
                    save_patient(patient)
                    await broadcast({
                        "type": "transfer_update",
                        "patient_id": pid,
                        "transfer_state": "acknowledged",
                        "ack_id": data.get("ack_id"),
                    })
                    return {"status": "ok", "ack_id": data.get("ack_id")}
                else:
                    patient["transfer_state"] = "failed"
                    patient["transfer_error"] = f"HTTP {resp.status_code}"
                    save_patient(patient)
                    await broadcast({"type": "transfer_update", "patient_id": pid, "transfer_state": "failed"})
                    return {"status": "error", "detail": f"HTTP {resp.status_code}"}
        except Exception as e:
            patient["transfer_state"] = "failed"
            patient["transfer_error"] = str(e)
            save_patient(patient)
            await broadcast({"type": "transfer_update", "patient_id": pid, "transfer_state": "failed", "error": str(e)})
            return {"status": "error", "detail": str(e)}


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
# Patienten-Aktionen (für einheitliches Template)
# ---------------------------------------------------------------------------
@app.post("/api/patient/{patient_id}/select")
async def select_patient(patient_id: str):
    if patient_id not in state.patients:
        return {"error": "Patient nicht gefunden"}
    await broadcast({"type": "patient_selected", "patient": state.patients[patient_id]})
    return {"status": "ok"}


@app.post("/api/patient/{patient_id}/update")
async def update_patient(patient_id: str, body: dict):
    if patient_id not in state.patients:
        return {"error": "Patient nicht gefunden"}
    patient = state.patients[patient_id]
    for key, val in body.items():
        if key != "patient_id" and val is not None:
            patient[key] = val
    save_patient(patient)
    await broadcast({"type": "patient_update", "patient": patient})
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Simulation: Reset (löscht SIM-Patienten)
# ---------------------------------------------------------------------------
@app.post("/api/simulation/reset")
async def simulation_reset():
    """Löscht alle Simulations- und Test-Patienten (IDs mit SIM- oder TEST- Prefix)."""
    sim_ids = [pid for pid in state.patients if pid.startswith("SIM-") or pid.startswith("TEST-")]
    for pid in sim_ids:
        del state.patients[pid]
        filepath = PATIENTS_DIR / f"{pid}.json"
        if filepath.exists():
            filepath.unlink()

    # Transporte mit sim- Devices aufräumen
    sim_transports = [k for k, v in state.transports.items()
                      if v.get("device_id", "").startswith("sim-")]
    for k in sim_transports:
        del state.transports[k]

    # Positionen mit sim- Devices aufräumen (auch wenn Transport schon weg ist)
    sim_positions = [k for k, v in state.positions.items()
                     if v.get("device_id", "").startswith("sim-")]
    for k in sim_positions:
        del state.positions[k]

    state.events = []
    save_state()
    await broadcast({"type": "init", "patients": list(state.patients.values()),
                     "transports": state.transports, "positions": state.positions, "events": []})
    return {"status": "ok", "removed": len(sim_ids)}


@app.post("/api/data/reset")
async def data_reset():
    """Löscht ALLE Patientendaten, Transporte, Positionen und Events.
    Für einen sauberen Demo-Neustart."""
    # Alle Patienten-Dateien löschen
    count = len(state.patients)
    for filepath in PATIENTS_DIR.glob("*.json"):
        filepath.unlink()
    state.patients.clear()

    # Transporte, Positionen, Events leeren
    state.transports.clear()
    state.positions.clear()
    state.events.clear()

    # state.json zurücksetzen
    save_state()

    # Alle Clients über leeren Zustand informieren
    await broadcast({
        "type": "init",
        "patients": [],
        "transports": {},
        "positions": {},
        "events": [],
    })

    print(f"Daten-Reset: {count} Patienten gelöscht")
    return {"status": "ok", "removed": count}


# ---------------------------------------------------------------------------
# LLM: Vorbereitungshinweise für eintreffende Patienten
# ---------------------------------------------------------------------------
@app.post("/api/llm/prepare")
async def llm_prepare(body: dict):
    """Generiert KI-Vorbereitungshinweise für einen Patienten."""
    patient = body.get("patient", {})
    if not patient:
        return {"hints": "<p>Keine Patientendaten</p>"}

    # Versuche Ollama/Qwen für Hinweise (wenn verfügbar)
    try:
        import httpx
        injuries = ", ".join(patient.get("injuries", []))
        triage = patient.get("triage", "?")
        vitals = patient.get("vitals", {})
        vitals_str = ", ".join(f"{k}: {v}" for k, v in vitals.items() if v)

        prompt = f"""Du bist ein militärmedizinischer Assistent an einer Rettungsstation (Role 1).
Ein verwundeter Soldat trifft gleich ein. Erstelle eine kurze, präzise Vorbereitungsliste.

Patient: {patient.get('name', 'Unbekannt')}
Triage: {triage}
Verletzungen: {injuries or 'keine Angabe'}
Vitalzeichen: {vitals_str or 'keine Angabe'}
Blutgruppe: {patient.get('blood_type', 'unbekannt')}

Antworte NUR mit einer HTML-Liste (<ul><li>...</li></ul>) der Vorbereitungsschritte.
Maximal 6 Punkte. Deutsch. Knapp und präzise."""

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post("http://127.0.0.1:11434/api/generate", json={
                "model": "qwen2.5:1.5b",
                "prompt": prompt,
                "stream": False,
            })
            if resp.status_code == 200:
                data = resp.json()
                return {"hints": data.get("response", "")}
    except Exception:
        pass

    return {"hints": ""}


# ---------------------------------------------------------------------------
# Peer Discovery / Netzwerk-Teilnehmer
# ---------------------------------------------------------------------------
PEER_TIMEOUT_HOURS = 5


@app.post("/api/heartbeat")
async def receive_heartbeat(body: dict, request: Request):
    """Empfängt Heartbeat von einem Netzwerk-Teilnehmer (z.B. Jetson)."""
    device_id = body.get("device_id", "")
    if not device_id:
        return {"error": "device_id fehlt"}
    # IP aus Request extrahieren falls nicht im Body
    ip = body.get("ip", "") or (request.client.host if request.client else "")
    state.peers[device_id] = {
        "unit_name": body.get("unit_name", "Unbekannt"),
        "unit_role": body.get("unit_role", ""),
        "system_name": body.get("system_name", ""),
        "device_id": device_id,
        "ip": ip,
        "port": body.get("port", 8080),
        "last_seen": datetime.now().isoformat(),
        "patient_count": body.get("patient_count", 0),
    }
    return {"status": "ok", "peers": len(state.peers)}


@app.get("/api/peers")
async def get_peers():
    """Gibt alle bekannten Netzwerk-Teilnehmer zurück."""
    now = datetime.now()
    # Alte Peers entfernen
    expired = [k for k, v in state.peers.items()
               if (now - datetime.fromisoformat(v["last_seen"])).total_seconds() > PEER_TIMEOUT_HOURS * 3600]
    for k in expired:
        del state.peers[k]

    peers_list = list(state.peers.values())
    # Eigene Instanz immer mit aufnehmen
    cfg = load_backend_config()
    own = {
        "unit_name": cfg.get("unit_name", "Rettungsstation"),
        "unit_role": cfg.get("role", "role1"),
        "system_name": "Surface Pro",
        "device_id": cfg.get("device_id", "surface-01"),
        "ip": "127.0.0.1",
        "port": 8080,
        "is_self": True,
        "last_seen": now.isoformat(),
        "patient_count": len(state.patients),
    }
    # Eigene Instanz nicht doppelt
    peers_list = [p for p in peers_list if p["device_id"] != own["device_id"]]
    peers_list.insert(0, own)
    return {"peers": peers_list}


async def _system_stats_loop():
    """Sendet periodisch System-Stats (CPU, RAM, Disk) an alle WebSocket-Clients."""
    try:
        import psutil
    except ImportError:
        print("psutil nicht installiert — Hardware-Monitor deaktiviert")
        return

    import platform
    await asyncio.sleep(2)
    while True:
        try:
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")

            # CPU-Frequenz ermitteln
            cpu_freq = psutil.cpu_freq()
            cpu_freq_mhz = round(cpu_freq.current) if cpu_freq else 0

            # Temperatur (falls verfügbar)
            temperatures = {}
            try:
                temps = psutil.sensors_temperatures()
                if temps:
                    for name, entries in temps.items():
                        for entry in entries:
                            key = entry.label or name
                            temperatures[key] = round(entry.current)
            except (AttributeError, Exception):
                pass  # macOS hat keine sensors_temperatures

            ram_used_mb = round(mem.used / 1024 / 1024)
            ram_total_mb = round(mem.total / 1024 / 1024)
            ram_percent = round((ram_used_mb / ram_total_mb) * 100, 1) if ram_total_mb > 0 else 0

            stats = {
                "cpu_percent": cpu,
                "cpu_freq_mhz": cpu_freq_mhz,
                "ram_used_mb": ram_used_mb,
                "ram_total_mb": ram_total_mb,
                "ram_percent": ram_percent,
                "gpu_usage": "N/A",
                "disk_used_gb": round(disk.used / 1024 / 1024 / 1024, 1),
                "disk_total_gb": round(disk.total / 1024 / 1024 / 1024, 1),
                "disk_percent": round(disk.percent),
                "temperatures": temperatures,
                "system_name": platform.node(),
                "platform": platform.system(),
                "cpu_name": platform.processor() or platform.machine(),
            }

            # GPU-Info (NVIDIA via nvidia-smi)
            if platform.system() != "Darwin":
                try:
                    import subprocess
                    result = subprocess.run(
                        ["nvidia-smi", "--query-gpu=name,memory.used,memory.total,temperature.gpu,utilization.gpu",
                         "--format=csv,noheader,nounits"],
                        capture_output=True, text=True, timeout=3
                    )
                    if result.returncode == 0:
                        parts = result.stdout.strip().split(", ")
                        if len(parts) >= 5:
                            stats["gpu_name"] = parts[0]
                            stats["gpu_vram_used_mb"] = int(parts[1])
                            stats["gpu_vram_total_mb"] = int(parts[2])
                            stats["temperatures"]["gpu-thermal"] = int(parts[3])
                            stats["gpu_usage"] = parts[4]
                except Exception:
                    pass

            # Top-Prozesse nach RAM
            procs = []
            for proc in psutil.process_iter(["name", "memory_info"]):
                try:
                    mi = proc.info.get("memory_info")
                    if mi is None:
                        continue
                    rss = mi.rss / 1024 / 1024
                    if rss > 50:
                        procs.append({"name": proc.info["name"] or "?", "rss_mb": round(rss)})
                except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                    pass
            procs.sort(key=lambda x: x["rss_mb"], reverse=True)
            stats["ram_processes"] = procs[:8]

            await broadcast({"type": "system_stats", "stats": stats})
        except Exception as e:
            print(f"System-Stats Fehler: {e}")
        await asyncio.sleep(3)


async def _heartbeat_loop():
    """Sendet periodisch Heartbeats an alle bekannten Peers (alle 30s)."""
    import httpx
    await asyncio.sleep(5)
    while True:
        try:
            cfg = load_backend_config()
            payload = {
                "device_id": cfg.get("device_id", "surface-01"),
                "unit_name": cfg.get("unit_name", "Rettungsstation"),
                "unit_role": cfg.get("role", "role1"),
                "system_name": "Surface Pro",
                "ip": "",
                "port": 8080,
                "patient_count": len(state.patients),
            }
            # An alle bekannten Peers senden
            for peer in list(state.peers.values()):
                if peer["device_id"] == payload["device_id"]:
                    continue
                ip = peer.get("ip", "")
                port = peer.get("port", 8080)
                if ip and ip != "127.0.0.1":
                    try:
                        async with httpx.AsyncClient(timeout=3) as client:
                            await client.post(f"http://{ip}:{port}/api/heartbeat", json=payload)
                    except Exception:
                        pass
        except Exception as e:
            print(f"Heartbeat Fehler: {e}")
        await asyncio.sleep(30)


# ---------------------------------------------------------------------------
# OLED-Display Simulator
# ---------------------------------------------------------------------------
# Import der OLED-Engine (funktioniert ohne I2C-Hardware)
import sys
sys.path.insert(0, str(ROOT_DIR / "jetson"))
try:
    from oled import oled_menu
    _oled_available = True
    print(f"OLED: Modul geladen (Software-Simulator)")
except Exception as e:
    _oled_available = False
    print(f"OLED-Modul nicht verfügbar: {e}")


@app.get("/api/oled/state")
async def oled_get_state():
    """Gibt OLED-Daten für die aktuelle Seite zurück."""
    if not _oled_available:
        return {"error": "OLED nicht verfügbar"}
    return {
        "page": oled_menu.current_page,
        "page_name": ["system", "audio", "network", "patients", "power", "models"][oled_menu.current_page],
        "stats": oled_menu.stats,
        "audio": oled_menu.audio_info,
        "network": oled_menu.network_info,
        "patients": oled_menu.patient_info,
        "power": oled_menu.power_info,
        "models": oled_menu.model_info,
    }


@app.post("/api/oled/button")
async def oled_button(body: dict):
    """Simuliert einen Tastendruck auf dem OLED-Display."""
    if not _oled_available:
        return {"error": "OLED nicht verfügbar"}
    button = body.get("button", "")
    result = {}
    if button == "up":
        oled_menu.button_up()
    elif button == "down":
        oled_menu.button_down()
    elif button == "ok":
        result = oled_menu.button_ok() or {}
    else:
        return {"error": f"Unbekannter Button: {button}"}
    return {
        "status": "ok",
        "page": oled_menu.current_page,
        "page_name": ["system", "audio", "network", "patients", "power", "models"][oled_menu.current_page],
        **result,
    }


async def _oled_loop():
    """Aktualisiert das OLED-Display alle 1s mit aktuellen Daten und broadcastet an Clients."""
    if not _oled_available:
        return
    await asyncio.sleep(3)
    while True:
        try:
            # System-Stats aktualisieren
            cfg = load_backend_config()
            import psutil
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            oled_menu.update_stats({
                "cpu_percent": cpu,
                "ram_percent": round((mem.used / mem.total) * 100, 1) if mem.total > 0 else 0,
                "ram_used_mb": round(mem.used / 1024 / 1024),
                "ram_total_mb": round(mem.total / 1024 / 1024),
                "gpu_usage": "N/A",
                "disk_percent": round(disk.percent),
                "temperatures": {},
                "unit_name": cfg.get("unit_name", ""),
                "patient_count": len(state.patients),
            })

            # Patienten-Info
            triage = {"t1": 0, "t2": 0, "t3": 0, "t4": 0}
            synced = 0
            last_name = "---"
            for p in state.patients.values():
                t = p.get("triage", "").upper()
                if t in ["T1", "T2", "T3", "T4"]:
                    triage[t.lower()] += 1
                if p.get("synced"):
                    synced += 1
                last_name = p.get("name", last_name)
            oled_menu.update_patients({
                "total": len(state.patients),
                **triage,
                "synced": synced,
                "last_patient": last_name,
            })

            # Netzwerk-Info
            peers = len(state.peers)
            role1_connected = any(
                p.get("unit_role") in ("role1", "Role 1")
                for p in state.peers.values()
            )
            oled_menu.update_network({
                "ssid": "---",
                "ip": "---",
                "tailscale_ip": "---",
                "role1_status": "verbunden" if role1_connected else "getrennt",
                "peers": peers,
            })

            # Modelle-Info (Platzhalter)
            oled_menu.update_models({
                "whisper_model": "---",
                "whisper_loaded": False,
                "ollama_model": cfg.get("ollama", {}).get("model", "---"),
                "ollama_loaded": False,
                "vosk_active": False,
                "ok_action": "Nicht verfügbar",
            })

            # Daten broadcasten
            await broadcast({
                "type": "oled_frame",
                "page": oled_menu.current_page,
                "page_name": ["system", "audio", "network", "patients", "power", "models"][oled_menu.current_page],
                "stats": oled_menu.stats,
                "audio": oled_menu.audio_info,
                "network": oled_menu.network_info,
                "patients": oled_menu.patient_info,
                "models": oled_menu.model_info,
            })

        except Exception as e:
            print(f"OLED-Loop Fehler: {e}")
        await asyncio.sleep(1)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def startup():
    load_patients()
    load_state()
    print(f"SAFIR Leitstelle gestartet — Role 1 (Rettungsstation)")
    print(f"  Geladene Patienten: {len(state.patients)}")
    print(f"  Aktive Transporte: {len(state.transports)}")
    print(f"  Aktive Positionen: {len(state.positions)}")
    asyncio.create_task(_heartbeat_loop())
    asyncio.create_task(_system_stats_loop())
    asyncio.create_task(_oled_loop())

    # Omnikey RFID Reader: Background-Task polled PC/SC-Reader und feuert
    # _handle_rfid_uid() pro gelesener Karte. Bricht nicht wenn pyscard
    # fehlt — das Modul loggt eine Warnung und return'ed dann.
    try:
        from backend.omnikey_reader import start_reader_loop
    except ImportError:
        try:
            from omnikey_reader import start_reader_loop  # wenn backend/ im path
        except ImportError as e:
            print(f"  Omnikey-Reader Modul nicht importierbar: {e}")
            start_reader_loop = None
    if start_reader_loop is not None:
        asyncio.create_task(start_reader_loop(_handle_rfid_uid))
        print("  Omnikey Reader-Task gestartet (wartet auf pyscard/Reader)")

    print("Warte auf Verbindungen von Feldgeräten...")
