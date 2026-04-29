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

    # Template-Type: "" (default: Patient-Diktat), "9liner" (MEDEVAC),
    # "tccc", "erstbefund" etc. Steuert welche Felder die UI anzeigt und
    # welcher LLM-Extraction-Prompt verwendet wird.
    "template_type": "",

    # 9-Liner MEDEVAC (Bundeswehr GSG 07/2018) — Phase 0 / Role 1
    "nine_liner": {
        "line1": "",   # Koordinaten / Landezone (Ortsangabe, UTM/MGRS)
        "line2": "",   # Anprechpartner vor Ort (Funkrufname / Frequenz für MIST)
        "line3": "",   # Anzahl + Priorität (A=30Min, B=60Min, C=90Min, D=24h, E=Bei Gelegenheit)
        "line4": "",   # Besondere Ausrüstung (A=Keine, B=Defi, C=Drahtschneider, D=San-Rucksack, E=Sonstiges)
        "line5": "",   # Anzahl + Transportart (L=Liegend, A=Gehfähig, E=Eskorte)
        "line6": "",   # Militärische Sicherheit (N=NO ENEMY, P=Possible/Gelb, E=Enemy/Rot, X=Eskorte)
        "line7": "",   # Markierung Landezone (A=Rauchsignal, B=Pyro, C=Keine, D=Andere)
        "line8": "",   # Anzahl + Nationalitäten (A=Eigene, B=Verbündete, D=Zivilisten, E=POW)
        "line9": "",   # Hinweise zur Landezone (Anflugrichtung, Hindernisse)
        "remarks": "", # Anmerkungen nach Readback (RE-Feld, GSG 07/2018)
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

    # Plausibility-Warnings vom Vitals-Validator und anderen Post-LLM-Checks.
    # Liste von Strings, z.B. "Puls=5000 unplausibel (erwartet 20-250)".
    # Frontend zeigt ein Warnsymbol an der Patient-Karte wenn > 0 Warnungen.
    "warnings": [],

    # Confidence-Scores pro Feld (Messe-Hardening B1). Dict-Form:
    #   {"name": 0.95, "rank": 1.0, "mechanism": 0.95,
    #    "injuries": [0.95, 0.80], "injuries_avg": 0.88,
    #    "vitals": {"pulse": 0.95, "bp": 0.75, "spo2": 0.95}}
    # Werte zwischen 0.0 und 1.0 — >=0.9 gruen, 0.6-0.9 gelb, <0.6 rot.
    # Frontend rendert kleine farbige Punkte neben jedem Feld im Patient-
    # Card, damit Messe-Besucher sofort sehen wo das System unsicher ist.
    "confidences": {},
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
