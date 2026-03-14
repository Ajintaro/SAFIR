"""
SAFIR — Gemeinsame Datenmodelle für Jetson und Backend.
Definiert die Strukturen, die zwischen den Geräten ausgetauscht werden.
"""

from datetime import datetime
from enum import Enum
from typing import Optional


# --- Rettungskette Stufen ---

class RoleLevel(str, Enum):
    PHASE0 = "phase0"   # Selbst-/Kameradenhilfe
    ROLE1 = "role1"      # Rettungsstation
    ROLE2 = "role2"      # Rettungszentrum
    ROLE3 = "role3"      # Einsatzlazarett
    ROLE4 = "role4"      # BW-Krankenhaus


class TriagePriority(str, Enum):
    T1 = "T1"  # Sofortbehandlung
    T2 = "T2"  # Dringend
    T3 = "T3"  # Aufschiebbar
    T4 = "T4"  # Abwartend/Erwartungsvoll


class PatientStatus(str, Enum):
    STABLE = "stable"
    CRITICAL = "critical"
    URGENT = "urgent"
    DECEASED = "deceased"


class PatientFlowStatus(str, Enum):
    REGISTERED = "registered"       # Ersterfassung am POI
    INBOUND = "inbound"             # Transport gemeldet
    ARRIVED = "arrived"             # Eingetroffen an nächster Stufe
    IN_TREATMENT = "in_treatment"   # In Behandlung
    STABILIZED = "stabilized"       # Stabilisiert
    OUTBOUND = "outbound"           # Transport zur nächsten Stufe
    TRANSFERRED = "transferred"     # Übergeben / verlegt


# Flow-Status Labels (deutsch)
FLOW_STATUS_LABELS = {
    "registered": "Registriert",
    "inbound": "Transport",
    "arrived": "Eingetroffen",
    "in_treatment": "In Behandlung",
    "stabilized": "Stabilisiert",
    "outbound": "Verlegung",
    "transferred": "Verlegt",
}

# Triage-Farben
TRIAGE_COLORS = {
    "T1": "#FF0000",  # Rot — Sofort
    "T2": "#FF8800",  # Orange — Dringend
    "T3": "#00AA00",  # Grün — Aufschiebbar
    "T4": "#4444AA",  # Blau — Abwartend
}


# --- Patienten-Datensatz (fließt durch die gesamte Kette) ---

PATIENT_SCHEMA = {
    "patient_id": "",           # Eindeutige ID
    "timestamp_created": "",    # Ersterfassung
    "current_role": "phase0",   # Aktuelle Stufe in der Rettungskette
    "flow_status": "registered",  # PatientFlowStatus
    "synced": False,            # True wenn erfolgreich an Leitstelle übermittelt
    "analyzed": False,          # True wenn KI-Analyse durchgeführt
    "rfid_tag_id": "",          # RFID-Tag Kennung
    "device_id": "",            # Erfassendes Gerät (z.B. "jetson-01")
    "created_by": "",           # Erfassender Sanitäter

    # Stammdaten
    "name": "",
    "rank": "",                 # Dienstgrad
    "unit": "",                 # Einheit
    "nationality": "",
    "dob": "",
    "blood_type": "",
    "allergies": "",

    # 9-Liner MEDEVAC (Phase 0 / Role 1)
    "nine_liner": {
        "line1": "",  # Koordinaten Landezone
        "line2": "",  # Funkfrequenz / Rufzeichen
        "line3": "",  # Patienten nach Dringlichkeit
        "line4": "",  # Sonderausstattung
        "line5": "",  # Patienten Liegend/Gehfähig
        "line6": "",  # Sicherheitslage
        "line7": "",  # Markierung Landeplatz
        "line8": "",  # Nationalität / Status
        "line9": "",  # ABC / Gelände
    },

    # Medizinische Daten
    "triage": "",               # T1-T4
    "status": "stable",
    "injuries": [],             # Liste der Verletzungen
    "vitals": {
        "pulse": "",
        "bp": "",
        "resp_rate": "",
        "spo2": "",
        "temp": "",
        "gcs": "",              # Glasgow Coma Scale
    },
    "treatments": [],           # Durchgeführte Maßnahmen
    "medications": [],          # Verabreichte Medikamente

    # Transkripte und Audio
    "transcripts": [],          # [{time, text, speaker, role_level}]
    "audio_files": [],          # Referenzen auf Audiodateien

    # Übergaben (bei jedem Role-Wechsel)
    "handovers": [],            # [{from_role, to_role, time, summary, personnel}]

    # Verlauf
    "timeline": [],             # [{time, role, event, details}]
}


# --- API-Schema: Jetson -> Backend Transfer ---

TRANSFER_SCHEMA = {
    "source_device": "jetson",
    "device_id": "",
    "unit_name": "",            # Einheit / Rufzeichen des sendenden BAT
    "timestamp": "",
    "patient": {},              # PATIENT_SCHEMA
    "flow_status": "",          # Aktueller Flow-Status
    "rfid_tag_id": "",          # RFID-Tag
    "audio_files": [],          # Base64 oder Dateireferenzen
    "raw_transcripts": [],      # Rohe Transkriptionen
}
