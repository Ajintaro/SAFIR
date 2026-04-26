"""
SAFIR — Tactical / Medical Interoperability Exports.

Erzeugt vier komplementaere Export-Formate fuer die Anbindung an
externe Fuehrungs- und Healthcare-Systeme. Der Code zielt auf
**echte Standards** statt auf "sieht-aus-wie"-Kosmetik:

  1. CoT XML (Cursor-on-Target 2.0 mit TAK-MEDEVAC-Detail-Schema)
     Konsumiert von ATAK / WinTAK / iTAK / FreeTAKServer / SitaWare
     mit TAK-Bridge. Patient-Marker auf der Lagekarte + 9-Liner-
     Felder unter dem Marker.

  2. NVG Overlay (NATO Vector Graphics 2.0.2)
     STANAG-Vector-Overlay zum Direkt-Import in SitaWare HQ /
     Frontline. APP-6D-Symbole pro Patient.

  3. MEDEVAC 9-Liner XML (ATP-3.7.2 / FM 4-25.13)
     Strikte 1:1-Abbildung der NATO-MEDEVAC-9-Felder. Geeignet
     fuer JSON/XML-Bridges in BMS, JC2, FuInfoSysH-API und
     Bundeswehr Battle Health System (BHS) Vendor-Adapter.

  4. HL7 FHIR R4 Bundle (Patient + Observation + Condition)
     Healthcare-Standard. Konsumiert von KIS, RoleHealth,
     SAP IS-H, Cerner, Epic, jedem modernen MEDEVAC-Stack.

Wichtig zur Einordnung: Bundeswehr BHS hat keine oeffentlich
dokumentierte Ingestion-API. Diese Exporte sind die *richtigen
Standards* — die finale Anbindung benoetigt einen Vendor-Adapter
oder ein BAAINBw-Spezifikationsdokument.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from xml.etree.ElementTree import Element, SubElement, tostring


# ---------------------------------------------------------------------------
# NATO/STANAG-Konstanten
# ---------------------------------------------------------------------------

# APP-6D Symbol Identification Codes (10-stellige neue Kodierung)
SIDC_CASUALTY = "10031000001401000000"  # Friendly, Land Unit, Casualty
SIDC_MEDEVAC_REQUEST = "10031500001213040000"  # Friendly, MEDEVAC Request
SIDC_MEDICAL_FACILITY = "10031000001211040000"  # Friendly, Medical Treatment Facility
SIDC_AMBULANCE = "10031500001213020000"  # Friendly, Ambulance
SIDC_CASUALTY_COLLECTION = "10031000001211020000"  # Friendly, CCP

# CoT 2.0 Event-Types (aus MIL-STD-2525 / APP-6 abgeleitet)
# Korrigiert: ein Verwundeter ist KEIN "Combat Individual" (a-f-G-U-C-I),
# sondern "Casualty/Disabled" (a-f-G-U-C-D).
COT_TYPE_CASUALTY = "a-f-G-U-C-D"
COT_TYPE_MEDEVAC_REQUEST = "b-r-f-h-c"  # request-friendly-human-casualty (TAK)
COT_TYPE_AMBULANCE = "a-f-G-E-V-M"
COT_TYPE_MEDICAL_FACILITY = "a-f-G-I-M"

# Triage zur NATO-MEDEVAC-Precedence (Line 3)
#   A = URGENT          - Verlust Leben/Glied/Augenlicht in 2 h
#   B = URGENT SURGICAL - chirurgisches Team bei Aufnahme noetig
#   C = PRIORITY        - 4 h
#   D = ROUTINE         - 24 h
#   E = CONVENIENCE     - aus Bequemlichkeit, kein medizinischer Druck
TRIAGE_TO_PRECEDENCE = {
    "T1": "B",  # T1 = Sofortbehandlung -> Urgent Surgical
    "T2": "A",  # T2 = Verzoegerte Behandlung -> Urgent (innerh. 2h)
    "T3": "C",  # T3 = Spaetbehandlung -> Priority
    "T4": "D",  # T4 = Erwartend / Tot -> Routine (Spezialfall)
}
PRECEDENCE_LABELS = {
    "A": "URGENT",
    "B": "URGENT-SURGICAL",
    "C": "PRIORITY",
    "D": "ROUTINE",
    "E": "CONVENIENCE",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _isoZ(dt: datetime) -> str:
    """ISO-8601 mit 'Z' Suffix (CoT/STANAG-konform)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _patient_lat_lon(patient: dict, default_lat: float, default_lon: float) -> tuple[float, float]:
    """Holt die Position aus dem Patientendatensatz mit Fallback.

    Patientenposition kann unter ``location.lat/lon``, ``geo.lat/lon``
    oder ``coords`` liegen — abhaengig vom Persistenz-Layer. Faellt
    auf default zurueck (Geraete-Position vom Aufrufer).
    """
    for key in ("location", "geo", "position"):
        sub = patient.get(key) or {}
        if isinstance(sub, dict):
            lat = sub.get("lat")
            lon = sub.get("lon")
            if lat is not None and lon is not None:
                try:
                    return float(lat), float(lon)
                except (TypeError, ValueError):
                    pass
    return default_lat, default_lon


def _injuries_text(patient: dict) -> str:
    inj = patient.get("injuries") or []
    if isinstance(inj, list):
        return ", ".join(str(x) for x in inj if x) or "Nicht angegeben"
    return str(inj)


def _vital_pairs(patient: dict) -> list[tuple[str, str]]:
    v = patient.get("vitals") or {}
    pairs = []
    if v.get("pulse"):
        pairs.append(("Puls", f"{v['pulse']}/min"))
    if v.get("bp"):
        pairs.append(("RR", str(v["bp"])))
    if v.get("spo2"):
        pairs.append(("SpO2", f"{v['spo2']}%"))
    if v.get("gcs"):
        pairs.append(("GCS", str(v["gcs"])))
    if v.get("respiration"):
        pairs.append(("AF", f"{v['respiration']}/min"))
    if v.get("temp"):
        pairs.append(("Temp", f"{v['temp']}°C"))
    return pairs


# ---------------------------------------------------------------------------
# 1. CoT XML — TAK MEDEVAC Schema
# ---------------------------------------------------------------------------

def generate_cot_event(patient: dict, unit_name: str = "", device_id: str = "",
                       lat: float = 50.7374, lon: float = 7.0982) -> str:
    """Erzeugt ein TAK-MEDEVAC-CoT-Event fuer EINEN Verwundeten.

    Schema-Referenz: TAK Product Center MEDEVAC Plugin / FreeTAKServer
    Cursor-on-Target Detail-Schema. Der ``<_medevac_>``-Block enthaelt
    die 9-Liner-Felder als Attribute mit den von TAK erwarteten Namen.
    """
    now = _now()
    pid = patient.get("patient_id") or f"UNKNOWN-{uuid.uuid4().hex[:8]}"
    triage = patient.get("triage") or "T3"
    precedence = TRIAGE_TO_PRECEDENCE.get(triage, "C")

    # CoT-Type richtig: Casualty, NICHT Combat-Individual
    event = Element("event", {
        "version": "2.0",
        "uid": f"SAFIR.MEDEVAC.{pid}",
        "type": COT_TYPE_MEDEVAC_REQUEST,
        "how": "h-e",  # human-estimated
        "time": _isoZ(now),
        "start": _isoZ(now),
        "stale": _isoZ(now + timedelta(hours=1)),
    })

    plat, plon = _patient_lat_lon(patient, lat, lon)
    SubElement(event, "point", {
        "lat": f"{plat:.6f}",
        "lon": f"{plon:.6f}",
        "hae": "0",
        "ce": "50",  # circular error 50 m
        "le": "50",  # linear error
    })

    detail = SubElement(event, "detail")

    callsign = unit_name or device_id or "SAFIR-BAT"
    SubElement(detail, "contact", {
        "callsign": callsign,
        "endpoint": "*:-1:stcp",
    })

    # Litter vs. ambulatory entscheiden anhand von Triage + GCS
    vitals = patient.get("vitals") or {}
    gcs = vitals.get("gcs")
    is_ambulatory = (triage in ("T3",) and (gcs is None or gcs >= 13))
    litter = "0" if is_ambulatory else "1"
    ambulatory = "1" if is_ambulatory else "0"

    # TAK-MEDEVAC-Detail-Schema (Plugin-konforme Attributnamen)
    SubElement(detail, "_medevac_", {
        "title": f"MEDEVAC {pid}",
        "casevac": "false",  # MEDEVAC = dediziertes Medical-Asset
        "freq": "0.0",  # Funkfrequenz, falls verfuegbar
        "urgency": precedence,  # Line 3 — A/B/C/D/E
        "medline_remarks": (
            f"{patient.get('rank','')} {patient.get('name','Unbekannt')} "
            f"({patient.get('unit', unit_name)}) — "
            f"Verletzungen: {_injuries_text(patient)}"
        ).strip(),
        "equipment_none": "true",
        "equipment_hoist": "false",
        "equipment_extraction": "false",
        "equipment_ventilator": "false",
        "litter": litter,         # Line 5
        "ambulatory": ambulatory,  # Line 5
        "security": "N",          # Line 6 — N=No enemy (Demo-default)
        "hlz_marking": "panel",   # Line 7
        "us_military": "0",
        "us_civilian": "0",
        "nonus_military": "1",  # Line 8 — Bundeswehr (non-US)
        "nonus_civilian": "0",
        "epw": "0",
        "child": "0",
        "terrain_none": "true",
        "terrain_slope": "false",
        "terrain_rough": "false",
        "terrain_loose": "false",
        "terrain_other": "false",
        "winds_are_from": "N",
        "friendlies": "1",
        "enemies": "0",
        "hlz_remarks": "",
        "routing": "",
        "zone_prot_selection": "0",
        "nbc_contaminated": "false",  # Line 9
    })

    # Patient-Metadaten (SAFIR-Extension, klar markiert)
    SubElement(detail, "_safir_patient", {
        "patient_id": pid,
        "triage": triage,
        "precedence": precedence,
        "precedence_label": PRECEDENCE_LABELS.get(precedence, "PRIORITY"),
        "name": patient.get("name", ""),
        "rank": patient.get("rank", ""),
        "unit": patient.get("unit", unit_name),
        "blood_type": patient.get("blood_type", ""),
        "allergies": patient.get("allergies", ""),
        "mechanism": patient.get("mechanism", ""),
        "source_device": device_id,
        "schema_version": "1.0",
    })

    # Remarks als Mensch-lesbarer Klartext (TAK zeigt das in der Marker-Card)
    vital_str = "; ".join(f"{k}: {v}" for k, v in _vital_pairs(patient)) or "—"
    remarks = SubElement(detail, "remarks")
    remarks.text = (
        f"MEDEVAC {pid} • {PRECEDENCE_LABELS.get(precedence)} ({triage})\n"
        f"Patient: {patient.get('rank','')} {patient.get('name','Unbekannt')}\n"
        f"Einheit: {patient.get('unit', unit_name)}\n"
        f"Verletzungen: {_injuries_text(patient)}\n"
        f"Vitalwerte: {vital_str}\n"
        f"Quelle: SAFIR / {device_id or 'Feldgeraet'}"
    )

    SubElement(detail, "__group", {"name": "Cyan", "role": "Medic"})

    return tostring(event, encoding="unicode", xml_declaration=False)


def generate_cot_batch(patients: list, unit_name: str = "", device_id: str = "",
                       lat: float = 50.7374, lon: float = 7.0982) -> str:
    """Mehrere CoT-Events als wohlgeformtes XML-Batch.

    Wrap aller Events in einen ``<events>``-Root + XML-Declaration —
    so ist der Output sowohl ein gueltiges XML-Dokument (Browser/
    Validator-tauglich) als auch von TAK-Server-Batch-Ingestion
    konsumierbar. Frueher wurden die Events nur mit Newlines
    konkateniert; das ist zwar TAK-Stream-Format, aber kein gueltiges
    XML-Dokument — Browser brachen mit "Extra content at end of
    document" ab.
    """
    inner = "".join(
        generate_cot_event(p, unit_name, device_id, lat, lon)
        for p in patients
    )
    now = _isoZ(_now())
    header = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<events generator="SAFIR" generated="{now}" '
        f'unit="{unit_name}" source_device="{device_id}" count="{len(patients)}">\n'
    )
    return header + inner + "\n</events>\n"


# ---------------------------------------------------------------------------
# 2. NVG Overlay — NATO Vector Graphics 2.0.2
# ---------------------------------------------------------------------------

def generate_nvg_overlay(patients: list, unit_name: str = "",
                         lat: float = 50.7374, lon: float = 7.0982) -> str:
    """NATO Vector Graphics Overlay mit APP-6D-Symbolen pro Patient."""
    nvg = Element("nvg", {
        "xmlns": "https://tide.act.nato.int/schemas/2012/10/nvg",
        "version": "2.0.2",
    })

    metadata = SubElement(nvg, "metadata")
    SubElement(metadata, "title").text = f"SAFIR Patient-Lage {unit_name}"
    SubElement(metadata, "subject").text = "MEDEVAC / Casualty Tracking"
    SubElement(metadata, "creator").text = "SAFIR — CGI Deutschland"
    SubElement(metadata, "modified").text = _isoZ(_now())

    for p in patients:
        plat, plon = _patient_lat_lon(p, lat, lon)
        triage = p.get("triage") or "T3"
        pid = p.get("patient_id", "UNKNOWN")
        precedence = TRIAGE_TO_PRECEDENCE.get(triage, "C")

        SubElement(nvg, "point", {
            "symbol": "app6a:" + SIDC_CASUALTY,
            "x": f"{plon:.6f}",
            "y": f"{plat:.6f}",
            "label": f"{triage} {p.get('name','Unbekannt')}",
            "uri": f"safir://patient/{pid}",
            "modifiers": (
                f"AS={triage};AB={precedence};T={pid};"
                f"CN={p.get('unit', unit_name)}"
            ),
        })

    return tostring(nvg, encoding="unicode", xml_declaration=True)


# ---------------------------------------------------------------------------
# 3. MEDEVAC 9-Liner XML (ATP-3.7.2 / FM 4-25.13)
# ---------------------------------------------------------------------------

def generate_medevac_9line(patients: list, unit_name: str = "",
                           device_id: str = "",
                           lat: float = 50.7374, lon: float = 7.0982,
                           radio_freq: str = "0.0",
                           radio_callsign: str = "") -> str:
    """Erzeugt einen MEDEVAC-9-Liner-Funkspruch als strukturiertes XML.

    Eine Anfrage = ein Pickup-Standort = beliebig viele Patienten.
    Felder folgen 1:1 ATP-3.7.2 / FM 4-25.13. XML-Schema ist
    SAFIR-eigen (kein einzelner globaler Standard fuer 9-Liner-XML),
    aber jedes Element traegt Line-Nummer + Klartext-Label.
    """
    now = _now()
    callsign = radio_callsign or unit_name or device_id or "SAFIR-BAT"

    # Aggregation ueber alle Patienten
    counts = {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0}
    litter = 0
    ambulatory = 0
    nationalities = set()
    has_nbc = False
    needs_hoist = False
    needs_ventilator = False

    for p in patients:
        triage = p.get("triage") or "T3"
        prec = TRIAGE_TO_PRECEDENCE.get(triage, "C")
        counts[prec] = counts.get(prec, 0) + 1

        v = p.get("vitals") or {}
        gcs = v.get("gcs")
        if triage == "T3" and (gcs is None or gcs >= 13):
            ambulatory += 1
        else:
            litter += 1

        nationalities.add(p.get("nationality") or "DEU")

        injuries = " ".join(p.get("injuries") or []).lower()
        if any(w in injuries for w in ("kontamination", "abc", "nbc", "chemisch", "biologisch", "radioaktiv")):
            has_nbc = True
        if v.get("respiration_assisted"):
            needs_ventilator = True

    # MGRS-Konvertierung waere hier ideal, aber lat/lon ist STANAG-tauglich.
    request = Element("MEDEVAC_REQUEST", {
        "schema": "ATP-3.7.2",
        "schema_version": "1.0",
        "request_uid": f"SAFIR.MEDEVAC.{uuid.uuid4().hex[:8]}",
        "timestamp": _isoZ(now),
        "device_id": device_id,
    })

    # Line 1 — Pickup Location
    line1 = SubElement(request, "Line1_PickupLocation")
    SubElement(line1, "Latitude").text = f"{lat:.6f}"
    SubElement(line1, "Longitude").text = f"{lon:.6f}"
    SubElement(line1, "Description").text = f"BAT-Standort {unit_name}"

    # Line 2 — Radio
    line2 = SubElement(request, "Line2_RadioFrequency")
    SubElement(line2, "Frequency").text = radio_freq
    SubElement(line2, "Callsign").text = callsign
    SubElement(line2, "CallsignSuffix").text = device_id

    # Line 3 — Patients by precedence
    line3 = SubElement(request, "Line3_PatientsByPrecedence")
    for code in ("A", "B", "C", "D", "E"):
        if counts.get(code, 0) > 0:
            SubElement(line3, "Patient", {
                "precedence": code,
                "label": PRECEDENCE_LABELS[code],
                "count": str(counts[code]),
            })
    SubElement(line3, "Total").text = str(sum(counts.values()))

    # Line 4 — Special equipment
    line4 = SubElement(request, "Line4_SpecialEquipment")
    SubElement(line4, "None").text = (
        "true" if not (needs_hoist or needs_ventilator) else "false"
    )
    SubElement(line4, "Hoist").text = "true" if needs_hoist else "false"
    SubElement(line4, "ExtractionEquipment").text = "false"
    SubElement(line4, "Ventilator").text = "true" if needs_ventilator else "false"

    # Line 5 — Patients by type
    line5 = SubElement(request, "Line5_PatientsByType")
    SubElement(line5, "Litter").text = str(litter)
    SubElement(line5, "Ambulatory").text = str(ambulatory)

    # Line 6 — Security at pickup site
    line6 = SubElement(request, "Line6_Security")
    SubElement(line6, "Code").text = "N"  # Demo-Default
    SubElement(line6, "Label").text = "No enemy troops in area"

    # Line 7 — Method of marking pickup site
    line7 = SubElement(request, "Line7_Marking")
    SubElement(line7, "Method").text = "PANEL"
    SubElement(line7, "Description").text = "Signalpaneel orange"

    # Line 8 — Patient nationality and status
    line8 = SubElement(request, "Line8_PatientStatusAndNationality")
    for nat in sorted(nationalities) or ["DEU"]:
        SubElement(line8, "Nationality").text = nat
    SubElement(line8, "MilitaryCount").text = str(sum(counts.values()))
    SubElement(line8, "CivilianCount").text = "0"
    SubElement(line8, "EPWCount").text = "0"
    SubElement(line8, "ChildCount").text = "0"

    # Line 9 — NBC contamination (war) / Threat description (peacetime)
    line9 = SubElement(request, "Line9_NBCContamination")
    SubElement(line9, "Contaminated").text = "true" if has_nbc else "false"
    if has_nbc:
        SubElement(line9, "Type").text = "Unknown"

    # Patient-Liste als Anhang (optional, fuer Empfaenger der mehr Daten will)
    plist = SubElement(request, "PatientDetails")
    for p in patients:
        triage = p.get("triage") or "T3"
        SubElement(plist, "Patient", {
            "patient_id": p.get("patient_id", ""),
            "triage": triage,
            "precedence": TRIAGE_TO_PRECEDENCE.get(triage, "C"),
            "name": p.get("name", ""),
            "rank": p.get("rank", ""),
            "unit": p.get("unit", ""),
            "blood_type": p.get("blood_type", ""),
            "allergies": p.get("allergies", ""),
            "injuries": "; ".join(p.get("injuries") or []),
        })

    return tostring(request, encoding="unicode", xml_declaration=True)


# ---------------------------------------------------------------------------
# 4. HL7 FHIR R4 Bundle
# ---------------------------------------------------------------------------

# LOINC-Codes fuer typische Vitalwerte
_LOINC = {
    "pulse": ("8867-4", "Heart rate"),
    "spo2": ("59408-5", "Oxygen saturation"),
    "respiration": ("9279-1", "Respiratory rate"),
    "temp": ("8310-5", "Body temperature"),
    "gcs": ("9269-2", "Glasgow coma score total"),
    "bp_systolic": ("8480-6", "Systolic blood pressure"),
    "bp_diastolic": ("8462-4", "Diastolic blood pressure"),
}

# SNOMED-CT-Codes fuer Triage (NATO-MEDEVAC-Mapping)
_SNOMED_TRIAGE = {
    "T1": ("422535002", "Triage immediate"),
    "T2": ("422512004", "Triage delayed"),
    "T3": ("422548002", "Triage minimal"),
    "T4": ("422554003", "Triage expectant"),
}


def _fhir_patient_resource(p: dict, fhir_id: str) -> dict:
    name_parts = (p.get("name") or "").strip().split()
    family = name_parts[-1] if name_parts else "Unknown"
    given = name_parts[:-1] if len(name_parts) > 1 else []

    resource = {
        "resourceType": "Patient",
        "id": fhir_id,
        "identifier": [
            {
                "system": "https://safir.cgi.com/patient",
                "value": p.get("patient_id", fhir_id),
            }
        ],
        "name": [
            {
                "family": family,
                "given": given or [p.get("name") or "Unknown"],
                "prefix": [p.get("rank")] if p.get("rank") else [],
            }
        ],
        "active": True,
    }
    if p.get("dob"):
        resource["birthDate"] = p["dob"]
    if p.get("blood_type"):
        # ABO-Bloodtype als Extension (HL7 hat keinen Top-level-Slot)
        resource["extension"] = [{
            "url": "https://safir.cgi.com/fhir/blood-type",
            "valueString": p["blood_type"],
        }]
    return resource


def _fhir_observation(loinc_code: str, display: str, value: float | str,
                      unit: str | None, patient_ref: str, when: str,
                      obs_id: str) -> dict:
    obs: dict = {
        "resourceType": "Observation",
        "id": obs_id,
        "status": "final",
        "category": [{
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                "code": "vital-signs",
                "display": "Vital Signs",
            }],
        }],
        "code": {
            "coding": [{"system": "http://loinc.org", "code": loinc_code, "display": display}],
        },
        "subject": {"reference": patient_ref},
        "effectiveDateTime": when,
    }
    if isinstance(value, (int, float)) and unit:
        obs["valueQuantity"] = {
            "value": value,
            "unit": unit,
            "system": "http://unitsofmeasure.org",
            "code": unit,
        }
    else:
        obs["valueString"] = str(value)
    return obs


def _fhir_condition(injury_text: str, patient_ref: str, when: str,
                    cond_id: str) -> dict:
    return {
        "resourceType": "Condition",
        "id": cond_id,
        "clinicalStatus": {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                "code": "active",
            }],
        },
        "verificationStatus": {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                "code": "provisional",
            }],
        },
        "category": [{
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/condition-category",
                "code": "encounter-diagnosis",
                "display": "Encounter Diagnosis",
            }],
        }],
        "code": {"text": injury_text},
        "subject": {"reference": patient_ref},
        "recordedDate": when,
    }


def _patient_to_fhir_entries(patient: dict, when: str) -> list[dict]:
    """Konvertiert einen SAFIR-Patient in FHIR Bundle-Entries.

    Erzeugt:
      - 1 Patient-Ressource
      - 0..N Observation-Ressourcen (Vitalwerte, falls vorhanden)
      - 0..N Condition-Ressourcen (Verletzungen, falls vorhanden)
      - 1 Encounter (MEDEVAC-Begegnung)
    """
    pid = patient.get("patient_id") or f"unk-{uuid.uuid4().hex[:8]}"
    fhir_id = pid.replace(".", "-")
    patient_ref = f"Patient/{fhir_id}"
    entries = []

    # Patient
    entries.append({
        "fullUrl": f"urn:uuid:{fhir_id}",
        "resource": _fhir_patient_resource(patient, fhir_id),
    })

    # Vitalwerte als Observations
    v = patient.get("vitals") or {}
    obs_definitions: list[tuple[str, str, str, float | str | None, str | None]] = []
    if v.get("pulse"):
        obs_definitions.append(("pulse", *_LOINC["pulse"], v["pulse"], "/min"))
    if v.get("spo2"):
        obs_definitions.append(("spo2", *_LOINC["spo2"], v["spo2"], "%"))
    if v.get("respiration"):
        obs_definitions.append(("resp", *_LOINC["respiration"], v["respiration"], "/min"))
    if v.get("temp"):
        obs_definitions.append(("temp", *_LOINC["temp"], v["temp"], "Cel"))
    if v.get("gcs"):
        obs_definitions.append(("gcs", *_LOINC["gcs"], v["gcs"], "{score}"))
    bp = v.get("bp")
    if bp and "/" in str(bp):
        try:
            sys_v, dia_v = str(bp).split("/", 1)
            obs_definitions.append(("bp-sys", *_LOINC["bp_systolic"], int(sys_v.strip()), "mm[Hg]"))
            obs_definitions.append(("bp-dia", *_LOINC["bp_diastolic"], int(dia_v.strip()), "mm[Hg]"))
        except (ValueError, AttributeError):
            pass

    for slug, code, display, value, unit in obs_definitions:
        oid = f"{fhir_id}-obs-{slug}"
        entries.append({
            "fullUrl": f"urn:uuid:{oid}",
            "resource": _fhir_observation(code, display, value, unit, patient_ref, when, oid),
        })

    # Verletzungen als Conditions
    for idx, injury in enumerate(patient.get("injuries") or []):
        cid = f"{fhir_id}-cond-{idx}"
        entries.append({
            "fullUrl": f"urn:uuid:{cid}",
            "resource": _fhir_condition(injury, patient_ref, when, cid),
        })

    # Encounter (MEDEVAC-Begegnung)
    eid = f"{fhir_id}-enc"
    triage = patient.get("triage") or "T3"
    snomed_code, snomed_display = _SNOMED_TRIAGE.get(triage, ("422548002", "Triage minimal"))
    entries.append({
        "fullUrl": f"urn:uuid:{eid}",
        "resource": {
            "resourceType": "Encounter",
            "id": eid,
            "status": "in-progress",
            "class": {
                "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                "code": "EMER",
                "display": "emergency",
            },
            "priority": {
                "coding": [{
                    "system": "http://snomed.info/sct",
                    "code": snomed_code,
                    "display": snomed_display,
                }],
            },
            "subject": {"reference": patient_ref},
            "period": {"start": when},
            "reasonCode": [{"text": _injuries_text(patient)}],
            "serviceType": {"text": "MEDEVAC / Tactical Combat Casualty Care"},
        },
    })

    return entries


def generate_fhir_bundle(patients: list, unit_name: str = "",
                        device_id: str = "") -> str:
    """Erzeugt ein HL7 FHIR R4 Collection-Bundle als JSON-String.

    Bundle-Type ``collection`` = informational batch ohne Transaktions-
    Semantik, geeignet fuer Push-Replikation / Patientenakte.
    Empfangsseitig wird das Bundle mit ``POST /fhir`` ingesteted, jedes
    Resource individuell verarbeitet.
    """
    when = _isoZ(_now())
    bundle: dict = {
        "resourceType": "Bundle",
        "id": f"safir-bundle-{uuid.uuid4().hex[:12]}",
        "meta": {
            "lastUpdated": when,
            "tag": [{
                "system": "https://safir.cgi.com/fhir/source",
                "code": device_id or "safir",
                "display": f"SAFIR {unit_name}".strip(),
            }],
        },
        "type": "collection",
        "timestamp": when,
        "entry": [],
    }

    for patient in patients:
        bundle["entry"].extend(_patient_to_fhir_entries(patient, when))

    return json.dumps(bundle, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Status / Capability-Reporting
# ---------------------------------------------------------------------------

def get_sitaware_status() -> dict:
    """Status der Interop-Schnittstelle fuer das Dashboard."""
    return {
        "available": True,
        "exports": [
            {
                "id": "cot",
                "label": "CoT XML (TAK MEDEVAC)",
                "format": "application/xml",
                "standards": ["CoT 2.0", "TAK MEDEVAC", "APP-6D"],
                "consumers": ["ATAK", "WinTAK", "iTAK", "FreeTAKServer", "SitaWare TAK-Bridge"],
            },
            {
                "id": "nvg",
                "label": "NVG Overlay",
                "format": "application/xml",
                "standards": ["NATO Vector Graphics 2.0.2", "APP-6D"],
                "consumers": ["SitaWare HQ", "SitaWare Frontline", "MIP-konforme C2-Systeme"],
            },
            {
                "id": "medevac",
                "label": "MEDEVAC 9-Liner XML",
                "format": "application/xml",
                "standards": ["ATP-3.7.2", "FM 4-25.13", "STANAG 2087"],
                "consumers": ["BMS-Vendor-Adapter", "FuInfoSysH", "Bundeswehr BHS-Integration"],
            },
            {
                "id": "fhir",
                "label": "HL7 FHIR R4 Bundle",
                "format": "application/json",
                "standards": ["FHIR R4", "LOINC", "SNOMED CT", "UCUM"],
                "consumers": ["KIS", "RoleHealth", "SAP IS-H", "Cerner", "Epic", "moderne MEDEVAC-Stacks"],
            },
        ],
        "compatible_systems": [
            "SitaWare Edge / Frontline / HQ",
            "ATAK / WinTAK / iTAK",
            "FreeTAKServer",
            "NATO JCOP",
            "FHIR-konforme Klinikinformationssysteme",
        ],
        "disclaimer": (
            "Die Exporte folgen oeffentlich dokumentierten NATO-/HL7-"
            "Standards. Die finale Anbindung an Bundeswehr Battle Health "
            "System (BHS) erfolgt ueber den Vendor-Adapter / die "
            "BAAINBw-Spezifikation der jeweiligen Zielinstanz."
        ),
    }
