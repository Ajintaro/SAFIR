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

    # 9-Liner MEDEVAC (NATO ATP-3.7.2 mit deutschen Bezeichnungen, 2026-04-30)
    # Schema-Update: Phonetisches Alphabet als Codes (Alfa=A, Bravo=B, etc.)
    # Sprechtext-Konvention: "Zeile eins ...", "Zeile zwei ...", optional
    # "naechste Zeile" als Pre-Trigger fuer die naechste Zeile.
    "nine_liner": {
        "line1": "",   # Pickup-Site / Aufnahmestelle (frei: MGRS + Pickup-Zone-Name)
        "line2": "",   # Funkkanal + Rufname + Suffix (frei)
        "line3": "",   # Anzahl + Prioritaet  (A=URGENT, B=URGENT-SURG, C=PRIORITY, D=ROUTINE, E=CONVENIENCE)
        "line4": "",   # Sonderausruestung    (A=None, B=Hoist/Winde, C=Extraction, D=Ventilator)
        "line5": "",   # Patienten-Transport  (L=Litter/liegend, A=Ambulatory/gehfaehig)
        "line6": "",   # Sicherheit Pickup    (N=No Enemy, P=Possible, E=Enemy, X=Enemy+Eskorte)
        "line7": "",   # Markierung Pickup    (A=Panels, B=Pyro, C=Smoke, D=None, E=Other)
        "line8": "",   # Nationalitaet+Status (A=US-Mil, B=US-Civ, C=Non-US-Mil, D=Non-US-Civ, E=POW)
        "line9": "",   # CBRN-Kontamination   (C=Chemical, B=Biological, R=Radiological, N=Nuclear)
        "remarks": "", # Anmerkungen / Readback / sonstige Hinweise
    },

    # ATMIST Patientenuebergabe (sechs-zeiliges militaer-medizinisches
    # Uebergabe-Schema, 2026-04-30). Sprechtext: "A, Angaben: ...",
    # "T, Time: ...", "M, Mechanismus: ...", "I, Injury: ...",
    # "S, Signs: ...", "T, Treatment: ...". Pro Buchstabe ein
    # Freitext-Feld — keine Codes wie beim 9-Liner.
    "atmist": {
        "line1": "",   # A — Angaben/Alter (Name, Geschlecht, Alter, Gewicht)
        "line2": "",   # T — Time (Verletzungs-/Uebergabezeit, Verlauf)
        "line3": "",   # M — Mechanismus (Wie ist die Verletzung passiert)
        "line4": "",   # I — Injury (Verletzungen, Lokalisation, Kontrolliert/Akut)
        "line5": "",   # S — Signs (Vitals, Bewusstsein, Schmerz)
        "line6": "",   # T — Treatment (Massnahmen, Tourniquet, Medikation)
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

    # Audit-Log: Wer hat wann was geaendert.
    # Eintrags-Format:
    #   {
    #     "timestamp": "2026-04-29T16:45:00",
    #     "operator_uid": "9CF13904",      # leer bei Voice/RFID-Auto-Aktionen
    #     "operator_name": "Bediener 1",   # leer wenn kein Operator eingeloggt
    #     "operator_role": "arzt",         # arzt|sani|bat_soldat etc.
    #     "field": "vitals.pulse",         # punktnotiert
    #     "old_value": "—",                # alter Wert (truncated wenn lang)
    #     "new_value": "120",              # neuer Wert
    #     "change_type": "manual_edit",    # manual_edit|voice_command|llm_extraction|sync_inbound
    #     "device": "jetson-01",           # welches Geraet hat es geaendert
    #   }
    # Wird von log_patient_change() in app.py befuellt. Wird mit-synced
    # zwischen Jetson und Surface (TRANSFER_SCHEMA), damit beide Seiten
    # die gleiche Wahrheit haben. Append-only — keine Loeschung,
    # keine Rueckgaengig-Funktion.
    "audit_log": [],
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
