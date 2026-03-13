"""
SAFIR — Gemeinsame Datenmodelle fuer Jetson und Backend.
Definiert die Strukturen, die zwischen den Geraeten ausgetauscht werden.
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


# --- Patienten-Datensatz (fliegt durch die gesamte Kette) ---

PATIENT_SCHEMA = {
    "patient_id": "",           # Eindeutige ID
    "timestamp_created": "",    # Ersterfassung
    "current_role": "phase0",   # Aktuelle Stufe in der Rettungskette

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
        "line5": "",  # Patienten Liegend/Gehfaehig
        "line6": "",  # Sicherheitslage
        "line7": "",  # Markierung Landeplatz
        "line8": "",  # Nationalitaet / Status
        "line9": "",  # ABC / Gelaende
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
    "treatments": [],           # Durchgefuehrte Massnahmen
    "medications": [],          # Verabreichte Medikamente

    # Transkripte und Audio
    "transcripts": [],          # [{time, text, speaker, role_level}]
    "audio_files": [],          # Referenzen auf Audiodateien

    # Uebergaben (bei jedem Role-Wechsel)
    "handovers": [],            # [{from_role, to_role, time, summary, personnel}]

    # Verlauf
    "timeline": [],             # [{time, role, event, details}]
}


# --- API-Schema: Jetson -> Backend Transfer ---

TRANSFER_SCHEMA = {
    "source_device": "jetson",
    "timestamp": "",
    "patient": {},              # PATIENT_SCHEMA
    "audio_files": [],          # Base64 oder Dateireferenzen
    "raw_transcripts": [],      # Rohe Transkriptionen
}
