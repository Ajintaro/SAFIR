#!/usr/bin/env python3
"""
SAFIR Leitstelle — Rettungsstation (Role 1)
Taktische Lagekarte + Live-Dashboard für eingehende Verwundete.

Empfängt Patientendaten und GPS-Positionen von Feldgeräten (Jetsons/BATs),
zeigt Truppenbewegungen auf der Karte und clustert Patienten nach Transport.
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path

# Logging auf INFO damit Omnikey-Scans, Operator-Login und andere
# INFO-Events im Terminal sichtbar sind. Ohne diese basicConfig
# schluckt Python die logger.info()-Aufrufe (Standard-Level = WARNING).
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

PROJECT_DIR = Path(__file__).parent
ROOT_DIR = PROJECT_DIR.parent

# Export-Modul im Repo-Root liegt (shared/exports.py). Wir fuegen das
# ROOT_DIR zum sys.path hinzu damit der Import funktioniert egal von wo
# uvicorn gestartet wurde.
import sys as _sys
if str(ROOT_DIR) not in _sys.path:
    _sys.path.insert(0, str(ROOT_DIR))
from shared import exports  # noqa: E402
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
        # Security-Lock: analog zum Jetson. Ein blauer Operator-Chip am Omnikey
        # entsperrt, nochmal auflegen sperrt wieder. Idle-Watcher sperrt nach
        # config.security.lock_idle_seconds (default 30 min) ohne Aktivitaet.
        self.current_operator: dict | None = None  # {uid, label, name, role, since}
        self.locked: bool = False
        self.last_activity: float = 0.0  # monotonic timestamp
        # Session-Store fuer LLM-Review: wenn der Jetson ein Diktat analysiert
        # hat und die Patienten meldet, landet hier das Original-Transkript
        # + die Liste aller Patient-IDs aus dieser Session. Das Surface-LLM
        # (Gemma 4) nutzt das spaeter fuer die Fehlender-Patient-Detection.
        #   session_id -> {
        #     "transcript":  "Hier spricht der Oberfeldarzt Meier...",
        #     "patient_ids": ["PAT-ABC", "PAT-DEF"],
        #     "received_at": ISO-timestamp,
        #     "unit_name":   "BAT Alpha42",
        #     "review":      None | {status, findings, ai_expected_count, ...}
        #   }
        self.sessions: dict = {}

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
    da sie nur während einer aktiven Simulation existieren sollen.

    Robust gegen File-Locks (WinError 32): wenn eine Datei gerade belegt
    ist (z.B. von einem gecrashten Vorprozess), wird sie uebersprungen.
    Beim naechsten Boot wird sie dann entweder eingelesen oder geloescht."""
    for filepath in PATIENTS_DIR.glob("*.json"):
        # Schritt 1: Lesen. Wenn File-Lock (WinError 32), sofort skip
        # und auch KEINE Loesch-Versuche — das wuerde den gleichen
        # Lock-Fehler produzieren.
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                patient = json.load(f)
        except OSError as e:
            if getattr(e, "winerror", None) == 32:
                print(f"  File-Lock auf {filepath.name} — skip (Datei wird von anderem Prozess genutzt)")
            else:
                print(f"Fehler beim Laden von {filepath.name}: {e}")
            continue
        except Exception as e:
            print(f"Fehler beim Laden von {filepath.name}: {e}")
            continue

        # Schritt 2: Verarbeiten
        pid = patient.get("patient_id")
        if not pid:
            continue
        if pid.startswith("SIM-") or pid.startswith("TEST-") or pid.startswith("P0-"):
            try:
                filepath.unlink()
                print(f"  Simulations-/Test-Patient {pid} entfernt")
            except OSError as e:
                print(f"  Konnte {pid} nicht entfernen (File-Lock?): {e}")
            continue
        state.patients[pid] = patient


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
        # Lock-Zustand sofort mitschicken damit das Frontend beim Connect
        # korrekt (ent-)sperrt darstellt. Ohne diese Felder bleibt der
        # Lock-Banner unsichtbar, auch wenn das Backend gesperrt ist.
        "locked": state.locked,
        "current_operator": state.current_operator,
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
        # Feature-Flags für die einheitliche UI. Die Surface hat KEINEN
        # eigenen Mikrofon-Input und KEIN OLED-Display — das sind
        # Jetson-spezifische Features. has_map bleibt True fuer die
        # taktische Lagekarte.
        "has_whisper": False,
        "has_vosk": False,
        "has_audio": False,
        "has_oled": False,
        "has_map": True,
        "default_page": "role1",
        # Lock-Zustand: wird vom Frontend beim initial /api/status Call
        # gelesen um Lock-Banner und Body-Klasse korrekt zu setzen.
        "locked": state.locked,
        "current_operator": state.current_operator,
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
            elif key == "rfid_tag_id" and "rfid_tag_id" in patient:
                # Explizit leerer rfid_tag_id → Karte wurde auf dem Jetson
                # geloescht (voice_erase_card). Surface muss die Zuordnung
                # aufloesen, sonst findet ein Omnikey-Scan derselben (jetzt
                # leeren) Karte weiterhin den alten Patient.
                existing["rfid_tag_id"] = ""
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

    # Session-Kontext: wenn der Jetson session_id + full_transcript
    # mitgeschickt hat, das Transkript + die Patienten-ID im Session-
    # Store ablegen. Das ist die Datenbasis fuer das spaetere LLM-
    # Review ("Fehlt ein Patient im Transkript?").
    session_id = body.get("session_id", "") or patient.get("session_id", "")
    full_transcript = body.get("full_transcript", "")
    if session_id:
        session = state.sessions.setdefault(session_id, {
            "session_id": session_id,
            "transcript": "",
            "patient_ids": [],
            "received_at": datetime.now().isoformat(),
            "unit_name": unit_name,
            "review": None,
        })
        if full_transcript and not session["transcript"]:
            session["transcript"] = full_transcript
        if pid not in session["patient_ids"]:
            session["patient_ids"].append(pid)
        session["review"] = None
        state.patients[pid]["session_id"] = session_id

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
# Security-Lock: analog zum Jetson. Blaue Operator-Chips entsperren / sperren.
# ---------------------------------------------------------------------------
def _find_operator(uid: str) -> dict | None:
    """Sucht in backend/config.json rfid.operators nach einer passenden UID.
    Gibt das Operator-Dict zurueck oder None."""
    uid_norm = (uid or "").strip().upper()
    if not uid_norm:
        return None
    cfg = load_backend_config()
    operators = (cfg.get("rfid", {}) or {}).get("operators", []) or []
    for op in operators:
        if (op.get("uid", "") or "").strip().upper() == uid_norm:
            return op
    return None


async def _handle_operator_scan(uid: str, op: dict):
    """Login/Logout-Toggle: selbe Karte auflegen = sperren + logout,
    andere Karte = direkter Wechsel zu neuem Operator."""
    import time as _t
    now_iso = datetime.now().strftime("%H:%M")
    uid_norm = (uid or "").strip().upper()
    current = state.current_operator
    print(
        f"[OPERATOR-SCAN] uid={uid_norm} op={op.get('name')} "
        f"current={current} locked={state.locked}",
        flush=True,
    )
    if current and (current.get("uid", "") or "").strip().upper() == uid_norm:
        # Gleicher Bediener scannt erneut → Logout + Sperren
        state.current_operator = None
        await _lock_system(reason="operator_logout")
        await broadcast({
            "type": "operator_logout",
            "uid": uid_norm,
            "name": op.get("name"),
        })
        add_event("operator_logout", f"Operator abgemeldet: {op.get('name', '?')}")
        return

    # Neuer Operator → ersetzen
    state.current_operator = {
        "uid": uid_norm,
        "label": op.get("label", "?"),
        "name": op.get("name", ""),
        "role": op.get("role", ""),
        "since": now_iso,
    }
    state.last_activity = _t.monotonic()
    await _unlock_system(reason="operator_login")
    await broadcast({
        "type": "operator_login",
        "uid": uid_norm,
        "label": op.get("label"),
        "name": op.get("name"),
        "role": op.get("role"),
    })
    add_event("operator_login", f"Operator angemeldet: {op.get('name', '?')} ({op.get('role', '?')})")


async def _lock_system(reason: str = "manual"):
    """Sperrt das System. Idempotent."""
    if state.locked:
        return
    state.locked = True
    print(f"[LOCK] System gesperrt (reason={reason})", flush=True)
    try:
        await broadcast({"type": "system_locked", "reason": reason})
    except Exception:
        pass


async def _unlock_system(reason: str = "manual"):
    """Entsperrt + reset Idle-Timer."""
    import time as _t
    state.locked = False
    state.last_activity = _t.monotonic()
    print(f"[UNLOCK] System entsperrt (reason={reason})", flush=True)
    try:
        await broadcast({"type": "system_unlocked", "reason": reason})
    except Exception:
        pass


async def _idle_watcher_loop():
    """Hintergrund-Task: sperrt das System nach Inaktivitaet.
    Schwelle aus backend/config.json security.lock_idle_seconds.
    Default 30 min — ueberschreibbar via Settings-UI."""
    import time as _t
    while True:
        await asyncio.sleep(30)  # alle 30 s pruefen
        if state.locked:
            continue
        if not state.current_operator:
            continue  # nur aktive Sessions auto-locken
        cfg = load_backend_config()
        threshold = int((cfg.get("security", {}) or {}).get("lock_idle_seconds", 1800))
        idle = _t.monotonic() - (state.last_activity or 0)
        if idle > threshold:
            print(f"[LOCK] Idle-Timeout ({idle:.0f}s > {threshold}s)", flush=True)
            state.current_operator = None
            await _lock_system(reason="idle_timeout")
            await broadcast({"type": "operator_logout", "uid": "", "name": "idle"})


# ---------------------------------------------------------------------------
# Omnikey RFID Lookup — Kern-Feature für die Role 1 Leitstelle
# ---------------------------------------------------------------------------
async def _handle_rfid_uid(uid: str) -> dict:
    """Routed einen RFID-Scan: erst Operator-Check, dann Patient-Lookup.

    Reihenfolge kritisch:
      1. Ist die Karte eine Operator-Karte (in rfid.operators)?
         → Login/Logout-Toggle. Kein Patient-Lookup, kein rfid_scan_result.
      2. Sonst: Patient per rfid_tag_id suchen und broadcastet
         `rfid_scan_result` mit found=True/False.
    """
    import time as _t
    uid_norm = (uid or "").strip().upper()
    # Diagnostik: immer loggen damit im Terminal sichtbar was passiert
    print(
        f"[RFID] Scan eingegangen: UID={uid_norm!r} "
        f"locked={state.locked} current_operator={state.current_operator} "
        f"scan_pending={_operator_scan_pending}",
        flush=True,
    )

    # Schritt 0 — Wenn Lern-Modus aktiv UND noch keine UID erfasst wurde:
    # UID merken und NICHT Login ausloesen. Sobald eine UID gemerkt ist,
    # fallen weitere Scans durch zu den normalen Handlern — damit die
    # gerade registrierte Karte sofort als Login funktioniert (ohne dass
    # der User die 30s des Lern-Modus abwarten muss).
    if _operator_scan_pending["active"] and _operator_scan_pending["uid"] is None:
        _operator_scan_pending["uid"] = uid_norm
        add_event("operator_scan_captured", f"Karte im Lern-Modus erfasst: {uid_norm}")
        return {"type": "operator_scan_captured", "uid": uid_norm}

    # Schritt 1 — Operator-Check (blauer Chip)
    op = _find_operator(uid_norm)
    print(f"[RFID] _find_operator({uid_norm!r}) -> {op}", flush=True)
    if op is not None:
        await _handle_operator_scan(uid_norm, op)
        return {"type": "operator_scan", "uid": uid_norm, "matched": True}

    # Schritt 2 — Patient-Lookup. Nur wenn entsperrt, sonst keine Daten-Enthuellung.
    if state.locked:
        add_event("rfid_scan_blocked", f"Karte gelesen im gesperrten Zustand: {uid_norm}")
        return {"type": "rfid_scan_result", "uid": uid_norm, "found": False, "locked": True}

    # Aktivitaets-Timer zuruecksetzen (Patient-Scan ist Aktivitaet)
    state.last_activity = _t.monotonic()

    patient = None
    patient_id = None
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
# Operator-Verwaltung: CRUD fuer rfid.operators + Scan-Hilfe fuer UI
# ---------------------------------------------------------------------------
_operator_scan_pending = {"active": False, "uid": None, "started_at": None}


@app.get("/api/operators")
async def operators_list():
    """Alle konfigurierten Operator-Karten (uid, label, name, role)."""
    cfg = load_backend_config()
    ops = (cfg.get("rfid", {}) or {}).get("operators", []) or []
    return {"operators": ops, "locked": state.locked, "current": state.current_operator}


@app.post("/api/operators")
async def operators_add(body: dict):
    """Neuen Operator in rfid.operators anhaengen.
    Body: {"uid": "AABBCC11", "label": "B1", "name": "OFw Hugendubel", "role": "arzt"}"""
    uid = (body.get("uid") or "").strip().upper()
    if not uid:
        return {"error": "uid fehlt"}
    label = (body.get("label") or "").strip() or uid[:4]
    name = (body.get("name") or "").strip() or "Unbekannt"
    role = (body.get("role") or "").strip() or "bat_soldat_1"

    cfg = load_backend_config()
    cfg.setdefault("rfid", {}).setdefault("operators", [])
    # Duplikat pruefen
    for op in cfg["rfid"]["operators"]:
        if (op.get("uid") or "").upper() == uid:
            return {"error": f"UID {uid} ist schon registriert"}
    cfg["rfid"]["operators"].append({
        "uid": uid, "label": label, "name": name, "role": role,
    })
    save_backend_config(cfg)
    add_event("operator_added", f"Neue Operator-Karte registriert: {name} ({label})")
    # Lern-Modus zuruecksetzen — damit die gerade registrierte Karte nicht
    # beim naechsten Auflegen erneut als Lern-UID abgefangen wird, sondern
    # direkt als Login funktioniert.
    _operator_scan_pending["active"] = False
    _operator_scan_pending["uid"] = None
    # Bei erster Operator-Karte: Lock aktivieren (ab jetzt mit Auth)
    if len(cfg["rfid"]["operators"]) == 1 and not state.locked:
        state.locked = True
        await broadcast({"type": "system_locked", "reason": "first_operator_registered"})
    return {"status": "ok", "operators": cfg["rfid"]["operators"]}


@app.delete("/api/operators/{uid}")
async def operators_delete(uid: str):
    """Entfernt einen Operator aus rfid.operators."""
    uid_norm = uid.strip().upper()
    cfg = load_backend_config()
    ops = cfg.setdefault("rfid", {}).setdefault("operators", [])
    before = len(ops)
    cfg["rfid"]["operators"] = [o for o in ops if (o.get("uid") or "").upper() != uid_norm]
    removed = before - len(cfg["rfid"]["operators"])
    if removed == 0:
        return {"error": f"UID {uid_norm} nicht gefunden"}
    save_backend_config(cfg)
    add_event("operator_removed", f"Operator-Karte entfernt: {uid_norm}")
    # Falls aktueller Operator geloescht wurde → sofort abmelden
    if state.current_operator and (state.current_operator.get("uid") or "").upper() == uid_norm:
        state.current_operator = None
        await _lock_system(reason="operator_deleted")
        await broadcast({"type": "operator_logout", "uid": uid_norm, "name": "removed"})
    return {"status": "ok", "removed": removed, "operators": cfg["rfid"]["operators"]}


@app.post("/api/operators/scan-start")
async def operators_scan_start():
    """Startet den Karten-Lern-Modus: die naechste am Omnikey gelesene UID
    wird gemerkt (nicht Login-triggert) und kann per /api/operators/scan-status
    abgefragt werden. Frontend baut darauf den Registrierungs-Dialog.
    Timeout: 30 Sekunden."""
    import time as _t
    _operator_scan_pending["active"] = True
    _operator_scan_pending["uid"] = None
    _operator_scan_pending["started_at"] = _t.monotonic()
    return {"status": "ok", "timeout_seconds": 30}


@app.get("/api/operators/scan-status")
async def operators_scan_status():
    """Gibt die letzte gescannte UID zurueck (oder null wenn noch keine).
    Frontend polled alle 500ms bis UID da ist oder Timeout eintritt."""
    import time as _t
    if not _operator_scan_pending["active"]:
        return {"active": False, "uid": None}
    elapsed = _t.monotonic() - (_operator_scan_pending["started_at"] or 0)
    if elapsed > 30:
        _operator_scan_pending["active"] = False
        return {"active": False, "uid": None, "timeout": True}
    return {
        "active": True,
        "uid": _operator_scan_pending["uid"],
        "elapsed_seconds": round(elapsed, 1),
    }


@app.post("/api/operators/scan-cancel")
async def operators_scan_cancel():
    """Bricht den Lern-Modus ab."""
    _operator_scan_pending["active"] = False
    _operator_scan_pending["uid"] = None
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# LLM-Review: Fehlender-Patient-Detection via Gemma 4 auf der Surface
# ---------------------------------------------------------------------------
# Der Jetson koennte bei konversationellen Unterbrechungen oder neuen
# Sprach-Mustern Patienten uebersehen. Die Surface hat ein staerkeres
# LLM (Gemma 4 E4B) und nutzt es als Zweit-Check: Bekommt das Original-
# Transkript plus die vom Jetson extrahierten Patient-Namen und prueft,
# ob im Transkript noch weitere Personen beschrieben werden.
#
# Bewusst konservativ:
#  - Keine Aenderung an Patient-Daten (nur "findings", die der Arzt
#    sichtbar bekommt)
#  - LLM-Antwort wird ins Session-Dict persistiert, damit kein doppelter
#    Aufruf passiert
#  - Prompt ist strikt formatiert mit JSON-Output, damit Halluzinationen
#    downstream nicht durchrutschen

OLLAMA_SURFACE_URL = "http://127.0.0.1:11434"
OLLAMA_SURFACE_MODEL = "gemma4:e4b"

SESSION_REVIEW_PROMPT = """Du bist klinischer Qualitaetssicherungs-Assistent im Bundeswehr-Sanitaetsdienst.
Du pruefst die Arbeit eines Feld-KI-Extraktors gegen das Original-Transkript.

TRANSKRIPT (Original-Diktat des Sanitaeters):
---
{transcript}
---

EXTRAKTOR-OUTPUT (was die Feld-KI aus dem Transkript herausgeholt hat):
{extracted_list}

PRUEFE DREI DINGE:

1) FEHLENDE PATIENTEN — gibt es Personen im Transkript die komplett fehlen?
   (Intros wie "Hier spricht Oberfeldarzt X" zaehlen NICHT als Patient.
    Fortsetzungen wie "Er hat auch..." zaehlen NICHT als neuer Patient.)

2) FEHLENDE FELDER — nennt das Transkript einen KONKRETEN WERT
   (Zahl mit Einheit, z.B. "Puls 140", "SpO2 90 Prozent", "RR 120/80",
    "Atmung 18", "GCS 12"), der bei einem extrahierten Patient aber
    leer ist?

   MELDE NUR WENN:
   - Eine konkrete Zahl im Transkript steht UND
   - Das entsprechende Feld im Patient-Record leer/fehlt.

   NICHT MELDEN WENN:
   - Im Transkript steht nur eine allgemeine Beschreibung ("blutet stark",
     "sieht schlecht aus") ohne Messwert.
   - Das Transkript sagt gar nichts zu diesem Feld.
   - Die Verletzungen/Name/Rang sind schon extrahiert.

3) FALSCHE ZUORDNUNG — hat die Feld-KI Daten dem FALSCHEN Patient
   zugeschrieben?

   Beispiel: Transkript sagt "Marius hat Puls 140", aber Puls 140
   steht bei Hubert im Patient-Record. Oder: Transkript sagt "Erika
   hat Rippenfraktur", aber Rippenfraktur landete bei Marius.

WICHTIGE REGELN:
- KONSERVATIV sein: im Zweifel NICHT melden.
- Jeder Fund braucht ein KONKRETES Transkript-Zitat als evidence.
- Das evidence-Zitat muss den WORTWOERTLICHEN Text aus dem Transkript
  enthalten (keine Zusammenfassung). Wenn du den Text nicht aus dem
  Transkript zitieren kannst, MELDE NICHT.
- Keine Spekulation ueber "was haette noch gesagt werden koennen".

BEISPIELE wie du (NICHT) melden sollst:

Beispiel A — NICHT melden:
  Transkript: "Erika hat Nasenbluten."
  Patient Erika hat: injuries=[Nasenbluten], vitals=leer
  -> status=ok, keine Meldung. Transkript nennt keine Vitals-Zahl fuer
     Erika, also keine Luecke.

Beispiel B — MELDEN:
  Transkript: "Marius hat drei Schusswunden. Puls 140, SpO2 90 Prozent."
  Patient Marius hat: injuries=[Schusswunden], vitals=leer
  -> status=issues, missing_fields enthaelt zwei Eintraege:
     (patient=Marius, field=pulse, value_from_transcript=140,
      evidence=Puls 140)
     (patient=Marius, field=spo2, value_from_transcript=90,
      evidence=SpO2 90 Prozent)

Beispiel C — MELDEN (falsche Zuordnung):
  Transkript: "Patient Marius hat Schusswunden. Puls 140. Naechster
               Patient Hubert hat Gehirnerschuetterung."
  Marius.vitals ist leer, Hubert.vitals.pulse=140
  -> status=issues, wrong_assignment enthaelt:
     (field=pulse, patient_should_be=Marius, patient_current=Hubert,
      evidence=Puls 140 steht direkt nach dem Marius-Abschnitt)

Antworte AUSSCHLIESSLICH mit gueltigem JSON im exakten Format:

{{
  "expected_patients": <zahl>,
  "extracted_count": <zahl>,
  "status": "ok" oder "issues",
  "missing": [
    {{"description": "Wer fehlt (Name/Rang/Verletzung)", "evidence": "Zitat"}}
  ],
  "missing_fields": [
    {{"patient": "Patient-Name", "field": "pulse|injuries|...", "value_from_transcript": "der Wert aus dem Transkript", "evidence": "Zitat"}}
  ],
  "wrong_assignment": [
    {{"patient_should_be": "Name", "patient_current": "Name", "field": "feld-name", "evidence": "Zitat"}}
  ]
}}

Bei status="ok": alle drei Listen leer.
Bei status="issues": mindestens EIN Eintrag in einer der Listen.
Antworte NUR mit dem JSON, keine Erklaerung davor oder danach.
"""


@app.post("/api/llm/review-session")
async def llm_review_session(body: dict):
    """Loest eine Session-Review via Gemma 4 (oder konfiguriertem Modell)
    auf der Surface aus. Body: {"session_id": "..."} oder implizit die
    aktuellste Session wenn leer.

    Ablauf:
      1. Session + Transkript aus state.sessions holen
      2. Liste der extrahierten Patienten formatieren
      3. Gemma 4 aufrufen (Ollama-API)
      4. JSON aus Response parsen (defensiv)
      5. Ergebnis in session["review"] speichern + broadcasten
    """
    import httpx as _httpx
    import json as _json
    import re as _re
    import time as _time

    session_id = (body.get("session_id") or "").strip()
    if not session_id:
        # Ohne session_id: neueste Session nehmen
        if not state.sessions:
            return {"error": "Keine Sessions vorhanden"}
        session_id = max(state.sessions.keys(),
                         key=lambda k: state.sessions[k].get("received_at", ""))

    session = state.sessions.get(session_id)
    if not session:
        return {"error": f"Session {session_id} nicht gefunden"}

    transcript = (session.get("transcript") or "").strip()
    if not transcript:
        return {"error": "Kein Transkript in dieser Session"}

    # Extrahierte Patienten des Jetsons formatieren
    extracted_list_lines = []
    for pid in session.get("patient_ids", []):
        p = state.patients.get(pid)
        if not p:
            continue
        name = (p.get("name") or "Unbekannt").strip()
        rank = (p.get("rank") or "").strip()
        injs = ", ".join(p.get("injuries") or [])
        label = f"- {rank} {name}".strip() if rank else f"- {name}"
        if injs:
            label += f" ({injs})"
        extracted_list_lines.append(label)
    extracted_block = "\n".join(extracted_list_lines) if extracted_list_lines else "(keine)"

    prompt = SESSION_REVIEW_PROMPT.format(
        transcript=transcript,
        extracted_list=extracted_block,
    )

    start = _time.monotonic()
    try:
        response = _httpx.post(
            f"{OLLAMA_SURFACE_URL}/api/chat",
            json={
                "model": OLLAMA_SURFACE_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "format": "json",
                # Thinking bei Gemma 4 deaktivieren damit der Token-Output
                # direkt ins JSON geht statt in interne Chain-of-Thought.
                # "think": False ist ein neueres Ollama-Feature; wenn
                # nicht unterstuetzt wird der Param ignoriert.
                "think": False,
                "options": {
                    "temperature": 0.1,
                    # Reasoning-Model braucht deutlich mehr Output-Budget
                    # als ein klassisches LLM. 2048 reicht fuer das
                    # JSON-Schema auch bei 3-4 Findings.
                    "num_predict": 2048,
                    "num_ctx": 4096,
                },
            },
            timeout=180,
        )
    except Exception as e:
        return {"error": f"Ollama nicht erreichbar: {e}"}

    elapsed = _time.monotonic() - start
    if response.status_code != 200:
        return {"error": f"Ollama HTTP {response.status_code}: {response.text[:200]}"}

    raw = response.json()
    raw_content = (raw.get("message") or {}).get("content", "").strip()
    # JSON robust parsen — Gemma 4 kann auch Reasoning-Text anhaengen
    parsed = None
    try:
        parsed = _json.loads(raw_content)
    except _json.JSONDecodeError:
        # Regex-Fallback: ersten {...}-Block suchen
        match = _re.search(r"\{.*\}", raw_content, _re.DOTALL)
        if match:
            try:
                parsed = _json.loads(match.group(0))
            except _json.JSONDecodeError:
                pass

    if not isinstance(parsed, dict):
        # LLM-Antwort nicht parsebar — als Warnung persistieren, damit
        # das Frontend wenigstens etwas anzeigen kann.
        review_result = {
            "status": "error",
            "error": "LLM-Antwort nicht als JSON parsebar",
            "raw_response": raw_content[:500],
            "elapsed_s": round(elapsed, 1),
            "model": OLLAMA_SURFACE_MODEL,
        }
    else:
        # Backward-compat: altes Schema hatte status="missing" — wir
        # normalisieren auf "issues" wenn irgendetwas gefunden wurde.
        missing = parsed.get("missing", []) or []
        missing_fields = parsed.get("missing_fields", []) or []
        wrong_assignment = parsed.get("wrong_assignment", []) or []
        raw_status = (parsed.get("status") or "").lower()
        if raw_status in ("missing", "issues") or missing or missing_fields or wrong_assignment:
            norm_status = "issues"
        else:
            norm_status = "ok"
        review_result = {
            "status": norm_status,
            "expected_patients": parsed.get("expected_patients"),
            "extracted_count": parsed.get("extracted_count", len(session["patient_ids"])),
            "missing": missing,
            "missing_fields": missing_fields,
            "wrong_assignment": wrong_assignment,
            "elapsed_s": round(elapsed, 1),
            "model": OLLAMA_SURFACE_MODEL,
            "reviewed_at": datetime.now().isoformat(),
        }

    session["review"] = review_result
    add_event(
        "llm_review",
        f"Session-Review {session_id}: {review_result['status']} "
        f"({review_result.get('expected_patients', '?')} erwartet, "
        f"{review_result.get('extracted_count', '?')} extrahiert, "
        f"{elapsed:.1f}s)",
    )
    await broadcast({
        "type": "session_review_done",
        "session_id": session_id,
        "review": review_result,
    })
    return {"session_id": session_id, "review": review_result}


@app.get("/api/sessions")
async def list_sessions():
    """Alle Jetson-Diktat-Sessions mit Transkript + Patient-IDs + Review-Status.
    Sortiert mit neuster Session zuerst."""
    sessions = list(state.sessions.values())
    sessions.sort(key=lambda s: s.get("received_at", ""), reverse=True)
    return {"sessions": sessions}


@app.post("/api/bat/route-broadcast")
async def bat_route_broadcast(body: dict):
    """Wird vom Jetson beim Start einer Rueckfahrt aufgerufen. Enthaelt
    die OSRM-Strassenroute als Liste von [lat, lon]-Paaren. Leitet das
    als bat_returning-Event an alle Browser-Clients (Surface-Lagekarte)
    damit diese die echte Strassen-Polylinie zeichnen koennen statt
    einer Luftlinie."""
    unit_name = body.get("unit_name", "BAT")
    route = body.get("route") or []
    await broadcast({
        "type": "bat_returning",
        "unit_name": unit_name,
        "start_lat": body.get("start_lat"),
        "start_lon": body.get("start_lon"),
        "destination_lat": body.get("destination_lat"),
        "destination_lon": body.get("destination_lon"),
        "route": route,
        "route_source": "osrm" if route else "straight",
    })
    add_event(
        "bat_returning",
        f"{unit_name}: Rueckfahrt zur Rettungsstation gestartet "
        f"({'echte Strassenroute' if route else 'Luftlinie'})",
    )
    return {"status": "ok", "broadcast_to": len(state.ws_clients)}


@app.post("/api/rfid/clear-tag")
async def rfid_clear_tag(body: dict):
    """Loest die rfid_tag_id-Zuordnung auf dem Surface explizit auf.
    Wird vom Jetson nach einem erfolgreichen Erase aufgerufen.

    Vorteile gegenueber /api/ingest mit leerem rfid_tag_id:
      - Unabhaengig von der Merge-Logik (funktioniert auch wenn der
        Surface gerade noch mit altem Code laeuft, solange dieser
        Endpoint existiert).
      - Schreibt save_patient sofort nach der Aenderung, damit der
        Zustand auch nach einem Surface-Restart erhalten bleibt.
      - Broadcastet patient_update damit die Frontend-Ansicht sofort
        aktualisiert.

    Body: {"uid": "8AEF10C3"}  — Mehrere Patienten mit derselben UID
    (sollte nicht vorkommen, aber defensive Programmierung) werden
    alle bereinigt.
    """
    uid = (body.get("uid") or "").strip().upper()
    if not uid:
        return {"status": "error", "error": "uid fehlt"}
    cleared = []
    for pid, p in list(state.patients.items()):
        tag = (p.get("rfid_tag_id") or "").strip().upper()
        if tag == uid:
            p["rfid_tag_id"] = ""
            save_patient(p)
            cleared.append(pid)
            await broadcast({"type": "patient_update", "patient": p})
    if cleared:
        add_event(
            "rfid_erased",
            f"Karte UID {uid} auf Feldgeraet geloescht — {len(cleared)} Zuordnung(en) aufgeloest",
        )
    return {"status": "ok", "uid": uid, "cleared": cleared}


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
# Simulation: Reset (entfernt — Demo-Story laeuft jetzt aus dem BAT-Geraet
# selbst via /api/position aus Phase 3 des Implementierungsplans)
# ---------------------------------------------------------------------------


@app.post("/api/data/reset")
async def data_reset(body: dict | None = None):
    """Löscht ALLE Patientendaten, Transporte, Positionen, Events und
    den Peer-Cache. Für einen sauberen Demo-Neustart. WebSocket-Clients
    werden bewusst NICHT angefasst, sonst brechen aktive Browser-Sessions ab.

    body.cascade=True (Default): Ruft den Reset-Endpoint aller bekannten
    Peers (Jetson-BATs) auf, damit sie ebenfalls ihren lokalen State
    leeren. Wird vom Jetson selbst mit cascade=False aufgerufen um
    Rekursion zu vermeiden.
    """
    cascade = True if body is None else bool(body.get("cascade", True))

    # Alle Patienten-Dateien löschen
    count = len(state.patients)
    peer_count = len(state.peers)
    for filepath in PATIENTS_DIR.glob("*.json"):
        filepath.unlink()
    state.patients.clear()

    # Transporte, Positionen, Events, Peers leeren
    state.transports.clear()
    state.positions.clear()
    state.events.clear()
    # Session-Store (Jetson-Diktat-Transkripte + LLM-Reviews) auch
    # bereinigen — sonst bleiben Review-Ergebnisse fuer nicht-existente
    # Patienten haengen.
    state.sessions.clear()
    peer_snapshot = list(state.peers.values())
    state.peers.clear()

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

    # Cascade an alle bekannten Jetson-Peers — damit die ihren lokalen
    # State ebenfalls leeren. Ohne das landet beim naechsten Heartbeat-
    # Sync alte Jetson-Daten wieder hier.
    cascaded_count = 0
    if cascade:
        import httpx
        for peer in peer_snapshot:
            peer_url = peer.get("url") or ""
            if not peer_url:
                continue
            try:
                r = httpx.post(f"{peer_url}/api/data/reset",
                               json={"cascade": False}, timeout=3)
                if r.status_code == 200:
                    cascaded_count += 1
            except Exception as e:
                print(f"[RESET] Cascade an {peer_url} fehlgeschlagen: {e}")

    print(f"Daten-Reset: {count} Patienten, {peer_count} Peers gelöscht"
          + (f", {cascaded_count} Peer(s) kaskadiert" if cascade else ""))
    return {"status": "ok", "removed": count, "peers_removed": peer_count,
            "cascaded": cascaded_count if cascade else 0}


@app.post("/api/data/test-generate")
async def data_test_generate():
    """Erzeugt Test-Patienten + Test-BAT in der Leitstelle, damit die
    Lagekarte und Patient-Liste ohne echten Jetson demonstrierbar sind.
    Patient-IDs haben TEST- Prefix."""
    import uuid as _uuid
    now = datetime.now().isoformat()

    # Test-Patienten — Surface-Sicht: alle bereits gemeldet (synced), in
    # Role 1 angekommen, mit gesetzter Triage (oder noch ohne).
    test_data = [
        # Patient-Tupel: (name, rank, triage, injuries, vitals, current_role)
        ("Markus Hoffmann",  "Hauptgefreiter",     "T2", ["Knie-Trauma li.", "Schwellung"],
            {"pulse": "92", "spo2": "97"}, "role1"),
        ("Andrea Wenzel",    "Soldatin",           "T3", ["Schnittwunde Unterarm"],
            {"pulse": "78", "spo2": "98"}, "role1"),
        ("Stefan Becker",    "Stabsunteroffizier", "T2", ["Splitterverletzung Oberschenkel"],
            {"pulse": "98", "spo2": "94", "bp": "110/70"}, "role1"),
        ("Lea Schwarz",      "Hauptgefreite",      "T1", ["Prellung Brustkorb", "Atemnot"],
            {"pulse": "115", "spo2": "89", "resp_rate": "24"}, "role1"),
        ("Tobias Krueger",   "Feldwebel",          "T1", ["Schussverletzung Bein", "Tourniquet"],
            {"pulse": "132", "spo2": "92", "bp": "95/60"}, "role1"),
        ("Julia Mueller",    "Oberleutnant",       "T2", ["Kopfprellung", "Beinfraktur"],
            {"pulse": "88", "spo2": "97", "bp": "120/80", "gcs": "14"}, "role1"),
    ]

    created_ids = []
    for name, rank, triage, injuries, vitals, role in test_data:
        pid = f"TEST-{_uuid.uuid4().hex[:8].upper()}"
        patient = {
            "patient_id": pid,
            "timestamp_created": now,
            "current_role": role,
            "flow_status": "reported",
            "synced": True,
            "analyzed": True,
            "rfid_tag_id": "",
            "device_id": "test-generator",
            "created_by": "Test-Generator",
            "name": name,
            "rank": rank,
            "unit": "BAT TestAlpha",
            "triage": triage,
            "status": "stable",
            "injuries": injuries,
            "vitals": vitals,
            "treatments": [],
            "medications": [],
            "transcripts": [],
            "audio_files": [],
            "handovers": [],
            "timeline": [{
                "time": now, "role": role, "event": "test_generated",
                "details": "Test-Patient generiert (data/test-generate)",
            }],
        }
        state.patients[pid] = patient
        save_patient(patient)
        created_ids.append(pid)

    # Plus: Ein Test-BAT auf der Karte (Position bei Bonn-Endenich)
    state.peers["test-bat-01"] = {
        "device_id": "test-bat-01",
        "unit_name": "BAT TestAlpha",
        "unit_role": "BAT",
        "system_name": "Test-Generator",
        "ip": "0.0.0.0",
        "port": 0,
        "last_seen": now,
        "patient_count": len(test_data),
    }
    state.positions["BAT TestAlpha"] = {
        "lat": 50.7251, "lon": 7.0644,  # Bonn-Endenich
        "heading": 0, "speed_kmh": 0,
        "device_id": "test-bat-01",
        "timestamp": now,
    }
    save_state()

    await broadcast({
        "type": "init",
        "patients": list(state.patients.values()),
        "transports": state.transports,
        "positions": state.positions,
        "events": state.events,
    })
    print(f"Test-Daten generiert: {len(created_ids)} Patient(en) + 1 Test-BAT")
    return {"status": "ok", "created": len(created_ids), "patient_ids": created_ids}


# ---------------------------------------------------------------------------
# Export & Interoperabilität (Phase 6) — nutzt shared.exports damit das
# Surface-Backend dieselbe Logik wie das Jetson-Backend hat. Die vier
# Endpoints sind identisch zu denen im Jetson app.py, aber auf
# state.patients des Surface-Backends.
# ---------------------------------------------------------------------------
PROTOCOLS_DIR_EXPORT = ROOT_DIR / "backend" / "data" / "exports"
PROTOCOLS_DIR_EXPORT.mkdir(exist_ok=True, parents=True)


def _export_cfg() -> tuple[str, str]:
    """Liefert (device_id, unit_name) aus der Surface-Config für Exports."""
    try:
        cfg_path = PROJECT_DIR / "config.json"
        if cfg_path.exists():
            with open(cfg_path, encoding="utf-8") as f:
                cfg = json.load(f)
            return cfg.get("device_id", "surface-01"), cfg.get("unit_name", "Leitstelle")
    except Exception:
        pass
    return "surface-01", "Leitstelle"


def _export_filename(ext: str) -> str:
    return f"safir-patients-{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"


@app.get("/api/export/json/all")
async def export_json_all():
    device_id, unit_name = _export_cfg()
    body = exports.generate_json(list(state.patients.values()), device_id, unit_name)
    return Response(
        content=body,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{_export_filename("json")}"'},
    )


@app.get("/api/export/xml/all")
async def export_xml_all():
    device_id, unit_name = _export_cfg()
    body = exports.generate_xml(list(state.patients.values()), device_id, unit_name)
    return Response(
        content=body,
        media_type="application/xml; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{_export_filename("xml")}"'},
    )


@app.post("/api/export/docx/all")
async def export_docx_all():
    device_id, unit_name = _export_cfg()
    try:
        filepath = exports.generate_docx(
            list(state.patients.values()), device_id, unit_name, PROTOCOLS_DIR_EXPORT
        )
    except ImportError as e:
        # WICHTIG: HTTP 503 statt 200! Das Frontend speichert sonst
        # den JSON-Error-Body als vermeintliches .docx und erzeugt
        # eine ungueltige Datei.
        return Response(
            content=json.dumps({
                "error": "python-docx nicht installiert",
                "hint": "pip install python-docx im Surface-Python",
                "detail": str(e),
            }),
            status_code=503,
            media_type="application/json",
        )
    except Exception as e:
        return Response(
            content=json.dumps({"error": f"DOCX-Export fehlgeschlagen: {e}"}),
            status_code=500,
            media_type="application/json",
        )
    return FileResponse(
        str(filepath),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filepath.name,
    )


@app.post("/api/export/pdf/all")
async def export_pdf_all():
    device_id, unit_name = _export_cfg()
    try:
        filepath = exports.generate_pdf(
            list(state.patients.values()), device_id, unit_name, PROTOCOLS_DIR_EXPORT
        )
    except ImportError as e:
        return Response(
            content=json.dumps({
                "error": "reportlab nicht installiert",
                "hint": "pip install reportlab im Surface-Python",
                "detail": str(e),
            }),
            status_code=503,
            media_type="application/json",
        )
    except Exception as e:
        return Response(
            content=json.dumps({"error": f"PDF-Export fehlgeschlagen: {e}"}),
            status_code=500,
            media_type="application/json",
        )
    return FileResponse(
        str(filepath),
        media_type="application/pdf",
        filename=filepath.name,
    )


@app.post("/api/export/docx/patient/{patient_id}")
async def export_docx_single(patient_id: str):
    """Einzelpatient als DOCX. Nutzt denselben Generator wie der
    Alle-Patienten-Export, nur mit Patient-Liste der Laenge 1."""
    device_id, unit_name = _export_cfg()
    patient = state.patients.get(patient_id)
    if not patient:
        return Response(
            content=json.dumps({"error": f"Patient {patient_id} nicht gefunden"}),
            status_code=404,
            media_type="application/json",
        )
    try:
        filepath = exports.generate_docx(
            [patient], device_id, unit_name, PROTOCOLS_DIR_EXPORT
        )
    except ImportError as e:
        return Response(
            content=json.dumps({"error": "python-docx nicht installiert", "detail": str(e)}),
            status_code=503, media_type="application/json",
        )
    except Exception as e:
        return Response(
            content=json.dumps({"error": f"DOCX-Export fehlgeschlagen: {e}"}),
            status_code=500, media_type="application/json",
        )
    return FileResponse(
        str(filepath),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filepath.name,
    )


@app.post("/api/export/pdf/patient/{patient_id}")
async def export_pdf_single(patient_id: str):
    """Einzelpatient als PDF."""
    device_id, unit_name = _export_cfg()
    patient = state.patients.get(patient_id)
    if not patient:
        return Response(
            content=json.dumps({"error": f"Patient {patient_id} nicht gefunden"}),
            status_code=404,
            media_type="application/json",
        )
    try:
        filepath = exports.generate_pdf(
            [patient], device_id, unit_name, PROTOCOLS_DIR_EXPORT
        )
    except ImportError as e:
        return Response(
            content=json.dumps({"error": "reportlab nicht installiert", "detail": str(e)}),
            status_code=503, media_type="application/json",
        )
    except Exception as e:
        return Response(
            content=json.dumps({"error": f"PDF-Export fehlgeschlagen: {e}"}),
            status_code=500, media_type="application/json",
        )
    return FileResponse(
        str(filepath),
        media_type="application/pdf",
        filename=filepath.name,
    )


@app.get("/api/export/list")
async def export_list():
    """Liste aller bereits erzeugten Export-Dateien (docx/pdf/json/xml).
    Sortiert nach Modification-Time, neuste zuerst."""
    items = []
    if PROTOCOLS_DIR_EXPORT.exists():
        for fp in PROTOCOLS_DIR_EXPORT.iterdir():
            if not fp.is_file():
                continue
            stat = fp.stat()
            items.append({
                "filename": fp.name,
                "size": stat.st_size,
                "mtime": stat.st_mtime,
                "mtime_iso": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "extension": fp.suffix.lstrip(".").lower(),
            })
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return {"files": items, "total": len(items)}


@app.get("/api/export/download/{filename}")
async def export_download(filename: str):
    """Download einer bereits erzeugten Export-Datei. Schuetzt gegen
    Path-Traversal (nur Dateien direkt im exports-Ordner, kein ..)."""
    # Path-Traversal-Schutz: nur der Basename zaehlt
    safe_name = Path(filename).name
    fp = PROTOCOLS_DIR_EXPORT / safe_name
    if not fp.exists() or not fp.is_file():
        return Response(
            content=json.dumps({"error": f"Datei {safe_name} nicht gefunden"}),
            status_code=404, media_type="application/json",
        )
    # Media-Type je nach Endung
    ext = fp.suffix.lstrip(".").lower()
    media_types = {
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pdf": "application/pdf",
        "json": "application/json",
        "xml": "application/xml",
    }
    return FileResponse(
        str(fp),
        media_type=media_types.get(ext, "application/octet-stream"),
        filename=fp.name,
    )


@app.delete("/api/export/delete/{filename}")
async def export_delete(filename: str):
    """Loescht eine Export-Datei. Path-Traversal-Schutz wie beim Download."""
    safe_name = Path(filename).name
    fp = PROTOCOLS_DIR_EXPORT / safe_name
    if not fp.exists() or not fp.is_file():
        return Response(
            content=json.dumps({"error": f"Datei {safe_name} nicht gefunden"}),
            status_code=404, media_type="application/json",
        )
    try:
        fp.unlink()
    except Exception as e:
        return Response(
            content=json.dumps({"error": f"Loeschen fehlgeschlagen: {e}"}),
            status_code=500, media_type="application/json",
        )
    return {"status": "ok", "deleted": safe_name}


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
    # Security-Lock Idle-Watcher: sperrt System nach lock_idle_seconds Inaktivitaet
    asyncio.create_task(_idle_watcher_loop())

    # Start-Zustand: gesperrt. User muss Operator-Karte am Omnikey auflegen.
    # Gilt nur wenn Operators ueberhaupt konfiguriert sind — sonst Open-Mode
    # fuer Entwicklung/Demo ohne Operator-Pflicht.
    _cfg = load_backend_config()
    _ops = (_cfg.get("rfid", {}) or {}).get("operators", []) or []
    if _ops:
        state.locked = True
        print(f"  Security-Lock aktiv ({len(_ops)} Operator-Karten konfiguriert)")
    else:
        state.locked = False
        print(f"  Security-Lock deaktiviert (keine Operator-Karten in config.json)")

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
