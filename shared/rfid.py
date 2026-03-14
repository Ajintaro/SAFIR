"""
SAFIR — RFID-Simulation für Patientenregistrierung.
Für die Demo: Keyboard-Eingabe simuliert RFID-Scan.
Später austauschbar gegen echten RC522 SPI-Reader.
"""

import uuid
from datetime import datetime


def generate_patient_id() -> str:
    """Generiert eine eindeutige Patienten-ID (UUID-basiert, kurz)."""
    return f"PAT-{uuid.uuid4().hex[:8].upper()}"


def generate_rfid_tag() -> str:
    """Generiert eine simulierte RFID-Tag-ID."""
    return f"RFID-{uuid.uuid4().hex[:12].upper()}"


def lookup_by_rfid(rfid_map: dict, tag_id: str) -> str | None:
    """Sucht Patient-ID anhand der RFID-Tag-ID."""
    return rfid_map.get(tag_id)


def create_patient_record(
    name: str,
    triage: str = "",
    rfid_tag_id: str = "",
    device_id: str = "jetson-01",
    created_by: str = "",
) -> dict:
    """Erstellt einen neuen Patientendatensatz mit Grunddaten."""
    from shared.models import PATIENT_SCHEMA
    import copy

    patient = copy.deepcopy(PATIENT_SCHEMA)
    patient["patient_id"] = generate_patient_id()
    patient["timestamp_created"] = datetime.now().isoformat()
    patient["name"] = name
    patient["triage"] = triage
    patient["rfid_tag_id"] = rfid_tag_id or generate_rfid_tag()
    patient["device_id"] = device_id
    patient["created_by"] = created_by
    patient["flow_status"] = "registered"
    patient["current_role"] = "phase0"

    # Initiales Timeline-Event
    patient["timeline"].append({
        "time": datetime.now().isoformat(),
        "role": "phase0",
        "event": "registered",
        "details": f"Patient registriert von {created_by or 'Unbekannt'} ({device_id})",
    })

    return patient
