#!/usr/bin/env python3
"""
CGI AFCEA San-Feldeinsatz — Web-Dashboard
FastAPI Backend mit WebSocket, Templates und Vosk-Sprachsteuerung.
"""

import asyncio
import json
import logging
import os
import subprocess
import tempfile
import time
import threading

# Logging für SAFIR-interne Logger (safir.hardware, safir.rfid, ...)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s: %(message)s",
)
from datetime import datetime
from pathlib import Path

import numpy as np
import psutil
import sounddevice as sd
import soundfile as sf
from docx import Document
from docx.shared import Pt, Mm, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

import copy
import signal
import httpx

from shared.rfid import generate_patient_id, generate_rfid_tag, lookup_by_rfid, create_patient_record
from shared.models import PATIENT_SCHEMA, TRANSFER_SCHEMA, PatientFlowStatus, FLOW_STATUS_LABELS, TRIAGE_COLORS
from shared import tts
from shared import sitaware
from jetson.oled import oled_menu
from jetson.hardware import HardwareService, SystemState

PROJECT_DIR = Path(__file__).parent
CONFIG_PATH = PROJECT_DIR / "config.json"
WHISPER_CLI = PROJECT_DIR / "whisper.cpp" / "build" / "bin" / "whisper-cli"
WHISPER_SERVER = PROJECT_DIR / "whisper.cpp" / "build" / "bin" / "whisper-server"
MODELS_DIR = PROJECT_DIR / "models"
PROTOCOLS_DIR = PROJECT_DIR / "protocols"
PROTOCOLS_DIR.mkdir(exist_ok=True)
VOSK_MODEL_PATH = MODELS_DIR / "vosk-model-small-de"

SAMPLE_RATE = 16000


# ---------------------------------------------------------------------------
# Konfiguration aus config.json laden
# ---------------------------------------------------------------------------
def load_config() -> dict:
    """Lädt Konfiguration aus config.json."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(cfg: dict):
    """Speichert Konfiguration in config.json."""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)


def build_voice_commands(cfg: dict) -> dict:
    """Baut VOICE_COMMANDS dict aus config.json voice_commands."""
    vc = cfg.get("voice_commands", {})
    commands = {}
    for action_id, action_data in vc.items():
        for trigger in action_data.get("triggers", []):
            commands[trigger.lower().strip()] = action_id
    return commands


_config = load_config()
WHISPER_SERVER_PORT = _config.get("whisper", {}).get("server_port", 8178)
OLLAMA_URL = _config.get("ollama", {}).get("url", "http://127.0.0.1:11434")
OLLAMA_MODEL = _config.get("ollama", {}).get("model", "qwen2.5:1.5b")
VOICE_COMMANDS = build_voice_commands(_config)

app = FastAPI(title="CGI San-Feldeinsatz")
app.mount("/static", StaticFiles(directory=str(PROJECT_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(PROJECT_DIR / "templates"))


# ---------------------------------------------------------------------------
# Templates für Patientenakten
# ---------------------------------------------------------------------------
RECORD_TEMPLATES = {
    "tccc": {
        "id": "tccc",
        "name": "TCCC Card",
        "description": "Tactical Combat Casualty Care — Verwundetenkarte",
        "icon": "&#9764;",
        "sections": [
            {
                "title": "Triage",
                "fields": [
                    {"key": "triage_cat", "label": "Triage-Kategorie", "type": "select",
                     "options": ["T1 — Sofort (Rot)", "T2 — Aufgeschoben (Gelb)", "T3 — Leicht (Grün)", "T4 — Abwartend (Blau)"]},
                    {"key": "triage_time", "label": "Zeitpunkt Sichtung", "type": "text", "default": ""},
                    {"key": "evac_priority", "label": "Transportpriorität", "type": "select",
                     "options": ["Urgent", "Urgent Surgical", "Priority", "Routine"]},
                ],
            },
            {
                "title": "Verletzung",
                "fields": [
                    {"key": "mechanism", "label": "Mechanismus", "type": "multiselect",
                     "options": ["Schuss (GSW)", "IED/Explosion", "Splitter", "Verbrennung", "Sturz", "Stumpfes Trauma", "Mine", "Granate", "Fahrzeugunfall", "Sonstiges"]},
                    {"key": "injury_location", "label": "Verletzungsort", "type": "text", "default": ""},
                    {"key": "injury_type", "label": "Verletzungsart", "type": "multiselect",
                     "options": ["Verwundung", "Verbrennung", "Erkrankung", "Vergiftung", "Strahlung", "Psych. Belastung"]},
                ],
            },
            {
                "title": "Vitalzeichen",
                "fields": [
                    {"key": "pulse", "label": "Puls (bpm)", "type": "text", "default": ""},
                    {"key": "bp", "label": "Blutdruck (sys/dia)", "type": "text", "default": ""},
                    {"key": "resp_rate", "label": "Atemfrequenz (/min)", "type": "text", "default": ""},
                    {"key": "spo2", "label": "SpO2 (%)", "type": "text", "default": ""},
                    {"key": "avpu", "label": "Bewusstsein (AVPU)", "type": "select",
                     "options": ["A — Wach", "V — Reagiert auf Ansprache", "P — Reagiert auf Schmerz", "U — Bewusstlos"]},
                    {"key": "pain", "label": "Schmerz (0-10)", "type": "text", "default": ""},
                ],
            },
            {
                "title": "Behandlung",
                "fields": [
                    {"key": "tourniquet", "label": "Tourniquet", "type": "text", "default": ""},
                    {"key": "tourniquet_time", "label": "TQ-Zeit", "type": "text", "default": ""},
                    {"key": "hemostatic", "label": "Hämostatikum / Verband", "type": "text", "default": ""},
                    {"key": "airway", "label": "Atemwegssicherung", "type": "select",
                     "options": ["Keine", "NPA", "SGA", "Endotracheal", "Koniotomie"]},
                    {"key": "chest_seal", "label": "Chest Seal / Thorax", "type": "text", "default": ""},
                    {"key": "iv_io", "label": "Zugang (IV/IO)", "type": "text", "default": ""},
                    {"key": "fluids", "label": "Infusionen", "type": "text", "default": ""},
                    {"key": "medications", "label": "Medikamente", "type": "textarea", "default": ""},
                    {"key": "splint", "label": "Schienung", "type": "text", "default": ""},
                ],
            },
        ],
    },
    "9liner": {
        "id": "9liner",
        "name": "9-Liner MEDEVAC",
        "description": "NATO MEDEVAC-Anforderung",
        "icon": "&#9992;",
        "sections": [
            {
                "title": "MEDEVAC Request",
                "fields": [
                    {"key": "line1", "label": "Line 1 — Koordinaten Landezone", "type": "text", "default": ""},
                    {"key": "line2", "label": "Line 2 — Funkfrequenz / Rufzeichen", "type": "text", "default": ""},
                    {"key": "line3", "label": "Line 3 — Patienten nach Dringlichkeit", "type": "text", "default": ""},
                    {"key": "line4", "label": "Line 4 — Sonderausstattung", "type": "select",
                     "options": ["A — Keine", "B — Winde (Hoist)", "C — Bergungsgerät", "D — Beatmungsgerät"]},
                    {"key": "line5", "label": "Line 5 — Patienten (Liegend/Gehfähig)", "type": "text", "default": ""},
                    {"key": "line6", "label": "Line 6 — Sicherheitslage", "type": "select",
                     "options": ["N — Kein Feind", "P — Mögl. Feind", "E — Feind im Gebiet", "X — Bewaffnete Eskorte"]},
                    {"key": "line7", "label": "Line 7 — Markierung Landeplatz", "type": "select",
                     "options": ["A — Panels", "B — Pyrotechnik", "C — Rauch", "D — Keine", "E — Sonstige"]},
                    {"key": "line8", "label": "Line 8 — Nationalität / Status", "type": "text", "default": ""},
                    {"key": "line9", "label": "Line 9 — ABC / Gelände", "type": "text", "default": ""},
                ],
            },
        ],
    },
    "erstbefund": {
        "id": "erstbefund",
        "name": "Erstbefund",
        "description": "Erste Untersuchung — Anamnese & Befund",
        "icon": "&#9879;",
        "sections": [
            {
                "title": "Stammdaten",
                "fields": [
                    {"key": "rank", "label": "Dienstgrad", "type": "text", "default": ""},
                    {"key": "unit", "label": "Einheit", "type": "text", "default": ""},
                    {"key": "dob", "label": "Geburtsdatum", "type": "text", "default": ""},
                    {"key": "blood_type", "label": "Blutgruppe", "type": "select",
                     "options": ["A+", "A-", "B+", "B-", "AB+", "AB-", "0+", "0-", "Unbekannt"]},
                    {"key": "allergies", "label": "Allergien / Unverträglichkeiten", "type": "text", "default": ""},
                ],
            },
            {
                "title": "Anamnese",
                "fields": [
                    {"key": "complaint", "label": "Hauptbeschwerde", "type": "textarea", "default": ""},
                    {"key": "history", "label": "Vorgeschichte / Vorerkrankungen", "type": "textarea", "default": ""},
                    {"key": "current_meds", "label": "Aktuelle Medikation", "type": "text", "default": ""},
                ],
            },
            {
                "title": "Befund",
                "fields": [
                    {"key": "general", "label": "Allgemeinzustand", "type": "textarea", "default": ""},
                    {"key": "pulse", "label": "Puls (bpm)", "type": "text", "default": ""},
                    {"key": "bp", "label": "Blutdruck", "type": "text", "default": ""},
                    {"key": "resp_rate", "label": "Atemfrequenz", "type": "text", "default": ""},
                    {"key": "spo2", "label": "SpO2 (%)", "type": "text", "default": ""},
                    {"key": "temp", "label": "Temperatur", "type": "text", "default": ""},
                ],
            },
            {
                "title": "Diagnose & Therapie",
                "fields": [
                    {"key": "diagnosis", "label": "Diagnose", "type": "textarea", "default": ""},
                    {"key": "therapy", "label": "Therapie / Maßnahmen", "type": "textarea", "default": ""},
                    {"key": "disposition", "label": "Weiteres Vorgehen", "type": "textarea", "default": ""},
                ],
            },
        ],
    },
    "mist": {
        "id": "mist",
        "name": "MIST Übergabe",
        "description": "Standardisierte Patientenübergabe",
        "icon": "&#8644;",
        "sections": [
            {
                "title": "MIST Schema",
                "fields": [
                    {"key": "m_mechanism", "label": "M — Mechanismus (Wie ist es passiert?)", "type": "textarea", "default": ""},
                    {"key": "i_injuries", "label": "I — Injuries (Welche Verletzungen?)", "type": "textarea", "default": ""},
                    {"key": "s_signs", "label": "S — Signs/Symptoms (Vitalzeichen, Bewusstsein)", "type": "textarea", "default": ""},
                    {"key": "t_treatment", "label": "T — Treatment (Was wurde gemacht?)", "type": "textarea", "default": ""},
                ],
            },
            {
                "title": "Übergabe-Details",
                "fields": [
                    {"key": "from_unit", "label": "Übergebende Einheit", "type": "text", "default": ""},
                    {"key": "to_unit", "label": "Aufnehmende Einrichtung", "type": "text", "default": ""},
                    {"key": "transport", "label": "Transportmittel", "type": "text", "default": ""},
                    {"key": "handover_time", "label": "Zeitpunkt Übergabe", "type": "text", "default": ""},
                ],
            },
        ],
    },
    "freitext": {
        "id": "freitext",
        "name": "Freitext",
        "description": "Freie Spracheingabe ohne Struktur",
        "icon": "&#9998;",
        "sections": [],
    },
}


# VOICE_COMMANDS wird aus config.json geladen (siehe build_voice_commands)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
class AppState:
    def __init__(self):
        self.current_model = None
        self.model_path = None
        self.model_loaded = False
        self.model_loading = False
        self.whisper_process = None
        self.recording = False
        self.transcribing = False
        self.audio_device = None
        self.audio_chunks = []
        self.stream = None
        self.sessions = {}
        self.active_session = None
        self.ws_clients: list[WebSocket] = []
        # Patienten-Registry
        self.patients: dict = {}       # patient_id -> patient data
        self.rfid_map: dict = {}       # rfid_tag_id -> patient_id
        self.active_patient: str = ""  # Aktuell ausgewählter Patient
        self.backend_reachable: bool = False
        self.sync_queue_depth: int = 0
        # Netzwerk-Teilnehmer (Peer Discovery)
        self.peers: dict = {}  # device_id -> {unit_name, ip, port, last_seen, role}
        self._stream_samplerate: int = SAMPLE_RATE
        # Mikrofon-Test
        self._mic_test: bool = False
        self._mic_test_chunks: list = []
        self._mic_test_stream = None
        self.language = "de"
        self.model_ram_mb = 0
        # Vosk
        self.vosk_enabled = False
        self.vosk_model = None
        self.vosk_recognizer = None
        self.vosk_listening = False
        self.persistent_stream = None
        self.event_loop = None
        self.vosk_command_queue = []  # thread-safe command queue
        # Hardware-Integration (Phase 6+)
        self.current_operator: dict | None = None  # None oder {uid, label, name, role, since}
        self.last_rfid_uid: str = "---"
        # Multi-Patient-Flow: Aufnahmen sammeln sich als Liste, jede wartet
        # unabhängig auf manuelle Analyse. Nie überschreiben, immer anhängen.
        # Struktur pro Eintrag:
        #   {id, full_text, time, datetime, date, duration, analyzed,
        #    analyzing, created_patient_ids}
        self.pending_transcripts: list[dict] = []

    def available_models(self):
        models = []
        for f in sorted(MODELS_DIR.glob("ggml-*.bin")):
            size_mb = f.stat().st_size / (1024 * 1024)
            name = f.stem.replace("ggml-", "")
            models.append({"name": name, "file": f.name, "size_mb": round(size_mb)})
        return models

    def audio_devices(self):
        devices = []
        # Nur echte USB/Hardware-Geräte + pulse/default anzeigen
        skip_keywords = ["NVIDIA Jetson", "sysdefault", "samplerate", "speexrate", "upmix", "vdownmix", "spdif"]
        for i, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] > 0:
                name = dev["name"]
                if any(kw in name for kw in skip_keywords):
                    continue
                devices.append({
                    "id": i,
                    "name": name,
                    "channels": dev["max_input_channels"],
                    "samplerate": int(dev["default_samplerate"]),
                    "default": i == sd.default.device[0],
                })
        return devices


state = AppState()

# Hardware-Service (Buttons + LEDs + Shutdown-Geste). Wird im Startup gestartet.
# RFID-Scan-Callback wird unten definiert und nach Instanzierung zugewiesen.
hardware_service = HardwareService(_config, oled_menu, on_rfid_scan=None)


# ---------------------------------------------------------------------------
# RFID-Scan-Routing (Phase 6) — Login vs Patient-Karte
# ---------------------------------------------------------------------------
def _find_operator(uid: str) -> dict | None:
    """Sucht eine UID in der config.rfid.operators Whitelist."""
    rfid_cfg = _config.get("rfid", {})
    for op in rfid_cfg.get("operators", []):
        if op.get("uid", "").upper() == uid.upper():
            return op
    return None


def _role_has_permission(role: str, permission: str) -> bool:
    """Prüft ob eine Rolle eine Permission hat (unterstützt Wildcard '*')."""
    roles = _config.get("rfid", {}).get("roles", {})
    perms = roles.get(role, [])
    return "*" in perms or permission in perms


def check_permission(permission: str):
    """Hilfsfunktion für Endpoints — wirft HTTPException(403) wenn fehlend.

    Verwendung in einem Endpoint:
        from fastapi import HTTPException
        check_permission("patient_delete")
    """
    from fastapi import HTTPException
    op = state.current_operator
    if op is None:
        raise HTTPException(status_code=401, detail="Kein Bediener eingeloggt")
    role = op.get("role", "")
    if not _role_has_permission(role, permission):
        raise HTTPException(
            status_code=403,
            detail=f"Rolle '{role}' hat keine Berechtigung für '{permission}'",
        )


def _handle_rfid_scan(uid: str):
    """Callback aus dem RfidService — läuft im asyncio-Task-Kontext.

    Entscheidet ob die UID ein Bediener-Login (blaue Karte) oder eine
    Patientenkarte (weiße Karte) ist und handled beide Fälle async.
    """
    state.last_rfid_uid = uid
    op = _find_operator(uid)
    if op is not None:
        asyncio.create_task(_handle_operator_scan(uid, op))
    else:
        asyncio.create_task(_handle_patient_scan(uid))


def _handle_oled_action(action: dict):
    """Callback vom Hardware-Service: Taster B lang im OLED-Untermenü.

    Empfängt ein dict mit {"page": <screen>, "action": <action_id>, "label": <text>}
    aus PAGE_SUBMENUS. Der Hardware-Service scheduled die zurückgegebene
    Coroutine automatisch.
    """
    page = action.get("page", "")
    action_id = action.get("action", "")
    print(f"[OLED-ACTION] page={page} action={action_id}", flush=True)

    if page == "operator" and action_id == "logout":
        return _manual_logout()

    if page == "patient":
        if action_id == "record_toggle":
            return _oled_record_toggle()
        if action_id == "analyze_pending":
            return _oled_analyze_pending()
        if action_id == "send_backend":
            return voice_send_backend()
        if action_id == "card_write":
            return voice_write_card()
        if action_id == "patient_delete":
            return _oled_patient_delete()

    print(f"[OLED-ACTION] unbekannt: page={page} action={action_id}", flush=True)
    return None


async def _oled_analyze_pending():
    """OLED-Untermenü 'Analysieren': Analysiert ALLE noch unanalysierten
    Transkripte in der pending-Liste sequentiell. Jede Aufnahme bleibt
    dabei einzeln erhalten und bekommt ihre eigenen Patienten."""
    todo = [p for p in state.pending_transcripts if not p.get("analyzed") and not p.get("analyzing")]
    if not todo:
        tts.speak("Kein Transkript vorhanden")
        oled_menu.show_status("KEIN TRANSKRIPT", "Erst aufnehmen")
        await asyncio.sleep(2)
        oled_menu.clear_status()
        return
    tts.speak("Analyse gestartet")
    total_created = 0
    for idx, pt in enumerate(todo):
        pt["analyzing"] = True
        full_text = pt["full_text"]
        record_time = pt.get("time") or datetime.now().strftime("%H:%M:%S")
        oled_menu.show_status("ANALYSE", f"Aufnahme {idx + 1}/{len(todo)}", int((idx + 1) / len(todo) * 100))
        await broadcast({"type": "analysis_started", "chars": len(full_text), "pending_id": pt["id"]})
        try:
            created = await _segment_and_create_patients(full_text, record_time)
        finally:
            pt["analyzing"] = False
        pt["analyzed"] = True
        pt["created_patient_ids"] = created
        total_created += len(created)
        await broadcast({
            "type": "analysis_complete",
            "pending_id": pt["id"],
            "count": len(created),
            "created_patient_ids": created,
        })
    oled_menu.show_status("FERTIG", f"{total_created} Patient(en)")
    tts.speak(f"{total_created} Patient angelegt" if total_created == 1 else f"{total_created} Patienten angelegt")
    await asyncio.sleep(2)
    oled_menu.clear_status()


async def _start_record_flow():
    """EINE gemeinsame Implementierung für Aufnahme-Start — wird von
    Taster, Sprachbefehl und jedem anderen Einstiegspunkt aufgerufen.
    Stellt sicher dass es KEINEN Unterschied zwischen Taster und Sprache gibt."""
    if state.recording:
        return  # läuft schon
    if state.transcribing:
        tts.speak("Transkription läuft, bitte warten")
        return
    if not state.model_loaded:
        tts.speak("Sprachmodell nicht geladen")
        return
    print("[FLOW] Aufnahme starten (Multi-Patient-Modus)", flush=True)
    tts.announce_recording_start()
    await asyncio.sleep(1.5)
    state.audio_chunks = []
    await start_recording_internal()


async def _stop_record_flow():
    """EINE gemeinsame Implementierung für Aufnahme-Stopp — von Taster,
    Sprachbefehl und jedem anderen Einstiegspunkt identisch.
    TTS-Meldung kommt SOFORT, damit die akustische Rückmeldung nicht
    auf die Transkription warten muss."""
    if not state.recording:
        return
    trim_chunks = int(1.5 / 0.1)
    if len(state.audio_chunks) > trim_chunks:
        state.audio_chunks = state.audio_chunks[:-trim_chunks]
    tts.announce_recording_stop()
    print("[FLOW] Aufnahme stoppen (Multi-Patient-Modus)", flush=True)
    await stop_recording()


async def _oled_record_toggle():
    """OLED-Untermenü: Aufnahme starten oder stoppen (Toggle).
    Delegiert an die shared Flow-Funktionen damit Taster und Sprachbefehl
    exakt denselben Code-Pfad durchlaufen."""
    print(f"[OLED-ACTION] record_toggle entry: recording={state.recording} transcribing={state.transcribing}", flush=True)
    if state.recording:
        await _stop_record_flow()
    else:
        await _start_record_flow()


async def _oled_patient_delete():
    """OLED-Untermenü: Aktuellen Patient löschen. Spiegelt die Logik des
    HTTP-Endpoints /api/patient/{id} (DELETE) für konsistentes Verhalten."""
    if not state.active_patient or state.active_patient not in state.patients:
        tts.speak("Kein aktiver Patient")
        return
    pid = state.active_patient
    patient = state.patients.pop(pid)
    rfid = patient.get("rfid_tag_id", "")
    if rfid and rfid in state.rfid_map:
        del state.rfid_map[rfid]
    state.active_patient = ""
    oled_menu.show_status("GELOESCHT", pid[:8])
    await broadcast({"type": "patient_deleted", "patient_id": pid})
    tts.announce_entry_deleted()
    await asyncio.sleep(1.0)
    oled_menu.clear_status()


async def _manual_logout():
    """OK-Druck auf OPERATOR-Seite = manueller Logout des aktuellen Bedieners."""
    op = state.current_operator
    if op is None:
        return
    state.current_operator = None
    oled_menu.show_status("LOGOUT", f"{op.get('name', '')}")
    try:
        tts.speak(f"Abmeldung {op.get('name', '')}")
    except Exception:
        pass
    await asyncio.sleep(1.5)
    oled_menu.clear_status()
    await broadcast({"type": "operator_logout", "uid": op.get("uid"), "name": op.get("name")})


async def _handle_operator_scan(uid: str, op: dict):
    """Login / Logout Toggle für blaue Operator-Transponder."""
    now_iso = datetime.now().strftime("%H:%M")
    current = state.current_operator
    if current and current.get("uid", "").upper() == uid.upper():
        # Gleicher Bediener scannt erneut → Logout
        state.current_operator = None
        oled_menu.show_status("LOGOUT", f"{op.get('name', '')}")
        await asyncio.sleep(1.5)
        oled_menu.clear_status()
        await broadcast({"type": "operator_logout", "uid": uid, "name": op.get("name")})
        try:
            from shared import tts
            tts.speak(f"Abmeldung {op.get('name', '')}")
        except Exception:
            pass
        print(f"Operator-Logout: {op.get('label')} {op.get('name')}")
        return

    # Anderer Login → direkt ersetzen (kein zweistufiger Handover nötig)
    state.current_operator = {
        "uid": uid,
        "label": op.get("label", "?"),
        "name": op.get("name", ""),
        "role": op.get("role", ""),
        "since": now_iso,
    }
    oled_menu.show_status(
        f"LOGIN [{op.get('label', '?')}]",
        f"{op.get('name', '')} / {op.get('role', '')}",
    )
    await hardware_service.flash_success(1.2)
    await asyncio.sleep(0.3)
    oled_menu.clear_status()
    # Auf OPERATOR-Seite springen (Index in PAGES)
    try:
        from jetson.oled import PAGES
        if "operator" in PAGES:
            oled_menu.current_page = PAGES.index("operator")
    except Exception:
        pass
    await broadcast({
        "type": "operator_login",
        "uid": uid,
        "label": op.get("label"),
        "name": op.get("name"),
        "role": op.get("role"),
    })
    try:
        from shared import tts
        tts.speak(f"Willkommen {op.get('name', '')}")
    except Exception:
        pass
    print(f"Operator-Login: {op.get('label')} {op.get('name')} (Rolle {op.get('role')})")


async def _handle_patient_scan(uid: str):
    """Weiße Karte → Patient-Lookup oder Platzhalter-Event.

    Die bisherige HTTP-API /api/rfid/scan bleibt als manueller Fallback
    erhalten. Dieser Pfad hier ist der automatische Weg via Hardware-Reader.
    """
    existing_pid = lookup_by_rfid(state.rfid_map, uid)
    if existing_pid and existing_pid in state.patients:
        state.active_patient = existing_pid
        patient = state.patients[existing_pid]
        await broadcast({"type": "rfid_scan", "action": "found", "patient": patient})
        oled_menu.show_status("PATIENT", patient.get("name", existing_pid)[:18])
        await asyncio.sleep(1.5)
        oled_menu.clear_status()
        try:
            from shared import tts
            tts.announce_rfid_linked()
        except Exception:
            pass
        return

    # Unbekannte Karte → WebSocket-Event, User kann im UI neuen Patient anlegen
    await broadcast({"type": "rfid_scan", "action": "unknown", "uid": uid})
    oled_menu.show_status("NEUE KARTE", f"UID {uid[:12]}")
    await asyncio.sleep(1.5)
    oled_menu.clear_status()


async def broadcast(msg: dict):
    """Sendet JSON an alle verbundenen WebSocket-Clients."""
    dead = []
    for ws in state.ws_clients:
        try:
            await ws.send_json(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        state.ws_clients.remove(ws)


# ---------------------------------------------------------------------------
# System Monitoring
# ---------------------------------------------------------------------------
def get_system_stats():
    cpu_percent = psutil.cpu_percent(interval=0)
    cpu_freq = psutil.cpu_freq()
    mem = psutil.virtual_memory()

    gpu_usage = "N/A"
    gpu_mem_used = 0
    gpu_mem_total = 0

    try:
        gpu_load_path = Path("/sys/devices/platform/bus@0/17000000.gpu/load")
        if gpu_load_path.exists():
            raw = int(gpu_load_path.read_text().strip())
            gpu_usage = str(round(raw / 10, 1))
            gpu_mem_used = round(mem.used / 1024 / 1024)
            gpu_mem_total = round(mem.total / 1024 / 1024)
    except Exception:
        pass

    temps = {}
    try:
        for tz in Path("/sys/class/thermal/").glob("thermal_zone*"):
            try:
                name = (tz / "type").read_text().strip()
                temp = int((tz / "temp").read_text().strip()) / 1000
                temps[name] = round(temp, 1)
            except Exception:
                pass
    except Exception:
        pass

    disk = psutil.disk_usage("/")

    # Prozesse mit höchstem RAM-Verbrauch
    ram_processes = []
    try:
        for proc in psutil.process_iter(['pid', 'name', 'memory_info']):
            info = proc.info
            rss = info.get('memory_info')
            if rss and rss.rss > 50 * 1024 * 1024:  # > 50MB
                ram_processes.append({
                    "name": info['name'],
                    "pid": info['pid'],
                    "rss_mb": round(rss.rss / 1024 / 1024),
                })
        ram_processes.sort(key=lambda x: x['rss_mb'], reverse=True)
        ram_processes = ram_processes[:8]
    except Exception:
        pass

    # Ollama Modell-Status
    ollama_models = []
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/ps", timeout=3)
        if r.status_code == 200:
            for m in r.json().get("models", []):
                ollama_models.append({
                    "name": m["name"],
                    "size_mb": round(m.get("size", 0) / 1024 / 1024),
                    "vram_mb": round(m.get("size_vram", 0) / 1024 / 1024),
                })
    except Exception:
        pass

    return {
        "cpu_percent": cpu_percent,
        "cpu_freq_mhz": round(cpu_freq.current) if cpu_freq else 0,
        "cpu_cores": psutil.cpu_count(),
        "ram_used_mb": round(mem.used / 1024 / 1024),
        "ram_total_mb": round(mem.total / 1024 / 1024),
        "ram_percent": mem.percent,
        "gpu_usage": gpu_usage,
        "gpu_mem_used_mb": gpu_mem_used,
        "gpu_mem_total_mb": gpu_mem_total,
        "temperatures": temps,
        "disk_used_gb": round(disk.used / 1024**3, 1),
        "disk_total_gb": round(disk.total / 1024**3, 1),
        "disk_percent": round(disk.percent, 1),
        "ram_processes": ram_processes,
        "ollama_models": ollama_models,
        "whisper_loaded": state.model_loaded,
        "whisper_model": state.current_model or "",
        "whisper_ram_mb": state.model_ram_mb,
    }


# ---------------------------------------------------------------------------
# Vosk Keyword Detection
# ---------------------------------------------------------------------------
def init_vosk():
    """Initialisiert Vosk für Sprachbefehle."""
    if not VOSK_MODEL_PATH.exists():
        print("Vosk-Modell nicht gefunden, Sprachbefehle deaktiviert")
        return False
    try:
        from vosk import Model, KaldiRecognizer, SetLogLevel
        SetLogLevel(-1)
        state.vosk_model = Model(str(VOSK_MODEL_PATH))
        state.vosk_recognizer = KaldiRecognizer(state.vosk_model, SAMPLE_RATE)
        state.vosk_enabled = True
        print(f"Vosk Sprachsteuerung aktiviert (Modell: {VOSK_MODEL_PATH.name})")
        return True
    except Exception as e:
        print(f"Vosk Init fehlgeschlagen: {e}")
        return False


def match_voice_command(text: str) -> str | None:
    """Matched erkannten Text gegen Sprachbefehle. Gibt Aktions-ID zurück."""
    text = text.lower().strip()
    if len(text) < 3:
        return None
    # Exakter Match
    if text in VOICE_COMMANDS:
        return VOICE_COMMANDS[text]
    # Phrase-in-Text Match (Befehl muss vollständig im Text vorkommen)
    for phrase, action in VOICE_COMMANDS.items():
        if phrase in text:
            return action
    # KEIN text-in-phrase Match mehr — zu viele Fehlauslösungen
    return None


def resample_to_16k(audio: np.ndarray, orig_rate: int) -> np.ndarray:
    """Einfaches Resampling auf 16000Hz via linearer Interpolation."""
    if orig_rate == SAMPLE_RATE:
        return audio
    ratio = SAMPLE_RATE / orig_rate
    n_out = int(len(audio) * ratio)
    indices = np.linspace(0, len(audio) - 1, n_out)
    return np.interp(indices, np.arange(len(audio)), audio.flatten()).astype(np.float32)


def persistent_audio_callback(indata, frames, time_info, status):
    """Audio-Callback für persistenten Stream — füttert Vosk und Recording."""
    # Recording-Buffer füllen (native Rate)
    if state.recording:
        state.audio_chunks.append(indata.copy())

    # Immer letzten Chunk für Level-Messung speichern
    state._mic_test_chunks.append(indata.copy())
    if len(state._mic_test_chunks) > 10:
        state._mic_test_chunks.pop(0)

    # Vosk fuettern — auf 16kHz resampled
    if state.vosk_enabled and state.vosk_recognizer and not state.transcribing:
        try:
            stream_rate = getattr(state, '_stream_samplerate', SAMPLE_RATE)
            mono = indata[:, 0]
            if stream_rate != SAMPLE_RATE:
                mono = resample_to_16k(mono, stream_rate)
            data = (mono * 32767).astype(np.int16).tobytes()
            if state.vosk_recognizer.AcceptWaveform(data):
                result = json.loads(state.vosk_recognizer.Result())
                text = result.get("text", "").strip()
                if text:
                    action = match_voice_command(text)
                    if action:
                        # Während Aufnahme: Stop, Patient fertig, Neuer Patient, Triage erlauben
                        allowed_during_recording = {"record_stop", "patient_ready", "new_patient",
                            "triage_red", "triage_yellow", "triage_green", "triage_blue"}
                        if state.recording and action not in allowed_during_recording:
                            return
                        # Wenn nicht aufnimmt, kein Stop-Befehl
                        if not state.recording and action == "record_stop":
                            return
                        state.vosk_command_queue.append({
                            "action": action,
                            "text": text,
                            "time": datetime.now().isoformat(),
                        })
        except Exception:
            pass


def get_device_samplerate(device=None) -> int:
    """Ermittelt die native Samplerate eines Audio-Geräts."""
    try:
        dev_id = device if device is not None else sd.default.device[0]
        info = sd.query_devices(dev_id, 'input')
        return int(info['default_samplerate'])
    except Exception:
        return SAMPLE_RATE


def start_persistent_stream():
    """Startet den persistenten Audio-Stream."""
    stop_persistent_stream()
    time.sleep(1.5)  # PortAudio/ALSA braucht Zeit zum Freigeben des Handles
    device = state.audio_device
    # Raten die wir probieren: nativ, 16000, 48000
    native_rate = get_device_samplerate(device)
    rates_to_try = [native_rate]
    if SAMPLE_RATE not in rates_to_try:
        rates_to_try.append(SAMPLE_RATE)
    if 48000 not in rates_to_try:
        rates_to_try.append(48000)

    for rate in rates_to_try:
        try:
            state.persistent_stream = sd.InputStream(
                samplerate=rate, channels=1, dtype="float32",
                blocksize=int(rate * 0.1),
                device=device, callback=persistent_audio_callback,
            )
            state.persistent_stream.start()
            state._stream_samplerate = rate
            state.vosk_listening = state.vosk_enabled
            print(f"Persistenter Audio-Stream gestartet (Device: {device or 'default'}, {rate}Hz)")
            return True
        except Exception as e:
            print(f"Audio-Stream bei {rate}Hz fehlgeschlagen: {e}")
            continue

    print("WARNUNG: Kein Audio-Stream konnte geöffnet werden!")
    return False


def stop_persistent_stream():
    """Stoppt den persistenten Audio-Stream."""
    if state.persistent_stream:
        try:
            state.persistent_stream.stop()
            state.persistent_stream.close()
        except Exception:
            pass
        state.persistent_stream = None
    state.vosk_listening = False


async def process_vosk_commands():
    """Verarbeitet Vosk-Sprachbefehle aus der Queue (läuft als asyncio task)."""
    while True:
        if state.vosk_command_queue:
            cmd = state.vosk_command_queue.pop(0)
            action = cmd["action"]
            text = cmd["text"]
            print(f"Sprachbefehl: '{text}' -> {action}")

            await broadcast({
                "type": "voice_command",
                "action": action,
                "text": text,
            })

            try:
                # Alle Record-Start-Aliase gehen durch denselben Flow wie der
                # Hardware-Taster. Keine Unterscheidung mehr zwischen
                # "Sprachbefehl" und "Taster" — nur ein einziger Code-Pfad.
                if action in ("record_start", "new_patient"):
                    await _start_record_flow()
                elif action in ("record_stop", "patient_ready"):
                    await _stop_record_flow()
                elif action == "triage_red":
                    await voice_set_triage("T1")
                elif action == "triage_yellow":
                    await voice_set_triage("T2")
                elif action == "triage_green":
                    await voice_set_triage("T3")
                elif action == "triage_blue":
                    await voice_set_triage("T4")
                elif action == "delete_last":
                    await voice_delete_last()
                elif action == "patient_count":
                    await voice_patient_count()
                elif action == "analyze_all":
                    # Sprachbefehl "Analysieren" → gleicher Pfad wie OLED-Menü
                    await _oled_analyze_pending()
                elif action == "send_backend":
                    await voice_send_backend()
                elif action == "export_docx":
                    tts.announce_confirmed()
                    await broadcast({"type": "voice_command", "action": "export_docx"})
                elif action == "rfid_write_patient":
                    await voice_write_card()
                elif action == "mic_test":
                    await voice_mic_test()
            except Exception as e:
                print(f"Vosk Befehl Fehler: {e}")
                tts.announce_error()

        await asyncio.sleep(0.1)


# ---------------------------------------------------------------------------
# Voice Command Handlers (Feld-Modus)
# ---------------------------------------------------------------------------
# Hinweis: voice_new_patient und voice_patient_ready wurden entfernt. Der
# Multi-Patient-Flow legt keinen Patient mehr vorab an — Aufnahmen werden
# gesammelt und erst bei der Analyse über Qwen segmentiert. Die beiden
# Sprachbefehle "neuer patient" und "patient fertig" werden jetzt in
# process_vosk_commands auf _start_record_flow() bzw. _stop_record_flow()
# umgeleitet, damit Taster und Sprache denselben Code-Pfad durchlaufen.


async def voice_set_triage(level: str):
    """Sprachbefehl: Triage setzen für aktiven Patient."""
    if not state.active_patient or state.active_patient not in state.patients:
        tts.announce_error()
        return
    patient = state.patients[state.active_patient]
    patient["triage"] = level
    patient["timeline"].append({
        "time": datetime.now().isoformat(),
        "role": patient["current_role"],
        "event": "triage_set",
        "details": f"Triage {level} gesetzt (Sprachbefehl)",
    })
    await broadcast({"type": "patient_update", "patient": patient})
    tts.announce_triage(level)


async def voice_delete_last():
    """Sprachbefehl: Letzten Transkriptions-Eintrag löschen."""
    sid = state.active_session
    if sid and sid in state.sessions:
        records = state.sessions[sid]["records"]
        if records:
            records.pop()
            # Auch aus Patient-Transkripten löschen
            if state.active_patient and state.active_patient in state.patients:
                transcripts = state.patients[state.active_patient]["transcripts"]
                if transcripts:
                    transcripts.pop()
            await broadcast({
                "type": "entry_deleted",
                "session_id": sid,
                "remaining": len(records),
            })
            tts.announce_entry_deleted()
            return
    tts.announce_error()


async def voice_patient_count():
    """Sprachbefehl: Anzahl der Patienten ansagen."""
    count = len(state.patients)
    tts.announce_patient_count(count)
    await broadcast({"type": "voice_command", "action": "patient_count", "count": count})


async def voice_analyze_all():
    """Sprachbefehl: Alle nicht-analysierten Patienten per KI analysieren."""
    if not state.patients:
        tts.speak("Keine Patienten vorhanden")
        return
    if getattr(state, '_analyzing', False):
        tts.speak("Analyse läuft bereits")
        return

    # Patienten ohne 'analyzed'-Badge sammeln
    pending = [(pid, p) for pid, p in state.patients.items() if not p.get("analyzed")]
    if not pending:
        tts.speak("Alle Patienten bereits analysiert")
        return

    tts.speak(f"{len(pending)} Patienten werden analysiert")
    state._analyzing = True
    oled_menu.show_status("ANALYSE", f"{len(pending)} Patient(en)...", 0)
    await broadcast({"type": "analyzing_batch", "count": len(pending)})
    asyncio.create_task(_run_batch_analysis(pending))


async def _run_batch_analysis(pending: list):
    """Analysiert Patienten sequentiell.

    Parallel-Betrieb: Whisper und Qwen laufen beide permanent im Speicher.
    Kein GPU-Swap mehr nötig — im Headless-Mode haben wir genug RAM.
    TTS (Piper, CPU) läuft durchgehend.
    """
    try:
        print(f"Analyse: Ollama {OLLAMA_MODEL}...")
        for pid, patient in pending:
            sid = _find_session_for_patient(pid)
            if not sid:
                print(f"Analyse übersprungen: Keine Session für {pid}")
                continue

            idx = [i for i, (p, _) in enumerate(pending) if p == pid][0]
            oled_menu.show_status("ANALYSE", f"Patient {idx + 1}/{len(pending)}", int((idx + 1) / len(pending) * 100))
            print(f"Analysiere Patient {pid}...")
            await broadcast({"type": "analyzing_patient", "patient_id": pid})
            try:
                prev_active = state.active_patient
                state.active_patient = pid
                result = await _run_analysis_for_session(sid)
                patient["analyzed"] = True
                await broadcast({"type": "patient_update", "patient": patient})
                state.active_patient = prev_active
            except Exception as e:
                print(f"Analyse Fehler für {pid}: {e}")
                await broadcast({"type": "analyzing_patient_done", "patient_id": pid, "error": True})

        analyzed_count = sum(1 for _, p in pending if p.get("analyzed"))
        oled_menu.show_status("ANALYSE FERTIG", f"{analyzed_count} Patient(en)")
        tts.speak(f"{analyzed_count} Patienten analysiert")
        await broadcast({"type": "batch_analysis_complete", "analyzed": analyzed_count, "total": len(pending)})

    except Exception as e:
        print(f"Batch-Analyse Fehler: {e}")
        await broadcast({"type": "analysis_error", "error": str(e)})
    finally:
        state._analyzing = False
        await asyncio.sleep(1.5)
        oled_menu.clear_status()


def _find_session_for_patient(patient_id: str) -> str | None:
    """Findet die Session-ID die zu einem Patienten gehört."""
    # Direkt per patient_id-Feld in der Session
    for sid, session in state.sessions.items():
        if session.get("patient_id") == patient_id:
            return sid
    # Fallback: letzte Session mit Transkripten (Altdaten)
    return None


async def voice_send_backend():
    """Sprachbefehl: Alle analysierten, nicht-übermittelten Patienten an Leitstelle senden."""
    if not state.patients:
        tts.speak("Keine Patienten vorhanden")
        return

    # Nur analysierte, nicht-gesyncte Patienten senden
    sendable = [p for p in state.patients.values() if p.get("analyzed") and not p.get("synced")]
    if not sendable:
        not_analyzed = [p for p in state.patients.values() if not p.get("analyzed")]
        if not_analyzed:
            tts.speak(f"{len(not_analyzed)} Patienten noch nicht analysiert")
        else:
            tts.speak("Alle Patienten bereits übermittelt")
        return

    oled_menu.show_status("SENDEN", "An Leitstelle...", 50)
    result = await sync_all_patients()
    if result["sent"] > 0:
        oled_menu.show_status("GESENDET", f"{result['sent']} Patient(en)")
        tts.speak(f"{result['sent']} Patienten übermittelt")
    elif result.get("error"):
        oled_menu.show_status("FEHLER", "Keine Verbindung")
        tts.speak("Leitstelle nicht erreichbar")
    elif result["failed"] > 0:
        oled_menu.show_status("FEHLER", f"{result['failed']} fehlgeschlagen")
        tts.speak(f"{result['failed']} Patienten nicht übermittelt. Leitstelle nicht erreichbar.")


async def voice_mic_test():
    """Sprachbefehl 'mikrofontest' / 'audiotest'.

    Wenn dieser Handler läuft, haben Audio-Capture (Dongle-Mikro), Vosk
    (Spracherkennung) UND Piper (TTS-Ausgabe) alle funktioniert — der Befehl
    wäre sonst gar nicht angekommen. Die Bestätigung bestätigt zusätzlich den
    Output-Pfad.
    """
    tts.speak("Mikrofon funktioniert, ich verstehe dich")
    await broadcast({"type": "voice_command", "action": "mic_test", "status": "ok"})


def _patient_has_written_rfid(patient: dict) -> bool:
    """Prüft ob der Patient schon mindestens einmal auf eine Karte
    geschrieben wurde (Timeline-Event 'rfid_written' vorhanden)."""
    for ev in patient.get("timeline", []) or []:
        if ev.get("event") == "rfid_written":
            return True
    return False


async def voice_write_card():
    """Batch-RFID: Schreibt alle Patienten in Anlegungsreihenfolge auf
    leere MIFARE-Karten. Iteriert durch state.patients.values() (stabile
    Reihenfolge in Python 3.7+) und überspringt solche die bereits eine
    RFID-Karte haben. Shared Handler für OLED-Menü, Sprachbefehl und GUI.

    Ablauf pro Patient:
      1. OLED "KARTE N/M <Name>" + TTS-Ansage
      2. Rot-LED BLINK_SLOW
      3. Warten auf RFID-Scan (15 s Timeout pro Karte)
      4. Operator-Karte → abweisen und warten
      5. Sonst: schreiben + Timeline-Event + TTS-Bestätigung
    """
    from shared.rfid import rc522_write_patient_to_card
    from jetson.hardware import LedPattern

    # Alle Patienten die noch keine Karte haben, in Anlegungsreihenfolge
    todo = [
        p for p in state.patients.values()
        if not _patient_has_written_rfid(p)
    ]
    if not todo:
        tts.speak("Alle Patienten schon auf Karten")
        oled_menu.show_status("KEINE TODO", "Alle RFID belegt")
        await asyncio.sleep(2.0)
        oled_menu.clear_status()
        return

    total = len(todo)
    tts.speak(f"{total} Karten schreiben" if total > 1 else "Eine Karte schreiben")
    written = 0
    skipped: list[str] = []
    op = state.current_operator or {}
    op_label = op.get("name", "") if op else "Taster"

    loop = asyncio.get_event_loop()

    for idx, patient in enumerate(todo):
        name = (patient.get("name") or "Unbekannt").strip()
        pid = patient["patient_id"]
        label_idx = f"{idx + 1}/{total}"
        short_name = name[:14]
        oled_menu.show_status(f"KARTE {label_idx}", f"{short_name} auflegen")
        if hardware_service._leds:
            hardware_service._leds.set(red=LedPattern.BLINK_SLOW)
        tts.speak(f"Karte {idx + 1}. {name}")

        uid = await hardware_service.await_rfid_scan(timeout=15.0)
        if uid is None:
            oled_menu.show_status("TIMEOUT", f"{label_idx} uebersprungen")
            tts.speak("Zeit abgelaufen, weiter")
            skipped.append(pid)
            await asyncio.sleep(1.0)
            continue

        # Operator-Karte? Nicht überschreiben
        if _find_operator(uid) is not None:
            oled_menu.show_status("OPERATOR", "Weisse Karte bitte")
            tts.speak("Keine Operator-Karte")
            await hardware_service.flash_error(1.0)
            # erneut auf dieselben Patient warten, Schleife rückwärts
            skipped.append(pid)
            await asyncio.sleep(1.5)
            continue

        # Schreiben
        oled_menu.show_status("SCHREIBE", f"{label_idx} {uid[:8]}", progress=int((idx + 1) / total * 100))
        try:
            success, result = await loop.run_in_executor(
                None, rc522_write_patient_to_card, patient, 8.0
            )
        except Exception as e:
            success, result = False, str(e)

        if success:
            patient.setdefault("timeline", []).append({
                "time": datetime.now().isoformat(),
                "role": patient.get("current_role", "phase0"),
                "event": "rfid_written",
                "details": f"Karte UID {result} von {op_label}",
            })
            state.last_rfid_uid = result
            await broadcast({
                "type": "rfid_written",
                "patient_id": pid,
                "uid": result,
            })
            await hardware_service.flash_success(0.7)
            tts.speak(f"Karte {idx + 1} fertig")
            written += 1
        else:
            oled_menu.show_status("FEHLER", str(result)[:18])
            tts.speak(f"Karte {idx + 1} Fehler")
            await hardware_service.flash_error(1.0)
            skipped.append(pid)
        await asyncio.sleep(0.8)

    if hardware_service._leds:
        hardware_service._leds.set(red=LedPattern.OFF)

    if written == total:
        oled_menu.show_status("FERTIG", f"{written}/{total} OK")
        tts.speak(f"{written} Karten geschrieben" if written != 1 else "Eine Karte geschrieben")
    elif written > 0:
        oled_menu.show_status("TEIL OK", f"{written}/{total}")
        tts.speak(f"{written} von {total} Karten geschrieben")
    else:
        oled_menu.show_status("KEINE OK", "0 Karten")
        tts.speak("Keine Karten geschrieben")
    await asyncio.sleep(2.5)
    oled_menu.clear_status()
    return


async def _legacy_single_card_write_unused():
    """Alte Single-Patient-Implementierung — wird nicht mehr aufgerufen,
    bleibt nur als Referenz für die await-Sequenz."""
    from shared.rfid import rc522_write_patient_to_card
    from jetson.hardware import LedPattern

    if not state.active_patient or state.active_patient not in state.patients:
        tts.speak("Kein aktiver Patient")
        oled_menu.show_status("FEHLER", "Kein aktiver Patient")
        await asyncio.sleep(2.0)
        oled_menu.clear_status()
        return
    patient = state.patients[state.active_patient]
    op = state.current_operator or {}

    oled_menu.show_status("RFID SCHREIBEN", "Karte anhalten...")
    if hardware_service._leds:
        hardware_service._leds.set(red=LedPattern.BLINK_SLOW)
    tts.speak("RFID Karte anhalten")

    # Exklusiv auf nächsten Scan warten (max 10 s)
    uid = await hardware_service.await_rfid_scan(timeout=10.0)
    if uid is None:
        oled_menu.show_status("TIMEOUT", "Keine Karte")
        if hardware_service._leds:
            hardware_service._leds.set(red=LedPattern.OFF)
        hardware_service.set_system_state(hardware_service.get_system_state())  # refresh
        tts.speak("Keine Karte erkannt")
        await asyncio.sleep(2.0)
        oled_menu.clear_status()
        return

    # Prüfen ob es eine Operator-Karte ist (blaue Transponder nicht beschreiben)
    if _find_operator(uid) is not None:
        oled_menu.show_status("OPERATOR", "Weiße Karte bitte")
        tts.speak("Keine Patientenkarte")
        await hardware_service.flash_error(1.5)
        await asyncio.sleep(1.0)
        oled_menu.clear_status()
        return

    # Schreiben (blocking → in Executor)
    oled_menu.show_status("SCHREIBE", f"UID {uid[:8]}", progress=50)
    loop = asyncio.get_event_loop()
    try:
        success, result = await loop.run_in_executor(
            None, rc522_write_patient_to_card, patient, 8.0
        )
    except Exception as e:
        success, result = False, str(e)

    if success:
        oled_menu.show_status("GESPEICHERT", f"UID {result[:8]}")
        await hardware_service.flash_success(1.5)
        tts.speak("Patient gespeichert")
        state.last_rfid_uid = result
        # Timeline-Event
        op_label = op.get("name", "") if op else "Taster"
        patient["timeline"].append({
            "time": datetime.now().isoformat(),
            "role": patient["current_role"],
            "event": "rfid_written",
            "details": f"Auf Karte geschrieben (UID {result}) von {op_label}",
        })
        await broadcast({
            "type": "rfid_written",
            "patient_id": patient["patient_id"],
            "uid": result,
        })
    else:
        oled_menu.show_status("SCHREIBFEHLER", str(result)[:18])
        await hardware_service.flash_error(2.0)
        tts.speak("Schreibfehler")

    await asyncio.sleep(1.5)
    oled_menu.clear_status()


# ---------------------------------------------------------------------------
# Whisper Server Lifecycle
# ---------------------------------------------------------------------------
def start_whisper_server(model_path: Path) -> bool:
    """Startet den whisper-server mit dem gegebenen Modell."""
    stop_whisper_server()

    env = os.environ.copy()
    env["PATH"] = "/usr/local/cuda/bin:" + env.get("PATH", "")

    cmd = [
        str(WHISPER_SERVER),
        "-m", str(model_path),
        "-l", state.language,
        "-t", "4",
        "-nfa",
        "-bs", "1",
        "-bo", "1",
        "--host", "127.0.0.1",
        "--port", str(WHISPER_SERVER_PORT),
        "--convert",
    ]

    try:
        state.whisper_process = subprocess.Popen(
            cmd, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        for _ in range(30):
            time.sleep(1)
            if state.whisper_process.poll() is not None:
                stderr = state.whisper_process.stderr.read().decode()
                stderr = "\n".join(l for l in stderr.splitlines() if "NvMap" not in l)
                print(f"whisper-server Fehler: {stderr[:300]}")
                return False
            try:
                r = httpx.get(f"http://127.0.0.1:{WHISPER_SERVER_PORT}/", timeout=2)
                if r.status_code == 200:
                    state.model_loaded = True
                    try:
                        proc = psutil.Process(state.whisper_process.pid)
                        state.model_ram_mb = round(proc.memory_info().rss / 1024 / 1024)
                    except Exception:
                        state.model_ram_mb = round(model_path.stat().st_size / 1024 / 1024)
                    print(f"whisper-server bereit (PID {state.whisper_process.pid}, ~{state.model_ram_mb} MB)")
                    return True
            except Exception:
                continue
        return False
    except Exception as e:
        print(f"whisper-server Start fehlgeschlagen: {e}")
        return False


def stop_whisper_server():
    """Stoppt den whisper-server und gibt GPU-Speicher frei."""
    if state.whisper_process:
        try:
            state.whisper_process.terminate()
            state.whisper_process.wait(timeout=5)
        except Exception:
            state.whisper_process.kill()
        state.whisper_process = None
    state.model_loaded = False
    state.model_ram_mb = 0


def is_whisper_server_alive() -> bool:
    """Prüft ob der whisper-server läuft."""
    if not state.whisper_process or state.whisper_process.poll() is not None:
        state.model_loaded = False
        return False
    try:
        r = httpx.get(f"http://127.0.0.1:{WHISPER_SERVER_PORT}/", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------
def _is_noise_transcript(text: str) -> bool:
    """Prüft ob ein Transkript nur Rauschen/Musik/Stille ist und verworfen werden soll."""
    t = text.strip().lower()
    # Leere oder zu kurze Texte
    if len(t) < 3:
        return True
    # Whisper Noise-Marker (verschiedene Sprachen/Formate)
    noise_markers = [
        "(stille", "(musik", "(music", "(noise", "(applaus",
        "[musik", "[music", "[noise", "[stille", "[applaus",
        "♪", "♫", "(lachen", "[lachen",
        "(hintergrundgeräusche", "[hintergrundgeräusche",
        "(stille / nicht erkannt)",
        "untertitel", "subtitle",
    ]
    for marker in noise_markers:
        if marker in t:
            return True
    # Nur Satzzeichen oder Sonderzeichen
    cleaned = t.replace(".", "").replace(",", "").replace("!", "").replace("?", "").replace("-", "").replace(" ", "")
    if len(cleaned) < 2:
        return True
    # Wiederholte einzelne Silben (z.B. "la la la", "na na na")
    words = t.split()
    if len(words) >= 3 and len(set(words)) == 1:
        return True
    return False


def run_transcribe(audio: np.ndarray, language: str = "de") -> dict:
    """Transkribiert Audio via whisper-server HTTP API."""
    if not state.model_loaded:
        return {"error": "Kein Modell geladen", "text": "", "duration": 0}

    if audio.ndim > 1:
        audio = audio[:, 0]
    peak = np.max(np.abs(audio))
    if peak > 0 and peak < 0.01:
        audio = audio * (0.5 / peak)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = f.name
        sf.write(wav_path, audio, SAMPLE_RATE, subtype='PCM_16')

    try:
        audio_duration = len(audio) / SAMPLE_RATE
        start = time.time()

        with open(wav_path, "rb") as f:
            response = httpx.post(
                f"http://127.0.0.1:{WHISPER_SERVER_PORT}/inference",
                files={"file": ("audio.wav", f, "audio/wav")},
                data={
                    "response_format": "json",
                    "language": language,
                },
                timeout=120,
            )

        elapsed = time.time() - start

        if response.status_code != 200:
            return {"error": f"Server-Fehler: {response.status_code}", "text": "", "duration": 0}

        result = response.json()
        text = result.get("text", "").strip()

        if not text:
            text = "(Stille / nicht erkannt)"

        rtf = elapsed / audio_duration if audio_duration > 0 else 0

        return {
            "text": text,
            "processing_time": round(elapsed, 2),
            "audio_duration": round(audio_duration, 2),
            "rtf": round(rtf, 3),
        }
    except httpx.TimeoutException:
        return {"error": "Transkription Timeout", "text": "", "duration": 0}
    except Exception as e:
        return {"error": str(e)[:300], "text": "", "duration": 0}
    finally:
        os.unlink(wav_path)


# ---------------------------------------------------------------------------
# LLM Field Extraction (Ollama / Qwen)
# ---------------------------------------------------------------------------
def build_extraction_prompt(template_id: str, text: str) -> str:
    """Baut den Prompt für die LLM-Feldextraktion mit Few-Shot Beispiel."""
    tpl = RECORD_TEMPLATES.get(template_id)
    if not tpl or not tpl.get("sections"):
        return ""

    # Sammle alle Felder mit Keys und Labels
    fields_desc = []
    field_keys = []
    for section in tpl["sections"]:
        for field in section["fields"]:
            key = field["key"]
            label = field["label"]
            field_keys.append(key)
            if field["type"] == "select":
                opts = ", ".join(field["options"])
                fields_desc.append(f"- {key}: {label} (Optionen: {opts})")
            else:
                fields_desc.append(f"- {key}: {label}")

    fields_list = "\n".join(fields_desc)

    # Few-Shot Beispiel für 9-Liner
    example = ""
    if template_id == "9liner":
        example = """
Beispiel:
Text: Standort Grid 12345678. Rufzeichen Alpha1 auf 45.5 MHz. Ein Verwundeter dringend. Brauche Trage. Ein liegender Patient. Kein Feind. Rauchzeichen. NATO-Soldat. Offenes Gelände, keine Kontaminierung.
JSON: {"line1": "Grid 12345678", "line2": "Alpha1, 45.5 MHz", "line3": "1 dringend", "line4": "A — Keine", "line5": "1 liegend", "line6": "N — Kein Feind", "line7": "C — Rauch", "line8": "NATO-Soldat", "line9": "Offenes Gelände, keine Kontaminierung"}
"""

    return f"""Du bist ein militaerischer Sanitaets-Assistent. Extrahiere aus dem Text die Felder als JSON.

Felder:
{fields_list}

Regeln:
- Nutze NUR Informationen aus dem Text
- Felder ohne Info: leerer String ""
- Kurze, praezise Werte
- Bei Select-Feldern: nutze die passende Option
{example}
Text: {text}

JSON:"""


def _call_ollama(prompt: str, label: str = "LLM") -> dict:
    """Ruft Ollama auf mit GPU-Fallback auf CPU bei OOM.
    keep_alive=-1 verhindert dass das Modell zwischen Analysen aus dem RAM
    fällt (Ollama-Default ist 5 min), wichtig für unseren permanenten
    Whisper+Qwen-Parallelbetrieb im Headless-Mode.
    temperature=0 + num_predict=400 macht den Decode deterministisch und
    schneller — für Feld-Extraktion und Segmentierung kein Kreativitäts-
    bedarf, Schnelligkeit zählt."""
    for num_gpu in [20, 0]:
        gpu_label = f"GPU:{num_gpu}" if num_gpu > 0 else "CPU"
        try:
            response = httpx.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {
                        "num_gpu": num_gpu,
                        "temperature": 0.0,
                        "num_predict": 400,
                        "top_k": 1,
                    },
                    "keep_alive": -1,
                },
                timeout=180,
            )
            if response.status_code == 200:
                result = response.json()
                if "error" in result:
                    print(f"{label} ({gpu_label}): Ollama-Fehler: {result['error'][:100]}")
                    if num_gpu > 0:
                        print(f"{label}: GPU Fehler, Fallback auf CPU...")
                        continue
                    return {}
                raw = result.get("response", "{}")
                try:
                    extracted = json.loads(raw)
                    print(f"{label} ({gpu_label}): {len([v for v in extracted.values() if v])} Felder extrahiert")
                    return extracted
                except json.JSONDecodeError:
                    print(f"{label}: JSON Parse Fehler: {raw[:200]}")
                    return {}
            else:
                print(f"{label} ({gpu_label}): HTTP {response.status_code}")
                if response.status_code == 500 and num_gpu > 0:
                    print(f"{label}: GPU OOM, Fallback auf CPU...")
                    continue
                return {}
        except Exception as e:
            print(f"{label} ({gpu_label}): Fehler: {e}")
            if num_gpu > 0:
                continue
            return {}
    return {}


def _unload_ollama_model():
    """Entlädt das Ollama-Modell aus GPU-RAM (keep_alive=0)."""
    try:
        httpx.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": "", "keep_alive": 0},
            timeout=10,
        )
        print(f"Ollama-Modell {OLLAMA_MODEL} aus GPU entladen")
    except Exception as e:
        print(f"Ollama entladen Fehler: {e}")


def run_llm_extraction(template_id: str, text: str) -> dict:
    """Extrahiert Template-Felder aus Text via Ollama LLM."""
    prompt = build_extraction_prompt(template_id, text)
    if not prompt:
        return {}
    return _call_ollama(prompt, "Feldextraktion")


# ---------------------------------------------------------------------------
# Transkript-Segmentierung (mehrere Patienten in einem Diktat)
# ---------------------------------------------------------------------------
SEGMENTATION_PROMPT = """Du zerlegst Sanitäts-Transkripte der Bundeswehr in einzelne Patienten.

KRITISCHE REGEL: patient_count MUSS exakt der Länge des patients-Arrays entsprechen. Wenn du 3 Patienten zählst, MÜSSEN 3 Einträge im Array stehen. KEINE Zusammenfassungen mehrerer Patienten in einem Eintrag.

REGELN:
1. Ein Patient mit mehreren Verletzungen = EIN Array-Eintrag. "Schusswunde Bein und Schnitt Hand beides" → ein Patient.
2. Neuer Patient NUR bei klaren Wörtern: "erster Patient", "zweiter Patient", "nächster Verwundeter", "jetzt zum anderen", "weiter mit dem nächsten", "jetzt eine Frau", "jetzt ein Kind".
3. Kopiere den Originaltext pro Patient 1:1 in das "text"-Feld (keine Umformulierung).
4. Im Zweifel lieber weniger Patienten als zu viele.

FORMAT (nur JSON, kein Markdown, keine Erklärung):
{"patient_count":N,"patients":[{"patient_nr":1,"text":"<originaltext patient 1>","summary":"<kurz>"},{"patient_nr":2,"text":"<originaltext patient 2>","summary":"<kurz>"}]}

BEISPIEL 1 — 1 Patient, 2 Verletzungen → genau 1 Array-Eintrag:
IN: "Patient männlich 30 Schusswunde Bein und Schnitt Hand beides blutet Puls 110"
OUT: {"patient_count":1,"patients":[{"patient_nr":1,"text":"Patient männlich 30 Schusswunde Bein und Schnitt Hand beides blutet Puls 110","summary":"Mann 30, Schuss+Schnitt"}]}

BEISPIEL 2 — 2 Patienten → genau 2 Array-Einträge, jeder mit eigenem Text:
IN: "Erster Patient Soldat 32 Stabsgefreiter Müller Schusswunde Oberschenkel T1. Zweiter eine Soldatin 28 Schmidt Splitterverletzung Arm T2 läuft noch."
OUT: {"patient_count":2,"patients":[{"patient_nr":1,"text":"Erster Patient Soldat 32 Stabsgefreiter Müller Schusswunde Oberschenkel T1.","summary":"Müller 32, Schuss Oberschenkel, T1"},{"patient_nr":2,"text":"Zweiter eine Soldatin 28 Schmidt Splitterverletzung Arm T2 läuft noch.","summary":"Schmidt 28, Splitter Arm, T2"}]}

BEISPIEL 3 — 3 Patienten → genau 3 Array-Einträge:
IN: "Erster männlich 40 Schuss Brust kritisch. Nächster Frau 30 Kopf bewusstlos. Dritter Verbrennung Arm stabil."
OUT: {"patient_count":3,"patients":[{"patient_nr":1,"text":"Erster männlich 40 Schuss Brust kritisch.","summary":"Mann 40, Schuss Brust, kritisch"},{"patient_nr":2,"text":"Nächster Frau 30 Kopf bewusstlos.","summary":"Frau 30, Kopf, bewusstlos"},{"patient_nr":3,"text":"Dritter Verbrennung Arm stabil.","summary":"Verbrennung Arm, stabil"}]}

TRANSKRIPT:
"""


BOUNDARY_PROMPT = """Zerlege Sanitäts-Transkripte in Patienten. Gib die Satzindizes zurück an denen ein NEUER Patient startet.

WICHTIGSTE REGEL: Ein Satz der "Der nächste Patient ist ..." oder "Zweiter Patient ..." oder "Weiter mit ..." enthält, IST SELBST der Start des neuen Patienten. Er gehört NICHT zum vorherigen.

WEITERE REGELN:
- Patient-Start-Signale: "erster/zweiter/dritter Patient", "nächster Verwundeter/Patient", "weiter mit dem nächsten", "jetzt zum anderen", "dann noch ein", "jetzt eine Frau", "es folgt", "als nächstes ist", "eine weitere Verletzte".
- KEIN Start-Signal: Sätze die nur Verletzungen, Vitals oder Behandlung eines bereits genannten Patienten beschreiben ("Er hat...", "Sie hat...", "Puls...", "Atmung...", "Maßnahmen...").
- KEIN Start-Signal: Einleitungssätze ohne Patient-Info ("Hier spricht...", "Ich bin am Ort", "Ich habe drei Verwundete") — sie gehören zum ersten echten Patient-Satz.
- "und", "außerdem", "zusätzlich", "auch" = SELBER Patient.

Antwort: JSON {"starts":[liste]} — sonst NICHTS.

BEISPIEL 1 — 3 Patienten mit Arzt-Einleitung:
[0] Ich bin am Unfallort und habe drei Verwundete
[1] Der erste ist Soldat Weber 25 Schussverletzung Bauch
[2] Weiter mit dem nächsten Patienten
[3] Zweiter eine Soldatin Becker 30 Platzwunde Kopf
[4] Dann noch ein dritter Patient Fischer 22 Splitter Oberschenkel
{"starts":[1,3,4]}

BEISPIEL 2 — "Der nächste Patient ist X" startet neuen Patient (GENAU DIESER Satz, nicht der folgende):
[0] Hier spricht Oberfeldarzt Mueller
[1] Ich untersuche die Hauptgefreite Erika Schmidt
[2] Sie hat Oberschenkelfraktur und Blutung
[3] SpO2 91 Puls 110
[4] Der nächste Patient ist der Stabsunteroffizier Marius Müller
[5] Er hat eine leichte Kopfverletzung mit Aspirin behandelt
{"starts":[1,4]}

BEISPIEL 3 — 1 Patient mit mehreren Sätzen (KEIN Split):
[0] Patient männlich 30 Schusswunde Bein
[1] Auch Schnittwunde Hand beides blutet
[2] Puls 130 Atmung normal
[3] Bewusstsein klar
{"starts":[0]}

BEISPIEL 4 — 2 Patienten, zweiter mit "Wir haben noch":
[0] Hier spricht Oberfeldarzt Meier
[1] Die Hauptgefreite Schmidt hat eine Beinverletzung Puls 110
[2] Wir haben noch eine weitere Verletzte die Oberst Meier-Lai
[3] Sie hat nur leichten Husten
{"starts":[1,2]}

Sätze:
"""


def _split_sentences(text: str) -> list[str]:
    """Schlankes Satz-Splitting für deutsche Sanitäts-Transkripte.
    Nutzt Satzzeichen + min. 30 chars Länge — zu kurze Fragmente werden
    ans vorherige Segment angehängt."""
    import re
    # Split bei . ! ? gefolgt von Space/Newline oder Ende
    raw = re.split(r"(?<=[.!?])\s+", text.strip())
    # Zu kurze Fragmente zusammenführen
    merged: list[str] = []
    for seg in raw:
        seg = seg.strip()
        if not seg:
            continue
        if merged and len(merged[-1]) < 30:
            merged[-1] = merged[-1] + " " + seg
        else:
            merged.append(seg)
    return merged


def segment_transcript_to_patients(transcript: str) -> dict:
    """Chunk-basierte Segmentierung.

    Ablauf:
      1. Split in Sätze
      2. Qwen erhält nur die Satzliste und gibt die Start-Indizes neuer
         Patienten zurück — das ist eine viel einfachere Aufgabe als
         "erzeuge eine komplette Patient-Struktur".
      3. Wir bauen die Patient-Records lokal auf: Für jeden Startindex
         sammeln wir Sätze bis zum nächsten Startindex.
      4. Der **Originaltext** bleibt damit 1:1 erhalten — kein Detail-Verlust.
    """
    if not transcript or not transcript.strip():
        return {"patient_count": 0, "patients": []}

    sentences = _split_sentences(transcript)
    if not sentences:
        return {"patient_count": 1, "patients": [{"patient_nr": 1, "text": transcript.strip(), "summary": ""}]}

    # Wenn sehr kurz: gar nicht erst fragen, das ist ein Patient
    if len(sentences) <= 2:
        return {"patient_count": 1, "patients": [{"patient_nr": 1, "text": transcript.strip(), "summary": ""}]}

    numbered = "\n".join(f"[{i}] {s}" for i, s in enumerate(sentences))
    prompt = BOUNDARY_PROMPT + numbered + "\n\nAntwort:"
    result = _call_ollama(prompt, "Segmentierung")
    print(f"[SEGMENT] {len(sentences)} Sätze → Qwen sagt starts={result.get('starts') if isinstance(result, dict) else result}", flush=True)

    starts: list[int] = []
    if isinstance(result, dict):
        raw_starts = result.get("starts") or []
        if isinstance(raw_starts, list):
            for x in raw_starts:
                try:
                    idx = int(x)
                    if 0 <= idx < len(sentences) and idx not in starts:
                        starts.append(idx)
                except (ValueError, TypeError):
                    continue
    starts.sort()
    # Fallback: Kein Start erkannt → alles als ein Patient
    if not starts:
        starts = [0]

    # Wenn Satz 0 selbst klar einen Patient beginnt (z. B. "Erster Patient
    # männlich 40 Schusswunde..."), dann muss 0 in der starts-Liste stehen.
    # Sonst wuerde der Einleitungs-Fix unten Satz 0 mit Satz 1 mergen und
    # einen echten Patienten verlieren.
    import re as _re
    _first_patient_re = _re.compile(
        r"^\s*(der\s+)?(erste[rn]?|erster)\s+(patient|verwundete[rn]?)",
        _re.IGNORECASE,
    )
    if sentences and _first_patient_re.match(sentences[0]) and 0 not in starts:
        starts.insert(0, 0)

    # Sätze vor dem ersten Patient-Start sind Einleitung und gehören zu Patient 1:
    # Wir ziehen den ersten Startindex auf 0 herunter und damit werden alle
    # Einleitungssätze Teil des ersten Patienten-Segments.
    if starts[0] > 0:
        starts[0] = 0

    # Sätze in Patient-Segmente aufteilen
    patients: list[dict] = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(sentences)
        seg_text = " ".join(sentences[start:end]).strip()
        if seg_text:
            patients.append({
                "patient_nr": len(patients) + 1,
                "text": seg_text,
                "summary": "",
            })

    # Post-Merge 1: Kurze Übergangs-Segmente ("Jetzt weiter mit dem nächsten
    # Patienten" o. ä.) haben keine Patient-Info und werden mit dem
    # *nachfolgenden* Segment zusammengeführt.
    TRANSITION_HINTS = (
        "jetzt weiter", "dann weiter", "nun weiter", "weiter mit",
        "jetzt zum nächsten", "dann zum nächsten", "als nächstes",
    )
    merged: list[dict] = []
    pending_prefix = ""
    for p in patients:
        text = p["text"]
        low = text.lower().strip()
        is_transition = len(text) < 80 and any(h in low for h in TRANSITION_HINTS)
        if is_transition:
            pending_prefix = (pending_prefix + " " + text).strip()
            continue
        if pending_prefix:
            text = pending_prefix + " " + text
            pending_prefix = ""
        merged.append({"patient_nr": len(merged) + 1, "text": text, "summary": p.get("summary", "")})
    if pending_prefix and merged:
        merged[-1]["text"] = merged[-1]["text"] + " " + pending_prefix

    # Post-Merge 2: Segmente die mit einem Pronomen starten und keinen
    # eigenen Namen/Patient-Marker haben, sind Fortsetzung des vorherigen
    # Segments. Beispiel:
    #   Segment A: "Der nächste Patient ist Marius Müller."
    #   Segment B: "Er hat eine leichte Kopfverletzung..."
    # → B gehört zu A. Qwen trennt gelegentlich solche Paare, weil "Er" wie
    # ein neuer Subjekt-Start aussieht.
    PRONOUN_STARTS = (
        "er hat", "sie hat", "es hat",
        "er ist", "sie ist", "es ist",
        "er wurde", "sie wurde", "es wurde",
        "ihr puls", "sein puls", "ihr blutdruck", "sein blutdruck",
        "ihre atmung", "seine atmung", "ihre verletzung", "seine verletzung",
        "ihre wunde", "seine wunde",
        "sein sauerstoff", "ihr sauerstoff",
        "bewusstsein", "puls", "atmung", "sauerstoff",
    )
    PATIENT_MARKERS = (
        "patient", "verwundeter", "verwundete", "soldat", "soldatin",
        "hauptgefreite", "stabsunteroffizier", "feldwebel", "oberst",
        "hauptmann", "leutnant", "oberst", "gefreiter", "hauptgefreiter",
        "unteroffizier", "mann", "frau", "kind",
    )
    # Maximale Länge für einen "Fortsetzungs"-Eintrag. Alles darüber ist ein
    # eigenständiger Patient-Block mit eigenen Vitals/Behandlung, auch wenn
    # er mit "Er hat..." beginnt. Gemessen an Beispielen:
    #   F5 Übergang: "Jetzt weiter mit dem nächsten Patienten." ~40 chars → merge
    #   F6 Folgesatz: "Er hat eine leichte Kopfverletzung und etwas Kopfschmerzen,
    #     konnte aber mit Aspirin vor Ort behoben werden." ~107 chars → NICHT merge
    PRONOUN_MERGE_MAX = 80
    merged2: list[dict] = []
    for p in merged:
        t = p["text"].strip()
        t_low = t.lower()
        starts_with_pronoun = any(t_low.startswith(h) for h in PRONOUN_STARTS)
        has_patient_marker = any(m in t_low for m in PATIENT_MARKERS)
        is_short = len(t) < PRONOUN_MERGE_MAX
        if starts_with_pronoun and not has_patient_marker and is_short and merged2:
            merged2[-1]["text"] = merged2[-1]["text"] + " " + t
            continue
        merged2.append({"patient_nr": len(merged2) + 1, "text": t, "summary": p.get("summary", "")})
    patients = merged2

    if not patients:
        patients = [{"patient_nr": 1, "text": transcript.strip(), "summary": ""}]

    return {"patient_count": len(patients), "patients": patients}


@app.get("/api/pending")
async def list_pending_transcripts():
    """Gibt alle noch nicht analysierten (oder gerade wartenden) Transkripte
    zurück. Das Frontend füllt daraus die Pending-Liste beim Page-Load."""
    return {"pending": state.pending_transcripts}


def _find_pending(tid: str) -> dict | None:
    for p in state.pending_transcripts:
        if p.get("id") == tid:
            return p
    return None


@app.post("/api/analyze/pending")
async def analyze_pending_transcript(body: dict):
    """Manueller Trigger: Analysiert ein bestimmtes Pending-Transkript
    (identifiziert über id) und legt N Patienten daraus an.
    Wenn keine id gegeben ist: nimmt das neueste unanalysierte."""
    tid = (body or {}).get("id")
    pt: dict | None = None
    if tid:
        pt = _find_pending(tid)
    else:
        pt = next((p for p in reversed(state.pending_transcripts) if not p.get("analyzed")), None)
    if not pt or not pt.get("full_text"):
        return {"status": "error", "error": "Kein Transkript gefunden. Erst aufnehmen."}
    if pt.get("analyzed"):
        return {"status": "error", "error": "Transkript wurde schon analysiert."}
    if pt.get("analyzing"):
        return {"status": "error", "error": "Analyse läuft bereits."}

    pt["analyzing"] = True
    full_text = pt["full_text"]
    record_time = pt.get("time") or datetime.now().strftime("%H:%M:%S")
    await broadcast({"type": "analysis_started", "chars": len(full_text), "pending_id": pt["id"]})
    try:
        created = await _segment_and_create_patients(full_text, record_time)
    finally:
        pt["analyzing"] = False
    pt["analyzed"] = True
    pt["created_patient_ids"] = created
    count = len(created)
    tts.speak(f"{count} Patient angelegt" if count == 1 else f"{count} Patienten angelegt")
    await broadcast({
        "type": "analysis_complete",
        "pending_id": pt["id"],
        "count": count,
        "created_patient_ids": created,
    })
    return {"status": "ok", "created_patient_ids": created, "count": count, "pending_id": pt["id"]}


@app.post("/api/analyze/discard")
async def discard_pending_transcript(body: dict):
    """Verwirft ein Pending-Transkript (identifiziert über id).
    Wenn keine id: verwirft das neueste unanalysierte."""
    tid = (body or {}).get("id")
    pt: dict | None = None
    if tid:
        pt = _find_pending(tid)
    else:
        pt = next((p for p in reversed(state.pending_transcripts) if not p.get("analyzed")), None)
    if not pt:
        return {"status": "error", "error": "Kein Transkript gefunden"}
    state.pending_transcripts = [p for p in state.pending_transcripts if p.get("id") != pt["id"]]
    await broadcast({"type": "pending_transcript_discarded", "pending_id": pt["id"]})
    return {"status": "ok", "pending_id": pt["id"]}


@app.post("/api/test/segment")
async def test_segment(body: dict):
    """Proof-of-Concept-Endpoint: POST {"transcript": "..."} →
    Qwen segmentiert das Transkript in Patienten-Blöcke.
    Dient zum Testen des Prompts BEVOR wir den produktiven Flow umbauen."""
    transcript = body.get("transcript", "")
    if not transcript:
        return {"error": "no transcript provided", "usage": {"transcript": "<langer text>"}}
    import time as _t
    t0 = _t.monotonic()
    result = segment_transcript_to_patients(transcript)
    elapsed = _t.monotonic() - t0
    result["_meta"] = {
        "elapsed_s": round(elapsed, 2),
        "model": OLLAMA_MODEL,
        "input_chars": len(transcript),
    }
    return result


# ---------------------------------------------------------------------------
# Document Generation
# ---------------------------------------------------------------------------
def _docx_add_header(doc, title):
    """Einheitlicher DOCX-Header."""
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    header_para = doc.add_paragraph()
    header_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = header_para.add_run(title)
    run.bold = True
    run.font.size = Pt(16)
    doc.add_paragraph()


def _docx_add_patient_table(doc, session):
    """Patienten-Stammdaten Tabelle."""
    tpl = RECORD_TEMPLATES.get(session.get("template_id", "freitext"), {})
    base_fields = [
        ("Patient", session.get("patient_name", "Unbekannt")),
        ("Datum", session.get("date", datetime.now().strftime("%Y-%m-%d %H:%M"))),
        ("Einsatzort", session.get("location", "Feld")),
        ("Sanitäter", session.get("medic", "—")),
        ("Dokumenttyp", tpl.get("name", "Freitext")),
    ]
    table = doc.add_table(rows=len(base_fields), cols=2)
    table.style = "Table Grid"
    for i, (label, value) in enumerate(base_fields):
        cell0 = table.rows[i].cells[0]
        cell0.text = label
        for p in cell0.paragraphs:
            for r in p.runs:
                r.bold = True
        table.rows[i].cells[1].text = str(value)
    doc.add_paragraph()


def _docx_add_template_data(doc, session):
    """Template-spezifische Felder ins DOCX schreiben."""
    template_id = session.get("template_id", "freitext")
    tpl = RECORD_TEMPLATES.get(template_id)
    tdata = session.get("template_data", {})

    if not tpl or not tpl.get("sections") or not tdata:
        return

    for section in tpl["sections"]:
        doc.add_heading(section["title"], level=2)
        table = doc.add_table(rows=0, cols=2)
        table.style = "Table Grid"
        for field in section["fields"]:
            val = tdata.get(field["key"], "")
            if isinstance(val, list):
                val = ", ".join(val)
            if val:
                row = table.add_row()
                cell0 = row.cells[0]
                cell0.text = field["label"]
                for p in cell0.paragraphs:
                    for r in p.runs:
                        r.bold = True
                row.cells[1].text = str(val)
        if len(table.rows) == 0:
            # Leere Section — Platzhalter
            row = table.add_row()
            row.cells[0].text = "(Keine Daten)"
        doc.add_paragraph()


def _docx_add_transcripts(doc, session):
    """Transkriptions-Einträge ins DOCX."""
    records = session.get("records", [])
    if records:
        doc.add_heading("Spracheingabe / Transkription", level=2)
        for i, record in enumerate(records, 1):
            para = doc.add_paragraph()
            run_time = para.add_run(f"[{record['time']}] ")
            run_time.bold = True
            run_time.font.size = Pt(9)
            para.add_run(record["text"])
        doc.add_paragraph()


def _docx_add_footer(doc):
    """DOCX Footer."""
    doc.add_paragraph()
    doc.add_heading("Unterschrift Sanitäter", level=2)
    doc.add_paragraph()
    doc.add_paragraph("_" * 30)

    doc.add_paragraph()
    footer = doc.add_paragraph()
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = footer.add_run("CGI Deutschland — AFCEA Demonstrator — KI-gestuetzte Felddokumentation (SAFIR)")
    run.font.size = Pt(8)
    run.italic = True


def generate_docx(session: dict) -> Path:
    """Generiert eine Patienten-Akte als Word-Dokument."""
    doc = Document()
    template_id = session.get("template_id", "freitext")
    tpl = RECORD_TEMPLATES.get(template_id, RECORD_TEMPLATES["freitext"])

    # Triage-Farbe in Header für TCCC
    tdata = session.get("template_data", {})
    triage = tdata.get("triage_cat", "")

    if template_id == "tccc":
        title = "TCCC CASUALTY CARD"
        if "T1" in triage:
            title += " — SOFORT (T1)"
        elif "T2" in triage:
            title += " — AUFGESCHOBEN (T2)"
        elif "T3" in triage:
            title += " — LEICHT (T3)"
        elif "T4" in triage:
            title += " — ABWARTEND (T4)"
    elif template_id == "9liner":
        title = "9-LINER MEDEVAC ANFORDERUNG"
    elif template_id == "mist":
        title = "MIST PATIENTENUEBERGABE"
    elif template_id == "erstbefund":
        title = "ERSTBEFUND — SANITAETSDIENST"
    else:
        title = "SANITAETSDIENST — PATIENTENAKTE"

    _docx_add_header(doc, title)
    _docx_add_patient_table(doc, session)
    _docx_add_template_data(doc, session)
    _docx_add_transcripts(doc, session)
    _docx_add_footer(doc)

    patient = session.get("patient_name", "patient").replace(" ", "_")
    filename = f"{template_id}_{patient}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
    filepath = PROTOCOLS_DIR / filename
    doc.save(str(filepath))
    return filepath


# ---------------------------------------------------------------------------
# Internal helpers (used by both API and Vosk)
# ---------------------------------------------------------------------------
async def start_recording_internal():
    """Startet Aufnahme (intern, ohne HTTP)."""
    if state.recording or state.transcribing:
        return
    if not state.model_path:
        return

    state.audio_chunks = []
    state.recording = True
    # Vosk pausiert waehrend Aufnahme
    state.vosk_listening = False

    # Wenn kein persistenter Stream läuft, eigenen oeffnen
    if not state.persistent_stream:
        try:
            native_rate = get_device_samplerate(state.audio_device)
            state.stream = sd.InputStream(
                samplerate=native_rate, channels=1, dtype="float32",
                blocksize=int(native_rate * 0.1),
                device=state.audio_device, callback=persistent_audio_callback,
            )
            state.stream.start()
            state._stream_samplerate = native_rate
        except Exception as e:
            state.recording = False
            return

    asyncio.create_task(_auto_stop_timer())
    await broadcast({"type": "recording_started"})
    oled_menu.show_status("AUFNAHME", "Sprechen...")


async def create_session_internal(patient_name, location, medic, template_id):
    """Erstellt Session (intern, ohne HTTP)."""
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    state.sessions[session_id] = {
        "id": session_id,
        "template_id": template_id,
        "template_data": {},
        "patient_name": patient_name,
        "patient_id": state.active_patient or "",
        "location": location,
        "medic": medic,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "records": [],
        "created": datetime.now().isoformat(),
    }
    state.active_session = session_id
    await broadcast({"type": "session_created", "session": state.sessions[session_id]})


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "config": _config})


@app.get("/api/status")
async def get_status():
    return {
        "system": get_system_stats(),
        "model": state.current_model,
        "model_loaded": state.model_loaded,
        "model_loading": state.model_loading,
        "model_ram_mb": state.model_ram_mb,
        "recording": state.recording,
        "transcribing": state.transcribing,
        "audio_device": state.audio_device,
        "active_session": state.active_session,
        "session_data": state.sessions.get(state.active_session) if state.active_session else None,
        "language": state.language,
        "vosk_enabled": state.vosk_enabled,
        "vosk_listening": state.vosk_listening,
        "active_patient": state.active_patient,
        "patient_count": len(state.patients),
        "backend_reachable": state.backend_reachable,
    }


@app.get("/api/templates")
async def get_templates():
    """Gibt alle verfuegbaren Templates zurück."""
    return {"templates": list(RECORD_TEMPLATES.values())}


@app.get("/api/models")
async def get_models():
    return {"models": state.available_models(), "current": state.current_model}


@app.post("/api/models/load")
async def load_model(body: dict):
    name = body.get("model", "medium")
    path = MODELS_DIR / f"ggml-{name}.bin"
    if not path.exists():
        return {"error": f"Modell nicht gefunden: {path}"}

    if state.model_loading:
        return {"error": "Modell wird bereits geladen"}

    state.model_loading = True
    await broadcast({"type": "model_loading", "model": name})

    loop = asyncio.get_event_loop()
    success = await loop.run_in_executor(None, start_whisper_server, path)

    state.model_loading = False

    if success:
        state.model_path = path
        state.current_model = name
        await broadcast({
            "type": "model_loaded",
            "model": name,
            "ram_mb": state.model_ram_mb,
            "loaded": True,
        })
        return {"status": "ok", "model": name, "ram_mb": state.model_ram_mb}
    else:
        return {"error": f"Modell {name} konnte nicht geladen werden"}


@app.post("/api/models/unload")
async def unload_model():
    stop_whisper_server()
    old_model = state.current_model
    state.current_model = None
    state.model_path = None
    await broadcast({"type": "model_unloaded", "model": old_model})
    return {"status": "ok"}


@app.get("/api/devices")
async def get_devices():
    return {"devices": state.audio_devices(), "current": state.audio_device}


@app.post("/api/devices/select")
async def select_device(body: dict):
    state.audio_device = body.get("device_id")
    # Persistenten Stream mit neuem Device neu starten
    if state.persistent_stream or state.vosk_enabled:
        stop_persistent_stream()
        start_persistent_stream()
    return {"status": "ok", "device_id": state.audio_device}


@app.post("/api/language")
async def set_language(body: dict):
    state.language = body.get("language", "de")
    return {"status": "ok", "language": state.language}


@app.post("/api/session/create")
async def create_session(body: dict):
    template_id = body.get("template_id", "freitext")
    await create_session_internal(
        body.get("patient_name", "Unbekannt"),
        body.get("location", "Feld"),
        body.get("medic", ""),
        template_id,
    )
    return {"status": "ok", "session_id": state.active_session}


@app.post("/api/session/template-data")
async def save_template_data(body: dict):
    """Speichert Template-Felddaten für die aktive Session."""
    sid = body.get("session_id", state.active_session)
    if not sid or sid not in state.sessions:
        return {"error": "Keine aktive Session"}
    data = body.get("data", {})
    state.sessions[sid]["template_data"].update(data)
    return {"status": "ok"}


@app.get("/api/sessions")
async def list_sessions():
    return {"sessions": list(state.sessions.values()), "active": state.active_session}


@app.post("/api/session/select")
async def select_session(body: dict):
    sid = body.get("session_id")
    if sid in state.sessions:
        state.active_session = sid
        return {"status": "ok"}
    return {"error": "Session nicht gefunden"}


# ---------------------------------------------------------------------------
# Patient Registry + RFID
# ---------------------------------------------------------------------------
@app.post("/api/patient/register")
async def register_patient(body: dict):
    """Patient anlegen mit RFID-Tag + Triage."""
    if not state.model_loaded:
        return {"error": "Sprachmodell nicht geladen"}
    cfg = load_config()
    device_id = cfg.get("device_id", "jetson-01")

    name = body.get("name", "Unbekannt")
    triage = body.get("triage", "")
    rfid_tag_id = body.get("rfid_tag_id", "")
    created_by = body.get("created_by", "") or cfg.get("default_medic", "")

    patient = create_patient_record(
        name=name,
        triage=triage,
        rfid_tag_id=rfid_tag_id,
        device_id=device_id,
        created_by=created_by,
    )
    # Einheit aus Config setzen
    patient["unit"] = cfg.get("unit_name", "")

    pid = patient["patient_id"]
    state.patients[pid] = patient
    state.rfid_map[patient["rfid_tag_id"]] = pid
    state.active_patient = pid

    await broadcast({
        "type": "patient_registered",
        "patient": patient,
    })
    tts.announce_patient_created()

    return {"status": "ok", "patient_id": pid, "patient": patient}


@app.get("/api/patient/{patient_id}")
async def get_patient(patient_id: str):
    """Patientendaten abrufen."""
    if patient_id not in state.patients:
        return {"error": "Patient nicht gefunden"}
    return state.patients[patient_id]


@app.get("/api/patients")
async def list_patients():
    """Alle registrierten Patienten auflisten."""
    return {
        "patients": list(state.patients.values()),
        "active_patient": state.active_patient,
    }


@app.post("/api/patient/{patient_id}/select")
async def select_patient(patient_id: str):
    """Aktiven Patient auswaehlen."""
    if patient_id not in state.patients:
        return {"error": "Patient nicht gefunden"}
    state.active_patient = patient_id
    await broadcast({
        "type": "patient_selected",
        "patient_id": patient_id,
        "patient": state.patients[patient_id],
    })
    return {"status": "ok"}


@app.post("/api/patient/{patient_id}/update")
async def update_patient(patient_id: str, body: dict):
    """Patientendaten aktualisieren (Felder mergen)."""
    if patient_id not in state.patients:
        return {"error": "Patient nicht gefunden"}
    patient = state.patients[patient_id]
    data = body.get("data", {})
    for key, value in data.items():
        if key in patient:
            patient[key] = value
    # Vitals separat mergen
    vitals = body.get("vitals", {})
    if vitals:
        patient["vitals"].update(vitals)
    await broadcast({"type": "patient_update", "patient": patient})
    return {"status": "ok", "patient": patient}


@app.delete("/api/patient/{patient_id}")
async def delete_patient(patient_id: str):
    """Patient löschen."""
    if patient_id not in state.patients:
        return {"status": "ok", "patient_id": patient_id}
    # Aus State entfernen
    patient = state.patients.pop(patient_id)
    # RFID-Mapping entfernen
    rfid = patient.get("rfid_tag_id", "")
    if rfid and rfid in state.rfid_map:
        del state.rfid_map[rfid]
    # Aktiven Patient zurücksetzen
    if state.active_patient == patient_id:
        state.active_patient = ""
    await broadcast({"type": "patient_deleted", "patient_id": patient_id})
    return {"status": "ok", "patient_id": patient_id}


@app.post("/api/patient/{patient_id}/status")
async def update_patient_status(patient_id: str, body: dict):
    """Flow-Status ändern."""
    if patient_id not in state.patients:
        return {"error": "Patient nicht gefunden"}
    new_status = body.get("flow_status", "")
    if new_status not in [s.value for s in PatientFlowStatus]:
        return {"error": f"Ungültiger Status: {new_status}"}
    patient = state.patients[patient_id]
    old_status = patient["flow_status"]
    patient["flow_status"] = new_status
    patient["timeline"].append({
        "time": datetime.now().isoformat(),
        "role": patient["current_role"],
        "event": "status_change",
        "details": f"{FLOW_STATUS_LABELS.get(old_status, old_status)} -> {FLOW_STATUS_LABELS.get(new_status, new_status)}",
    })
    await broadcast({"type": "patient_update", "patient": patient})
    return {"status": "ok", "patient": patient}


@app.post("/api/rfid/batch")
async def rfid_batch_write():
    """GUI-Trigger: Schreibt alle Patienten ohne RFID-Karte nacheinander
    auf leere MIFARE-Karten (Fahrzeug-Workflow). Shared Handler —
    identisch zu OLED-Menü 'RFID schreiben' und Sprachbefehl."""
    asyncio.create_task(voice_write_card())
    return {"status": "started"}


@app.post("/api/rfid/scan")
async def rfid_scan(body: dict):
    """RFID-Tag scannen — Patient nachschlagen oder neuen anlegen."""
    tag_id = body.get("tag_id", "").strip()
    if not tag_id:
        # Neuen RFID-Tag generieren (Simulation)
        tag_id = generate_rfid_tag()

    # Nachschlagen
    existing_pid = lookup_by_rfid(state.rfid_map, tag_id)
    if existing_pid and existing_pid in state.patients:
        state.active_patient = existing_pid
        patient = state.patients[existing_pid]
        await broadcast({
            "type": "rfid_scan",
            "action": "found",
            "patient": patient,
        })
        tts.announce_rfid_linked()
        return {"status": "found", "patient_id": existing_pid, "patient": patient}

    # Neuen Patient anlegen (mit Tag, Name wird spaeter gesetzt)
    await broadcast({
        "type": "rfid_scan",
        "action": "new",
        "tag_id": tag_id,
    })
    return {"status": "new", "tag_id": tag_id}


# ---------------------------------------------------------------------------
# Backend-WebSocket-Client
# ---------------------------------------------------------------------------
# Persistente WS-Verbindung vom Jetson zum Leitstellen-Backend. Ein einziger
# Code-Pfad für alle Patient-Änderungen die vom Backend (oder von anderen
# BATs über das Backend) kommen — wir re-broadcasten sie 1:1 an unsere
# eigenen Dashboard-Clients, damit der Browser automatisch aktualisiert.

state.backend_ws_connected: bool = False
state.backend_ws_task = None


async def _backend_ws_loop():
    """Hält eine persistente WS-Verbindung zum Backend offen. Reconnectet
    automatisch mit exponential backoff. Eingehende Events werden in den
    lokalen state gemergt und an Jetson-WS-Clients weitergereicht."""
    import websockets
    import urllib.parse

    reconnect_delay = 2.0  # Wird bei erfolgreichem Connect auf 2.0 zurückgesetzt

    while True:
        cfg = load_config()
        backend_url = cfg.get("backend", {}).get("url", "")
        if not backend_url:
            await asyncio.sleep(10)
            continue

        # http://host:port → ws://host:port/ws
        parsed = urllib.parse.urlparse(backend_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        ws_url = f"{scheme}://{parsed.netloc}/ws"

        try:
            print(f"[BACKEND-WS] Verbinde zu {ws_url}...", flush=True)
            async with websockets.connect(ws_url, ping_interval=30, ping_timeout=10) as ws:
                state.backend_ws_connected = True
                print("[BACKEND-WS] Verbunden.", flush=True)
                await broadcast({"type": "backend_link", "connected": True})
                reconnect_delay = 2.0  # Reset nach erfolgreicher Verbindung

                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        continue
                    await _handle_backend_event(msg)
        except Exception as e:
            print(f"[BACKEND-WS] Verbindung verloren: {e}", flush=True)
        finally:
            state.backend_ws_connected = False
            try:
                await broadcast({"type": "backend_link", "connected": False})
            except Exception:
                pass

        # Exponential backoff mit Deckel bei 30 s
        reconnect_delay = min(reconnect_delay * 1.5, 30.0)
        print(f"[BACKEND-WS] Reconnect in {reconnect_delay:.1f} s", flush=True)
        await asyncio.sleep(reconnect_delay)


async def _handle_backend_event(msg: dict):
    """Verarbeitet ein vom Backend gesendetes Event. Mergt State und
    re-broadcastet an die Jetson-eigenen Frontend-Clients."""
    mtype = msg.get("type", "")

    if mtype == "init":
        # Snapshot beim Connect — alle Patienten vom Backend übernehmen.
        # Lokale Patienten die das Backend nicht kennt bleiben erhalten.
        remote_pts = msg.get("patients", [])
        added = 0
        for p in remote_pts:
            pid = p.get("patient_id")
            if not pid:
                continue
            if pid not in state.patients:
                state.patients[pid] = p
                rfid_tag = p.get("rfid_tag_id")
                if rfid_tag:
                    state.rfid_map[rfid_tag] = pid
                added += 1
            else:
                # Lokaler Eintrag gewinnt NUR wenn er neuere Zeitstempel hat
                local = state.patients[pid]
                if (p.get("timestamp_updated") or "") > (local.get("timestamp_updated") or ""):
                    state.patients[pid] = p
        print(f"[BACKEND-WS] init: {len(remote_pts)} Patienten vom Backend, {added} neu", flush=True)
        # Jetson-Clients informieren
        await broadcast({"type": "backend_init", "patient_count": len(remote_pts), "added": added})

    elif mtype in ("patient_new", "patient_update", "patient_registered"):
        p = msg.get("patient")
        if not p:
            return
        pid = p.get("patient_id")
        if not pid:
            return
        # Merge: Backend-Event überschreibt lokalen Eintrag
        state.patients[pid] = p
        rfid_tag = p.get("rfid_tag_id")
        if rfid_tag:
            state.rfid_map[rfid_tag] = pid
        print(f"[BACKEND-WS] {mtype}: {pid} ({p.get('name','?')})", flush=True)
        # An Jetson-Frontend weiterleiten, damit Dashboard sich aktualisiert
        await broadcast({"type": "patient_update", "patient": p})

    elif mtype == "patient_deleted":
        pid = msg.get("patient_id")
        if pid and pid in state.patients:
            state.patients.pop(pid, None)
            await broadcast({"type": "patient_deleted", "patient_id": pid})

    elif mtype == "transfer_update":
        # Backend meldet geänderten Flow-Status (z.B. bei Role 2 Übernahme)
        pid = msg.get("patient_id")
        if pid and pid in state.patients:
            new_state = msg.get("transfer_state") or ""
            if new_state == "sent":
                state.patients[pid]["synced"] = True
            await broadcast({"type": "transfer_update", "patient_id": pid,
                             "transfer_state": new_state})


async def sync_all_patients() -> dict:
    """Übermittelt alle nicht-synchronisierten Patienten an die Leitstelle."""
    cfg = load_config()
    backend_url = cfg.get("backend", {}).get("url", "")
    device_id = cfg.get("device_id", "jetson-01")

    if not backend_url:
        return {"sent": 0, "skipped": 0, "failed": 0, "error": "Kein Backend konfiguriert"}

    sent = 0
    skipped = 0
    failed = 0

    for pid, patient in state.patients.items():
        # Bereits übermittelte überspringen
        if patient.get("synced"):
            skipped += 1
            continue
        # Nur analysierte Patienten senden
        if not patient.get("analyzed"):
            skipped += 1
            continue

        transfer = copy.deepcopy(TRANSFER_SCHEMA)
        transfer["source_device"] = "jetson"
        transfer["device_id"] = device_id
        transfer["unit_name"] = cfg.get("unit_name", "")
        transfer["timestamp"] = datetime.now().isoformat()
        transfer["patient"] = patient
        transfer["flow_status"] = patient["flow_status"]
        transfer["rfid_tag_id"] = patient["rfid_tag_id"]

        try:
            response = httpx.post(f"{backend_url}/api/ingest", json=transfer, timeout=10)
            if response.status_code == 200:
                patient["synced"] = True
                patient["timeline"].append({
                    "time": datetime.now().isoformat(),
                    "role": patient["current_role"],
                    "event": "sent_to_backend",
                    "details": "An Leitstelle übermittelt",
                })
                await broadcast({"type": "patient_synced", "patient_id": pid, "patient": patient})
                sent += 1
            else:
                print(f"Sync Fehler für {pid}: HTTP {response.status_code}")
                failed += 1
        except Exception as e:
            print(f"Sync Fehler für {pid}: {e}")
            failed += 1

    state.backend_reachable = (sent > 0 or skipped > 0) and failed == 0

    # GPS-Simulation starten wenn Patienten gesendet wurden
    global _gps_active, _gps_index
    if sent > 0 and not _gps_active:
        _gps_active = True
        _gps_index = 0

    await broadcast({
        "type": "sync_complete",
        "sent": sent,
        "skipped": skipped,
        "failed": failed,
        "backend_reachable": state.backend_reachable,
    })

    return {"sent": sent, "skipped": skipped, "failed": failed}


@app.post("/api/position")
async def receive_position(body: dict):
    """Empfängt GPS-Position einer Einheit und broadcastet sie an alle Clients."""
    await broadcast({
        "type": "position_update",
        "position": {
            "unit_name": body.get("unit_name", ""),
            "device_id": body.get("device_id", ""),
            "lat": body.get("lat", 0),
            "lon": body.get("lon", 0),
            "heading": body.get("heading", 0),
            "speed_kmh": body.get("speed_kmh", 0),
        },
    })
    return {"status": "ok"}


@app.post("/api/simulation/reset")
async def reset_simulation():
    """Setzt die Simulation zurück."""
    return {"status": "ok"}


@app.post("/api/data/reset")
async def data_reset():
    """Löscht ALLE Patientendaten für einen sauberen Demo-Neustart."""
    count = len(state.patients)
    state.patients.clear()
    state.rfid_map.clear()
    state.active_patient = ""
    state.sync_queue_depth = 0
    await broadcast({
        "type": "init",
        "model": state.current_model,
        "patients": [],
        "backend_reachable": state.backend_reachable,
    })
    print(f"Daten-Reset: {count} Patienten gelöscht")
    return {"status": "ok", "removed": count}


# ---------------------------------------------------------------------------
# Peer Discovery / Netzwerk-Teilnehmer
# ---------------------------------------------------------------------------
PEER_TIMEOUT_HOURS = 5

@app.post("/api/heartbeat")
async def receive_heartbeat(body: dict):
    """Empfängt Heartbeat von einem Netzwerk-Teilnehmer."""
    device_id = body.get("device_id", "")
    if not device_id:
        return {"error": "device_id fehlt"}
    state.peers[device_id] = {
        "unit_name": body.get("unit_name", "Unbekannt"),
        "unit_role": body.get("unit_role", ""),
        "system_name": body.get("system_name", ""),
        "device_id": device_id,
        "ip": body.get("ip", ""),
        "port": body.get("port", 8080),
        "last_seen": datetime.now().isoformat(),
        "patient_count": body.get("patient_count", 0),
    }
    return {"status": "ok", "peers": len(state.peers)}


@app.get("/api/peers")
async def get_peers():
    """Gibt alle bekannten Netzwerk-Teilnehmer zurück."""
    now = datetime.now()
    # Alte Peers entfernen (> PEER_TIMEOUT_HOURS)
    expired = [k for k, v in state.peers.items()
               if (now - datetime.fromisoformat(v["last_seen"])).total_seconds() > PEER_TIMEOUT_HOURS * 3600]
    for k in expired:
        del state.peers[k]

    peers_list = list(state.peers.values())
    # Eigene Instanz immer mit aufnehmen
    cfg = load_config()
    own = {
        "unit_name": cfg.get("unit_name", ""),
        "unit_role": cfg.get("unit_role", ""),
        "system_name": cfg.get("system_name", ""),
        "device_id": cfg.get("device_id", ""),
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


async def _heartbeat_loop():
    """Sendet periodisch Heartbeats an alle bekannten Peers (alle 30s)."""
    await asyncio.sleep(5)  # Warten bis Server bereit
    while True:
        try:
            cfg = load_config()
            own_device_id = cfg.get("device_id", "")
            own_unit_name = cfg.get("unit_name", "")
            backend_url = cfg.get("backend", {}).get("url", "")

            payload = {
                "device_id": own_device_id,
                "unit_name": own_unit_name,
                "unit_role": cfg.get("unit_role", ""),
                "system_name": cfg.get("system_name", ""),
                "ip": "",
                "port": 8080,
                "patient_count": len(state.patients),
            }

            # An Backend senden (falls konfiguriert)
            if backend_url:
                try:
                    httpx.post(f"{backend_url}/api/heartbeat", json=payload, timeout=5)
                except Exception:
                    pass

            # An alle bekannten Peers senden
            for peer in list(state.peers.values()):
                if peer["device_id"] == own_device_id:
                    continue
                ip = peer.get("ip", "")
                port = peer.get("port", 8080)
                if ip and ip != "127.0.0.1":
                    try:
                        httpx.post(f"http://{ip}:{port}/api/heartbeat", json=payload, timeout=3)
                    except Exception:
                        pass
        except Exception as e:
            print(f"Heartbeat Fehler: {e}")
        await asyncio.sleep(30)


@app.post("/api/patients/sync")
async def sync_patients_to_backend():
    """Alle Patienten an Leitstelle übermitteln (überspringt bereits synchronisierte)."""
    if not state.patients:
        return {"error": "Keine Patienten vorhanden"}
    result = await sync_all_patients()
    return {"status": "ok", **result}


# ---------------------------------------------------------------------------
# SitaWare Interoperabilität (CoT / NVG / APP-6D)
# ---------------------------------------------------------------------------
@app.get("/api/sitaware/status")
async def sitaware_status():
    """Status der SitaWare-Schnittstelle."""
    return sitaware.get_sitaware_status()


@app.get("/api/sitaware/cot")
async def sitaware_cot_export():
    """Exportiert alle Patienten als Cursor-on-Target XML Events."""
    if not state.patients:
        return {"error": "Keine Patienten vorhanden"}
    cfg = load_config()
    patients_list = list(state.patients.values())
    xml = sitaware.generate_cot_batch(
        patients_list,
        unit_name=cfg.get("unit_name", ""),
        device_id=cfg.get("device_id", ""),
    )
    from fastapi.responses import Response
    return Response(content=xml, media_type="application/xml",
                    headers={"Content-Disposition": "attachment; filename=safir_medevac_cot.xml"})


@app.get("/api/sitaware/nvg")
async def sitaware_nvg_export():
    """Exportiert Patienten als NATO Vector Graphics Overlay."""
    if not state.patients:
        return {"error": "Keine Patienten vorhanden"}
    cfg = load_config()
    patients_list = list(state.patients.values())
    xml = sitaware.generate_nvg_overlay(
        patients_list,
        unit_name=cfg.get("unit_name", ""),
    )
    from fastapi.responses import Response
    return Response(content=xml, media_type="application/xml",
                    headers={"Content-Disposition": "attachment; filename=safir_overlay.nvg"})


# Multi-Patient-Flow: Der BAT-Sanitäter kann mehrere Verwundete am Stück
# diktieren. 600 s = 10 min Safety-Buffer. Audio wird in 25 s-Chunks
# gestreamt (CHUNK_SECONDS), die Whisper parallel zur Aufnahme transkribiert.
MAX_RECORD_SECONDS = 600
RECORD_WARN_BEFORE_END = 30  # OLED-Warnung N Sekunden vor Ablauf
CHUNK_SECONDS = 25


@app.post("/api/record/start")
async def start_recording():
    if state.recording:
        return {"error": "Aufnahme läuft bereits"}
    if not state.model_path:
        return {"error": "Kein Modell geladen"}

    state.audio_chunks = []
    state.recording = True
    state.vosk_listening = False

    # Wenn kein persistenter Stream, eigenen oeffnen
    if not state.persistent_stream:
        try:
            native_rate = get_device_samplerate(state.audio_device)
            state.stream = sd.InputStream(
                samplerate=native_rate, channels=1, dtype="float32",
                blocksize=int(native_rate * 0.1),
                device=state.audio_device, callback=persistent_audio_callback,
            )
            state.stream.start()
            state._stream_samplerate = native_rate
        except Exception as e:
            state.recording = False
            return {"error": f"Audio-Fehler: {e}"}

    asyncio.create_task(_auto_stop_timer())
    await broadcast({"type": "recording_started"})
    oled_menu.show_status("AUFNAHME", "Sprechen...")
    return {"status": "recording", "max_seconds": MAX_RECORD_SECONDS}


async def _auto_stop_timer():
    await asyncio.sleep(MAX_RECORD_SECONDS)
    if state.recording:
        await broadcast({"type": "recording_auto_stop"})
        await stop_recording()


@app.post("/api/record/stop")
async def stop_recording():
    if not state.recording:
        return {"error": "Keine Aufnahme aktiv"}

    state.recording = False

    # Wenn eigener Stream (kein persistenter), schliessen
    if state.stream and not state.persistent_stream:
        state.stream.stop()
        state.stream.close()
        state.stream = None

    # Vosk wieder aktivieren
    if state.vosk_enabled:
        state.vosk_listening = True

    if not state.audio_chunks:
        return {"error": "Keine Audio-Daten"}

    audio_raw = np.concatenate(state.audio_chunks, axis=0)
    stream_rate = getattr(state, '_stream_samplerate', SAMPLE_RATE)
    # Resample auf 16kHz für Whisper
    if stream_rate != SAMPLE_RATE:
        audio = resample_to_16k(audio_raw, stream_rate)
    else:
        audio = audio_raw
    total_duration = len(audio) / SAMPLE_RATE

    if total_duration < 0.5:
        await broadcast({"type": "recording_stopped", "duration": total_duration, "error": "Zu kurz"})
        return {"error": "Aufnahme zu kurz"}

    await broadcast({"type": "recording_stopped", "duration": round(total_duration, 1)})

    chunk_samples = CHUNK_SECONDS * SAMPLE_RATE
    chunks = []
    for i in range(0, len(audio), chunk_samples):
        chunk = audio[i:i + chunk_samples]
        if len(chunk) >= SAMPLE_RATE * 0.5:
            chunks.append(chunk)

    total_chunks = len(chunks)
    all_texts = []
    total_proc_time = 0

    state.transcribing = True
    await broadcast({"type": "transcribing", "chunks": total_chunks})
    oled_menu.show_status("TRANSKRIPTION", f"{total_chunks} Chunk(s)...", 0)

    loop = asyncio.get_event_loop()

    for idx, chunk in enumerate(chunks):
        await broadcast({
            "type": "transcribing_progress",
            "chunk": idx + 1,
            "total": total_chunks,
        })
        oled_menu.show_status("TRANSKRIPTION", f"Chunk {idx + 1}/{total_chunks}", int((idx + 1) / total_chunks * 100))

        result = await loop.run_in_executor(None, run_transcribe, chunk, state.language)

        if result.get("error"):
            await broadcast({"type": "transcription_error", "error": result["error"], "chunk": idx + 1})
            continue

        text = result["text"]
        if text and _is_noise_transcript(text):
            await broadcast({
                "type": "transcription_noise_skipped",
                "text": text,
                "chunk": idx + 1,
            })
            continue

        if text:
            all_texts.append(text)
            total_proc_time += result.get("processing_time", 0)

            await broadcast({
                "type": "transcription_partial",
                "text": text,
                "chunk": idx + 1,
                "total": total_chunks,
            })

    state.transcribing = False

    # Vosk wieder aktiv
    if state.vosk_enabled:
        state.vosk_listening = True

    if not all_texts:
        oled_menu.show_status("FEHLER", "Keine Sprache erkannt")
        await asyncio.sleep(2)
        oled_menu.clear_status()
        await broadcast({"type": "transcription_error", "error": "Keine Sprache erkannt"})
        return {"error": "Keine Sprache erkannt"}

    full_text = " ".join(all_texts)
    rtf = total_proc_time / total_duration if total_duration > 0 else 0

    _now = datetime.now()
    record_entry = {
        "time": _now.strftime("%H:%M:%S"),
        "date": _now.strftime("%d.%m.%Y"),
        "datetime": _now.isoformat(timespec="seconds"),
        "text": full_text,
        "audio_duration": round(total_duration, 2),
        "processing_time": round(total_proc_time, 2),
        "rtf": round(rtf, 3),
    }

    if state.active_session and state.active_session in state.sessions:
        state.sessions[state.active_session]["records"].append(record_entry)

    # Transkript in aktiven Patienten einfügen (Edge case: es gab vor der
    # Aufnahme schon einen aktiven Patienten — z.B. manuelle Voice-Command-Aufnahme)
    if state.active_patient and state.active_patient in state.patients:
        patient = state.patients[state.active_patient]
        patient["transcripts"].append({
            "time": record_entry["time"],
            "text": full_text,
            "speaker": "sanitaeter",
            "role_level": patient["current_role"],
        })

    # Das Transkript wird als neuer Eintrag an die pending-Liste angehängt
    # — NIE überschrieben, jede Aufnahme bleibt unabhängig erhalten bis
    # der User sie analysiert oder verwirft. Jeder Eintrag bekommt eine
    # eindeutige ID damit das Frontend gezielt drauf referenzieren kann.
    import uuid
    pending_entry = {
        "id": uuid.uuid4().hex[:10],
        "full_text": full_text,
        "time": record_entry["time"],
        "date": record_entry["date"],
        "datetime": record_entry["datetime"],
        "duration": round(total_duration, 2),
        "analyzed": False,
        "analyzing": False,
        "created_patient_ids": [],
    }
    state.pending_transcripts.append(pending_entry)

    await broadcast({
        "type": "transcription_result",
        "record": record_entry,
        "session_id": state.active_session,
        "patient_id": state.active_patient,
        "full_text": full_text,
        "pending_analysis": not bool(state.active_patient),
        "pending_entry": pending_entry,
    })

    oled_menu.show_status("TRANSKRIPT OK", f"{len(full_text)} Zeichen")
    await asyncio.sleep(2)
    oled_menu.clear_status()

    return {"status": "ok", "result": record_entry}


async def _segment_and_create_patients(full_text: str, record_time: str) -> list[str]:
    """Ruft Qwen für die Segmentierung auf und legt pro erkanntem Patient
    einen Draft-Record an. Gibt die Liste der erzeugten patient_ids zurück.

    Ablauf:
      1. Segmentierung (Qwen mit SEGMENTATION_PROMPT)
      2. Pro Segment: create_patient_record + 9-Liner-Feld-Extraktion
      3. WebSocket-Broadcast patient_registered pro Patient
      4. Der ZULETZT erzeugte Patient wird active_patient (für RFID-Schreiben etc.)
    """
    loop = asyncio.get_event_loop()
    try:
        segments = await loop.run_in_executor(None, segment_transcript_to_patients, full_text)
    except Exception as e:
        print(f"[SEGMENT] Fehler: {e}", flush=True)
        segments = {"patient_count": 1, "patients": [{"patient_nr": 1, "text": full_text, "summary": ""}]}

    patient_list = segments.get("patients", [])
    if not patient_list:
        patient_list = [{"patient_nr": 1, "text": full_text, "summary": ""}]
    print(f"[SEGMENT] {len(patient_list)} Patient-Segment(e) erkannt", flush=True)

    cfg = load_config()
    device_id = cfg.get("device_id", "jetson-01")
    default_medic = cfg.get("default_medic", "")
    unit_name = cfg.get("unit_name", "")
    created_pids: list[str] = []

    for i, seg in enumerate(patient_list):
        seg_text = (seg.get("text") or "").strip()
        if not seg_text:
            continue

        # Neuen Patient-Record erzeugen
        patient = create_patient_record(
            name="Unbekannt",
            triage="",
            device_id=device_id,
            created_by=default_medic,
        )
        patient["unit"] = unit_name
        pid = patient["patient_id"]
        patient["transcripts"].append({
            "time": record_time,
            "text": seg_text,
            "speaker": "sanitaeter",
            "role_level": patient["current_role"],
        })
        state.patients[pid] = patient
        state.rfid_map[patient["rfid_tag_id"]] = pid
        created_pids.append(pid)

        # 9-Liner-Extraktion im Executor (blockt nicht den Event-Loop)
        try:
            oled_menu.show_status(
                "ANALYSE",
                f"Patient {i + 1}/{len(patient_list)}",
                int((i + 1) / max(1, len(patient_list)) * 80) + 20,
            )
            enrichment = await loop.run_in_executor(None, run_patient_enrichment, seg_text)
            if enrichment:
                if enrichment.get("name"):
                    patient["name"] = enrichment["name"]
                if enrichment.get("rank"):
                    patient["rank"] = enrichment["rank"]
                # Triage wird bewusst NICHT automatisch gesetzt — der
                # Sanitäter vergibt sie manuell. Qwen halluziniert gern
                # eine Triage wenn keine genannt wurde.
                if enrichment.get("injuries"):
                    patient["injuries"] = enrichment["injuries"]
                if enrichment.get("mechanism"):
                    patient["mechanism"] = enrichment["mechanism"]
                vitals = patient.setdefault("vitals", {})
                for src, dst in (("pulse", "pulse"), ("bp", "bp"), ("resp_rate", "resp_rate"), ("spo2", "spo2")):
                    if enrichment.get(src):
                        vitals[dst] = enrichment[src]
                patient["analyzed"] = True
        except Exception as e:
            print(f"[SEGMENT] Enrichment fehlgeschlagen für {pid}: {e}", flush=True)

        await broadcast({"type": "patient_registered", "patient": patient})

    # Letzten Patient aktiv setzen (wichtig für RFID-Schreiben danach)
    if created_pids:
        state.active_patient = created_pids[-1]
        last = state.patients[created_pids[-1]]
        oled_menu.update_active_patient({
            "patient_id": last["patient_id"],
            "name": last.get("name", ""),
            "triage": last.get("triage", ""),
            "flow_status": last.get("flow_status", "registered"),
        })

    return created_pids


@app.post("/api/record/delete")
async def delete_record(body: dict):
    sid = body.get("session_id", state.active_session)
    idx = body.get("index")
    if sid in state.sessions and idx is not None:
        records = state.sessions[sid]["records"]
        if 0 <= idx < len(records):
            records.pop(idx)
            return {"status": "ok"}
    return {"error": "Eintrag nicht gefunden"}


def build_patient_enrichment_prompt(text: str) -> str:
    """Baut den Prompt für die Patienten-Datenanreicherung aus Transkripten.
    Triage wird bewusst NICHT extrahiert — der Sanitäter setzt sie manuell."""
    return f"""Du bist ein militärischer Sanitäts-Assistent. Extrahiere aus dem Transkript alle Patientendaten als JSON.

Felder:
- name: Name des Patienten (Nachname oder voller Name)
- rank: Dienstgrad (z.B. Feldwebel, Oberstabsgefreiter, Hauptmann)
- injuries: Liste der Verletzungen (als Array von Strings)
- mechanism: Verletzungsmechanismus (z.B. Schussverletzung, IED, Splitter)
- pulse: Puls (nur Zahl)
- bp: Blutdruck (z.B. "120/80")
- resp_rate: Atemfrequenz (nur Zahl)
- spo2: Sauerstoffsättigung (nur Zahl)
- treatments: Durchgeführte Maßnahmen (Array von Strings)
- medications: Verabreichte Medikamente (Array von Strings)
- unit: Einheit des Patienten
- blood_type: Blutgruppe

Regeln:
- Nur Informationen aus dem Text verwenden
- Felder ohne Info: leerer String oder leeres Array
- Kurze, präzise Werte
- NICHT ERFINDEN: keine Triage-Kategorie, kein Alter, keine Namen die nicht im Text stehen

Text: {text}

JSON:"""


def run_patient_enrichment(text: str) -> dict:
    """Extrahiert Patientendaten aus Transkript-Text via Ollama LLM."""
    prompt = build_patient_enrichment_prompt(text)
    return _call_ollama(prompt, "Patienten-Anreicherung")


async def _run_analysis_background(sid: str):
    """Einzelanalyse mit GPU-Swap: Whisper stoppen → Ollama GPU → Whisper neu starten."""
    loop = asyncio.get_event_loop()
    try:
        # GPU-Swap: Whisper stoppen für Ollama
        print("GPU-Swap (Einzel): Whisper wird gestoppt...")
        await loop.run_in_executor(None, stop_whisper_server)
        await asyncio.sleep(1)

        result = await _run_analysis_for_session(sid)
        pid = state.sessions[sid].get("patient_id", state.active_patient)
        if pid and pid in state.patients:
            state.patients[pid]["analyzed"] = True
            await broadcast({"type": "patient_update", "patient": state.patients[pid]})
        tts.speak("Analyse abgeschlossen")
    except Exception as e:
        print(f"Background-Analyse Fehler: {e}")
        await broadcast({"type": "analysis_error", "error": str(e)})
    finally:
        state._analyzing = False

        # GPU-Swap: Ollama entladen, Whisper neu starten
        print("GPU-Swap (Einzel): Ollama entladen...")
        await loop.run_in_executor(None, _unload_ollama_model)
        await asyncio.sleep(1)

        print("GPU-Swap (Einzel): Whisper wird neu gestartet...")
        if state.model_path and state.model_path.exists():
            success = await loop.run_in_executor(None, start_whisper_server, state.model_path)
            if success:
                print(f"GPU-Swap (Einzel): Whisper bereit ({state.current_model})")
                await broadcast({"type": "model_loaded", "model": state.current_model, "ram_mb": state.model_ram_mb})
            else:
                print("WARNUNG: Whisper konnte nach Einzelanalyse nicht neu gestartet werden!")


async def _run_analysis_for_session(sid: str) -> dict:
    """Kern-Logik: KI analysiert Transkripte und reichert Patientendaten an."""
    session = state.sessions[sid]
    template_id = session.get("template_id", "freitext")
    full_text = " ".join(r["text"] for r in session["records"])

    loop = asyncio.get_event_loop()

    # 1. Template-Felder extrahieren (wenn nicht Freitext)
    extracted = {}
    if template_id != "freitext":
        extracted = await loop.run_in_executor(None, run_llm_extraction, template_id, full_text)
        if extracted:
            session["template_data"].update(extracted)

    # 2. Patientendaten anreichern (immer, auch bei Freitext)
    enriched = await loop.run_in_executor(None, run_patient_enrichment, full_text)

    # Patientendaten aktualisieren (nur nicht-leere Felder überschreiben)
    pid = session.get("patient_id") or state.active_patient
    if enriched and pid and pid in state.patients:
        patient = state.patients[pid]
        # Einfache String-Felder: nur überschreiben wenn aktuell leer oder "Unbekannt"
        for key in ["name", "rank", "triage", "unit", "blood_type"]:
            val = enriched.get(key, "")
            if val and (not patient.get(key) or patient.get(key) == "Unbekannt"):
                patient[key] = val
        # Array-Felder: anhängen
        for key in ["injuries", "treatments", "medications"]:
            vals = enriched.get(key, [])
            if isinstance(vals, list) and vals:
                existing = patient.get(key, [])
                for v in vals:
                    if v and v not in existing:
                        existing.append(v)
                patient[key] = existing
        # Vitals: nur überschreiben wenn aktuell leer
        vitals_map = {"pulse": "pulse", "bp": "bp", "resp_rate": "resp_rate", "spo2": "spo2"}
        for src, dst in vitals_map.items():
            val = enriched.get(src, "")
            if val and not patient["vitals"].get(dst):
                patient["vitals"][dst] = str(val)
        # Verletzungsmechanismus in Template-Daten
        if enriched.get("mechanism"):
            session["template_data"]["mechanism"] = enriched["mechanism"]

        # Patient nach Anreicherung als nicht-synchronisiert markieren
        patient["synced"] = False

        patient["timeline"].append({
            "time": datetime.now().isoformat(),
            "role": patient["current_role"],
            "event": "ki_analysis",
            "details": f"KI-Analyse: {len([v for v in enriched.values() if v])} Felder extrahiert",
        })
        await broadcast({"type": "patient_update", "patient": patient})

    fields_count = len([v for v in extracted.values() if v]) + len([v for v in enriched.values() if v])
    await broadcast({
        "type": "analysis_complete",
        "session_id": sid,
        "data": extracted,
        "enriched": enriched,
        "fields_count": fields_count,
    })
    return {"extracted": extracted, "enriched": enriched, "fields_count": fields_count}


@app.post("/api/session/analyze")
async def analyze_session(body: dict = None):
    """KI analysiert Transkripte — läuft non-blocking im Hintergrund."""
    if getattr(state, '_analyzing', False):
        return {"error": "Analyse läuft bereits"}
    sid = body.get("session_id", state.active_session) if body else state.active_session
    if not sid or sid not in state.sessions:
        return {"error": "Keine aktive Session"}
    if not state.sessions[sid]["records"]:
        return {"error": "Keine Transkripte vorhanden"}

    state._analyzing = True
    await broadcast({"type": "analyzing", "session_id": sid})
    asyncio.create_task(_run_analysis_background(sid))
    return {"status": "ok", "message": "Analyse gestartet"}


@app.post("/api/patients/analyze")
async def analyze_all_patients():
    """Alle nicht-analysierten Patienten per KI analysieren."""
    if getattr(state, '_analyzing', False):
        return {"error": "Analyse läuft bereits"}
    pending = [(pid, p) for pid, p in state.patients.items() if not p.get("analyzed")]
    if not pending:
        return {"status": "ok", "message": "Alle Patienten bereits analysiert", "analyzed": 0}

    state._analyzing = True
    await broadcast({"type": "analyzing_batch", "count": len(pending)})
    asyncio.create_task(_run_batch_analysis(pending))
    return {"status": "ok", "message": f"{len(pending)} Patienten werden analysiert"}


@app.post("/api/export/docx")
async def export_docx(body: dict = None):
    sid = body.get("session_id", state.active_session) if body else state.active_session
    if not sid or sid not in state.sessions:
        return {"error": "Keine aktive Session"}

    session = state.sessions[sid]
    if not session["records"] and not session.get("template_data"):
        return {"error": "Keine Einträge vorhanden"}

    filepath = generate_docx(session)
    return FileResponse(
        str(filepath),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filepath.name,
    )


@app.get("/api/files")
async def list_files():
    files = []
    for f in sorted(PROTOCOLS_DIR.glob("*")):
        files.append({
            "name": f.name,
            "size_kb": round(f.stat().st_size / 1024, 1),
            "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        })
    return {"files": files}


@app.get("/api/files/download/{filename}")
async def download_file(filename: str):
    filepath = PROTOCOLS_DIR / filename
    if not filepath.exists() or not filepath.is_relative_to(PROTOCOLS_DIR):
        return {"error": "Datei nicht gefunden"}
    return FileResponse(str(filepath), filename=filename)


@app.delete("/api/files/{filename}")
async def delete_file(filename: str):
    filepath = PROTOCOLS_DIR / filename
    if filepath.exists() and filepath.is_relative_to(PROTOCOLS_DIR):
        filepath.unlink()
        return {"status": "ok"}
    return {"error": "Datei nicht gefunden"}


# Vosk Toggle
@app.post("/api/vosk/toggle")
async def toggle_vosk(body: dict = None):
    if not state.vosk_model:
        return {"error": "Vosk nicht verfuegbar"}
    enable = body.get("enabled", not state.vosk_enabled) if body else not state.vosk_enabled
    state.vosk_enabled = enable
    if enable and not state.persistent_stream:
        start_persistent_stream()
    if enable:
        state.vosk_listening = not state.recording
    else:
        state.vosk_listening = False
        if state.persistent_stream and not state.recording:
            stop_persistent_stream()
    await broadcast({"type": "vosk_status", "enabled": state.vosk_enabled, "listening": state.vosk_listening})
    return {"status": "ok", "enabled": state.vosk_enabled}


@app.post("/api/tts/speak")
async def tts_speak(body: dict):
    """Spricht einen Text per Piper TTS aus."""
    text = body.get("text", "")
    if text:
        tts.speak(text)
    return {"status": "ok"}


@app.post("/api/tts/toggle")
async def tts_toggle(body: dict = None):
    """TTS ein/ausschalten."""
    enabled = body.get("enabled", not tts.is_enabled()) if body else not tts.is_enabled()
    tts.set_enabled(enabled)
    return {"status": "ok", "enabled": tts.is_enabled()}


@app.get("/api/tts/status")
async def tts_status():
    return {"enabled": tts.is_enabled()}


@app.post("/api/mic/test")
async def mic_test(body: dict = None):
    """Startet/Stoppt einen Mikrofon-Test mit eigenem Stream."""
    action = body.get("action", "start") if body else "start"
    if action == "start":
        state._mic_test = True
        state._mic_test_chunks = []
        # Eigenen Test-Stream starten falls kein persistenter läuft
        if not state.persistent_stream and not state.stream:
            try:
                # Native Samplerate des Geräts ermitteln
                dev_info = sd.query_devices(state.audio_device or sd.default.device[0], 'input')
                native_rate = int(dev_info['default_samplerate'])
                state._mic_test_stream = sd.InputStream(
                    samplerate=native_rate, channels=1, dtype="float32",
                    blocksize=int(native_rate * 0.1),
                    device=state.audio_device,
                    callback=lambda indata, frames, t, status: state._mic_test_chunks.append(indata.copy()),
                )
                state._mic_test_stream.start()
            except Exception as e:
                return {"status": "error", "error": str(e)}
        return {"status": "ok", "action": "started", "device": state.audio_device}
    else:
        state._mic_test = False
        if hasattr(state, '_mic_test_stream') and state._mic_test_stream:
            try:
                state._mic_test_stream.stop()
                state._mic_test_stream.close()
            except Exception:
                pass
            state._mic_test_stream = None
        return {"status": "ok", "action": "stopped"}


@app.get("/api/mic/level")
async def mic_level():
    """Gibt aktuellen Mikrofon-Pegel zurück (RMS + Peak)."""
    # Daten aus Test-Stream oder persistentem Stream lesen
    chunks = None
    if hasattr(state, '_mic_test_chunks') and state._mic_test_chunks:
        chunks = state._mic_test_chunks
    elif state.audio_chunks:
        chunks = state.audio_chunks

    if not chunks:
        has_stream = bool(state.persistent_stream or state.stream or (hasattr(state, '_mic_test_stream') and state._mic_test_stream))
        if not has_stream:
            return {"rms": 0, "peak": 0, "db": -60, "error": "Kein Audio-Stream aktiv. Vosk aktivieren oder Mic-Test starten."}
        return {"rms": 0, "peak": 0, "db": -60, "error": "Stream aktiv, aber keine Daten"}

    try:
        chunk = chunks[-1]
        rms = float(np.sqrt(np.mean(chunk ** 2)))
        peak = float(np.max(np.abs(chunk)))
        db = 20 * np.log10(rms + 1e-10)
        return {"rms": round(rms, 6), "peak": round(peak, 6), "db": round(db, 1)}
    except Exception as e:
        return {"rms": 0, "peak": 0, "db": -60, "error": str(e)}


@app.get("/api/oled/image")
async def oled_image():
    """Liefert das aktuelle OLED-Bild als base64-PNG + Menü-Meta für das
    Dashboard-Preview. Das Frontend pollt diesen Endpoint alle ~300 ms."""
    try:
        img_b64 = oled_menu.render_base64()
        from jetson.oled import PAGES, PAGE_SUBMENUS, PAGE_TITLES
        page = PAGES[oled_menu.current_page] if PAGES else ""
        return {
            "image": img_b64,
            "page": page,
            "page_title": PAGE_TITLES.get(page, page),
            "submenu_open": oled_menu.submenu_open,
            "submenu_index": oled_menu.submenu_index,
            "submenu_items": [lbl for _, lbl in PAGE_SUBMENUS.get(page, [])],
            "status_mode": oled_menu._status_mode,
        }
    except Exception as e:
        return {"image": None, "error": str(e)}


@app.get("/api/hw/state")
async def hw_state():
    """Diagnose-Snapshot der Taster-Hardware. Zeigt rohe GPIO-Werte UND
    die debounced press-States — so sehen wir sofort ob ein Pin stuck-LOW
    ist (rohes LOW obwohl niemand drückt). Zusätzlich: combo-active Flag
    und seit wann die Taster gedrückt sind."""
    bd = getattr(hardware_service, "_buttons", None)
    if bd is None:
        return {"error": "ButtonDriver nicht initialisiert"}
    try:
        a_raw_low = bd._gpio.input(bd._pin_a) == bd._gpio.LOW
        b_raw_low = bd._gpio.input(bd._pin_b) == bd._gpio.LOW
    except Exception as e:
        return {"error": f"GPIO read failed: {e}"}
    import time as _t
    now = _t.monotonic()
    return {
        "pin_a": bd._pin_a,
        "pin_b": bd._pin_b,
        "a_raw_pressed": a_raw_low,
        "b_raw_pressed": b_raw_low,
        "a_debounced_pressed": bd._state_a["pressed"],
        "b_debounced_pressed": bd._state_b["pressed"],
        "a_held_s": (now - bd._state_a["since"]) if bd._state_a["pressed"] else 0.0,
        "b_held_s": (now - bd._state_b["since"]) if bd._state_b["pressed"] else 0.0,
        "combo_active": bd._combo_active,
        "combo_latched": bd._combo_latched,
        "long_press_s": bd._long_press,
        "combo_s": bd._combo,
    }


@app.post("/api/hw/button")
async def hw_button(body: dict):
    """Virtueller Button-Druck aus dem Dashboard.
    Body: {"button": "A"|"B", "kind": "short"|"long"}.
    Das Event geht durch dieselbe Routing-Funktion wie echte GPIO-Taster,
    inklusive Wake-Gate, Submenu-Logik und App-Callbacks."""
    from jetson.hardware import ButtonEvent
    btn = str(body.get("button", "")).upper()
    kind = str(body.get("kind", "short")).lower()
    if btn not in ("A", "B") or kind not in ("short", "long"):
        return {"status": "error", "error": "button must be A/B, kind short/long"}
    hold = 2.0 if kind == "long" else 0.1
    event = ButtonEvent(kind=kind, button=btn, hold_seconds=hold)
    try:
        hardware_service._handle_button_event(event)
    except Exception as e:
        return {"status": "error", "error": str(e)}
    return {"status": "ok", "button": btn, "kind": kind}


@app.get("/api/vosk/status")
async def vosk_status():
    return {
        "enabled": state.vosk_enabled,
        "listening": state.vosk_listening,
        "available": state.vosk_model is not None,
    }


# ---------------------------------------------------------------------------
# Konfiguration API
# ---------------------------------------------------------------------------
@app.get("/api/config")
async def get_config():
    """Gibt die aktuelle Konfiguration zurück."""
    return load_config()


@app.post("/api/config")
async def update_config(body: dict):
    """Aktualisiert die Konfiguration und laedt Sprachbefehle neu."""
    global VOICE_COMMANDS, OLLAMA_URL, OLLAMA_MODEL
    cfg = load_config()
    # Deep-merge: top-level keys ersetzen
    for key, value in body.items():
        if isinstance(value, dict) and isinstance(cfg.get(key), dict):
            cfg[key].update(value)
        else:
            cfg[key] = value
    save_config(cfg)
    # Sprachbefehle neu laden
    VOICE_COMMANDS = build_voice_commands(cfg)
    # Ollama Config neu laden
    OLLAMA_URL = cfg.get("ollama", {}).get("url", OLLAMA_URL)
    OLLAMA_MODEL = cfg.get("ollama", {}).get("model", OLLAMA_MODEL)
    return {"status": "ok"}


@app.get("/api/config/voice-commands")
async def get_voice_commands():
    """Gibt die konfigurierten Sprachbefehle zurück."""
    cfg = load_config()
    return cfg.get("voice_commands", {})


@app.post("/api/config/voice-commands")
async def update_voice_commands(body: dict):
    """Aktualisiert die Sprachbefehle und speichert in config.json."""
    global VOICE_COMMANDS
    cfg = load_config()
    cfg["voice_commands"] = body
    save_config(cfg)
    VOICE_COMMANDS = build_voice_commands(cfg)
    return {"status": "ok", "commands": len(VOICE_COMMANDS)}


@app.get("/api/config/navigation")
async def get_navigation():
    """Gibt die Navigationsstruktur zurück."""
    cfg = load_config()
    return {"navigation": cfg.get("navigation", [])}


@app.post("/api/config/navigation")
async def update_navigation(body: dict):
    """Aktualisiert die Navigationsstruktur."""
    cfg = load_config()
    cfg["navigation"] = body.get("navigation", cfg.get("navigation", []))
    save_config(cfg)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# WebSocket for real-time updates
# ---------------------------------------------------------------------------
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    state.ws_clients.append(ws)

    await ws.send_json({
        "type": "init",
        "model": state.current_model,
        "model_loaded": state.model_loaded,
        "model_ram_mb": state.model_ram_mb,
        "recording": state.recording,
        "active_session": state.active_session,
        "session_data": state.sessions.get(state.active_session) if state.active_session else None,
        "vosk_enabled": state.vosk_enabled,
        "vosk_listening": state.vosk_listening,
        "active_patient": state.active_patient,
        "patients": list(state.patients.values()),
        "backend_reachable": state.backend_reachable,
    })

    try:
        while True:
            try:
                loop = asyncio.get_event_loop()
                stats = await loop.run_in_executor(None, get_system_stats)
                stats["model_loaded"] = state.model_loaded
                stats["model_ram_mb"] = state.model_ram_mb
                await ws.send_json({"type": "system_stats", "stats": stats})
            except Exception as e:
                print(f"WS stats error: {e}")

            try:
                if state.recording and state.audio_chunks:
                    last_chunk = state.audio_chunks[-1]
                    rms = float(np.sqrt(np.mean(last_chunk ** 2)))
                    duration = len(state.audio_chunks) * 0.1
                    await ws.send_json({
                        "type": "audio_level",
                        "rms": round(rms, 4),
                        "duration": round(duration, 1),
                    })
            except Exception:
                pass

            try:
                msg = await asyncio.wait_for(ws.receive_text(), timeout=2.0)
                data = json.loads(msg)
                if data.get("type") == "ping":
                    await ws.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                pass
            except WebSocketDisconnect:
                break
            except Exception:
                break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WS error: {e}")
    finally:
        if ws in state.ws_clients:
            state.ws_clients.remove(ws)


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# GPS-Simulation (Demo: BAT fährt zur Rettungsstation)
# ---------------------------------------------------------------------------
# Route: Startpunkt südlich von Bonn → Rettungsstation Bonn Zentrum
GPS_ROUTE = [
    (50.6900, 7.0700),  # Startpunkt (Feld/POI)
    (50.6950, 7.0750),
    (50.7000, 7.0780),
    (50.7050, 7.0820),
    (50.7100, 7.0850),
    (50.7150, 7.0880),
    (50.7200, 7.0900),
    (50.7250, 7.0920),
    (50.7300, 7.0950),
    (50.7350, 7.0980),  # Rettungsstation (Ziel)
]
_gps_index = 0
_gps_active = False


async def gps_simulation_loop():
    """Sendet periodisch GPS-Positionen an das Backend (alle 10 Sekunden)."""
    global _gps_index, _gps_active
    while True:
        await asyncio.sleep(10)
        if not _gps_active:
            continue
        cfg = load_config()
        backend_url = cfg.get("backend", {}).get("url", "")
        unit_name = cfg.get("unit_name", "BAT Alpha")
        device_id = cfg.get("device_id", "jetson-01")

        if not backend_url or _gps_index >= len(GPS_ROUTE):
            continue

        lat, lon = GPS_ROUTE[_gps_index]
        try:
            httpx.post(f"{backend_url}/api/position", json={
                "unit_name": unit_name,
                "device_id": device_id,
                "lat": lat,
                "lon": lon,
                "heading": 0,
                "speed_kmh": 40,
            }, timeout=5)
            _gps_index += 1
            if _gps_index >= len(GPS_ROUTE):
                _gps_index = 0  # Loop für Demo
                _gps_active = False
        except Exception:
            pass


@app.post("/api/gps/start")
async def start_gps_sim():
    """Startet die GPS-Simulation."""
    global _gps_active, _gps_index
    _gps_active = True
    _gps_index = 0
    return {"status": "ok", "message": "GPS-Simulation gestartet"}


@app.post("/api/gps/stop")
async def stop_gps_sim():
    """Stoppt die GPS-Simulation."""
    global _gps_active
    _gps_active = False
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Startup / Shutdown
# ---------------------------------------------------------------------------
def _play_sound_async(filename: str) -> None:
    """Spielt eine WAV-Datei aus sounds/ über aplay auf dem USB-Dongle ab.
    Fire-and-forget: blockiert weder den Event-Loop noch Konflikte mit dem
    bestehenden sounddevice-Stream (aplay = separater Prozess, parallel zum
    Python-Capture-Stream)."""
    try:
        import subprocess
        path = PROJECT_DIR / "sounds" / filename
        if not path.exists():
            print(f"[SOUND] fehlt: {path}", flush=True)
            return
        subprocess.Popen(
            ["aplay", "-q", "-D", "plughw:0,0", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        print(f"[SOUND] Fehler bei {filename}: {e}", flush=True)


@app.on_event("startup")
async def startup():
    state.event_loop = asyncio.get_event_loop()

    # OLED Display initialisieren
    oled_menu.init_hardware()
    oled_menu.show_status("SAFIR", "System startet...", 0)

    # Vosk initialisieren
    oled_menu.show_status("SAFIR", "Vosk laden...", 10)
    init_vosk()

    # Whisper-Modell laden
    models = state.available_models()
    if models:
        best = next((m for m in models if m["name"] == "small"), models[0])
        path = MODELS_DIR / f"ggml-{best['name']}.bin"
        print(f"Lade Modell: {best['name']} ({best['size_mb']} MB)...")
        oled_menu.show_status("SAFIR", f"Whisper {best['name']}...", 30)
        success = start_whisper_server(path)
        if success:
            state.model_path = path
            state.current_model = best["name"]
            print(f"Modell bereit: {best['name']} (~{state.model_ram_mb} MB RAM)")
            oled_menu.show_status("SAFIR", "Whisper geladen", 60)
        else:
            print("WARNUNG: Modell konnte nicht geladen werden!")
            oled_menu.show_status("FEHLER", "Whisper fehlgeschlagen")

    # Audio-Device automatisch erkennen: bevorzugt USB-Mikrofon
    oled_menu.show_status("SAFIR", "Audio suchen...", 70)
    devices = state.audio_devices()
    usb_device = next((d for d in devices if "USB" in d["name"] or "Logitech" in d["name"]), None)
    if usb_device:
        state.audio_device = usb_device["id"]
        print(f"Audio-Device: [{usb_device['id']}] {usb_device['name']} ({usb_device['samplerate']}Hz)")
    else:
        print("Kein USB-Mikrofon gefunden, verwende Default")

    # Persistenten Audio-Stream starten (für Vosk)
    if state.vosk_enabled:
        start_persistent_stream()

    # Vosk Command-Processor starten
    asyncio.create_task(process_vosk_commands())

    # Piper TTS laden
    oled_menu.show_status("SAFIR", "TTS laden...", 85)
    tts.init_tts()

    # GPS-Simulation starten (für Demo)
    asyncio.create_task(gps_simulation_loop())

    # Peer Discovery Heartbeat
    asyncio.create_task(_heartbeat_loop())

    # Backend-WebSocket-Client: persistente bidirektionale Verbindung zur
    # Leitstelle. Pusht Änderungen live an das Jetson-Dashboard ohne F5.
    state.backend_ws_task = asyncio.create_task(_backend_ws_loop())

    # SAFIR bereit!
    oled_menu.show_status("SAFIR BEREIT", "Warte auf Befehl...")
    _play_sound_async("safir-ready.wav")
    await asyncio.sleep(3)
    oled_menu.clear_status()

    # Hardware-Service: Taster, LEDs, Shutdown-Geste starten
    hardware_service.set_rfid_callback(_handle_rfid_scan)
    hardware_service.set_oled_action_callback(_handle_oled_action)
    await hardware_service.start()

    # Starte OLED-Update-Loop für Menü-Seiten
    asyncio.create_task(_oled_update_loop())


async def _oled_update_loop():
    """Aktualisiert das OLED-Menü alle ~500 ms mit Systemdaten.

    Kürzerer Intervall weil der Shutdown-Countdown bei 3 s Gesamtdauer
    mehrmals gerendert werden muss. Normale Seiten-Daten werden aber nur
    alle 2 s neu erfasst (Rate-Limiting über _last_stats_refresh).
    """
    import psutil
    import socket
    print("[OLED] _oled_update_loop gestartet", flush=True)
    last_stats_refresh = 0.0
    last_debug_print = 0.0
    STATS_INTERVAL = 2.0

    while True:
        # Burn-in Schutz: nach 5 Min Inaktivität Display ausschalten
        oled_menu.check_screensaver()

        # Shutdown-Countdown hat Vorrang — rendert sich selbst via show_status()
        if hardware_service.render_shutdown_countdown_if_active():
            await asyncio.sleep(0.1)
            continue

        # Diagnose: alle 5 s den aktuellen Zustand loggen
        _dbg_now = time.monotonic()
        if _dbg_now - last_debug_print > 5.0:
            last_debug_print = _dbg_now
            print(f"[OLED] tick status_mode={oled_menu._status_mode} display_off={oled_menu._display_off} page={oled_menu.current_page}", flush=True)

        if not oled_menu._status_mode and not oled_menu._display_off:
            now = time.monotonic()
            try:
                # Stats nur alle 2 s erneuern (teuer)
                if now - last_stats_refresh >= STATS_INTERVAL:
                    last_stats_refresh = now
                    mem = psutil.virtual_memory()
                    disk = psutil.disk_usage("/")
                    oled_menu.update_stats({
                        "cpu_percent": psutil.cpu_percent(),
                        "ram_percent": mem.percent,
                        "ram_used_mb": mem.used // (1024 * 1024),
                        "ram_total_mb": mem.total // (1024 * 1024),
                        "gpu_usage": "N/A",
                        "disk_percent": disk.percent,
                        "unit_name": _config.get("unit_name", ""),
                        "patient_count": len(state.patients),
                    })
                    # Netzwerk-Info
                    try:
                        hostname = socket.gethostname()
                    except Exception:
                        hostname = "jetson"
                    ip = _get_primary_ip()
                    oled_menu.update_network({
                        "hostname": hostname,
                        "ip": ip,
                        "tailscale_ip": _get_tailscale_ip(),
                        "peers": len(state.peers),
                    })
                    # Operator-Info
                    op = getattr(state, "current_operator", None)
                    if op:
                        oled_menu.update_operator({
                            "logged_in": True,
                            "label": op.get("label", "?"),
                            "name": op.get("name", ""),
                            "role": op.get("role", ""),
                            "since": op.get("since", ""),
                        })
                    else:
                        oled_menu.update_operator({"logged_in": False})

                    # KI-Modelle-Status: SAFIR ist einsatzbereit wenn beide
                    # Modelle verfügbar sind. Qwen wird wegen GPU-Swap nur
                    # während der Analyse in den VRAM geladen — wir prüfen
                    # deshalb ob das Modell bei Ollama registriert ist
                    # (`/api/tags`), nicht ob es gerade im VRAM liegt.
                    whisper_ok = bool(state.model_loaded)
                    qwen_ok = False
                    try:
                        _tags = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=1.5)
                        if _tags.status_code == 200:
                            want = OLLAMA_MODEL.split(":")[0]
                            for _m in _tags.json().get("models", []):
                                if want in _m.get("name", ""):
                                    qwen_ok = True
                                    break
                    except Exception:
                        qwen_ok = False
                    oled_menu.update_models_status({
                        "whisper_ok": whisper_ok,
                        "qwen_ok": qwen_ok,
                    })

                    # Aktiver Patient für PATIENT-Seite
                    active_pat = None
                    if state.active_patient and state.active_patient in state.patients:
                        active_pat = state.patients[state.active_patient]
                    if active_pat:
                        oled_menu.update_active_patient({
                            "patient_id": active_pat.get("patient_id", ""),
                            "name": active_pat.get("name", ""),
                            "triage": active_pat.get("triage", ""),
                            "flow_status": active_pat.get("flow_status", ""),
                        })
                    else:
                        oled_menu.update_active_patient({})

                    # Power-Info (Uptime)
                    uptime_s = time.monotonic() - _hardware_start_ts
                    oled_menu.update_power({
                        "uptime_hours": uptime_s / 3600.0,
                        "current_watts": 0,  # TODO: tegrastats-Parsing
                    })
                    # Cardwrite-Info (für die KARTE-SCHREIBEN-Seite)
                    active_p = None
                    if state.active_patient and state.active_patient in state.patients:
                        active_p = state.patients[state.active_patient]
                    cw_op_ok = op is not None
                    cw_perm_ok = cw_op_ok and _role_has_permission(
                        op.get("role", ""), "rfid_write_patient"
                    )
                    oled_menu.update_cardwrite({
                        "operator_logged_in": cw_op_ok,
                        "has_permission": cw_perm_ok,
                        "has_active_patient": active_p is not None,
                        "patient_name": (active_p or {}).get("name", ""),
                        "patient_id": (active_p or {}).get("patient_id", ""),
                        "triage": (active_p or {}).get("triage", ""),
                    })

                    # Hardware-Info
                    from shared import rfid as _rfid
                    hw_uptime = time.monotonic() - _hardware_start_ts
                    btn_counts = hardware_service.get_button_counts()
                    oled_menu.update_hardware({
                        "rfid_available": _rfid.is_rc522_available(),
                        "last_uid": getattr(state, "last_rfid_uid", "---"),
                        "button_a_count": btn_counts["A_short"] + btn_counts["A_long"],
                        "button_b_count": btn_counts["B_short"] + btn_counts["B_long"],
                        "system_state": hardware_service.get_system_state().value,
                        "uptime_s": hw_uptime,
                    })
                oled_menu.render()
            except Exception as e:
                print(f"OLED update error: {e}")
        await asyncio.sleep(0.5)


def _get_primary_ip() -> str:
    """Ermittelt die primäre IP-Adresse des Jetson (ohne 127.0.0.1)."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "---"


def _get_tailscale_ip() -> str:
    """Liest die Tailscale-IP aus der tailscale CLI, falls verfügbar."""
    try:
        out = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True, text=True, timeout=1.0,
        )
        ip = out.stdout.strip().split("\n")[0]
        return ip or "---"
    except Exception:
        return "---"


# Startzeit für Hardware-Service-Uptime
_hardware_start_ts = time.monotonic()


@app.on_event("shutdown")
async def shutdown():
    oled_menu.show_status("SAFIR", "Herunterfahren...")
    try:
        await hardware_service.stop()
    except Exception as e:
        print(f"Hardware-Service stop error: {e}")
    stop_persistent_stream()
    stop_whisper_server()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
