"""
SAFIR — SitaWare Interoperabilitäts-Schnittstelle (Demo).

Generiert Cursor-on-Target (CoT) XML-Events und NATO APP-6D SIDCs
für die Integration mit SitaWare Edge/Frontline/Headquarters.

CoT ist der de-facto NATO-Standard für taktische Lagebildmeldungen.
SitaWare unterstützt CoT nativ über MIP, NFFI und direkte XML-Ingestion.

Protokolle: CoT XML (MITRE), NVG (NATO Vector Graphics)
Standards:  APP-6D (NATO Joint Military Symbology), MIL-STD-2525D
"""

import uuid
from datetime import datetime, timedelta, timezone
from xml.etree.ElementTree import Element, SubElement, tostring


# --- APP-6D Symbol Identification Codes (SIDC) ---
# Format: 10 SSCCFFFFFF (10-stellig, neue APP-6D Kodierung)
SIDC_MEDEVAC_REQUEST = "10031500001213040000"  # Friendly, MEDEVAC Request
SIDC_MEDICAL_FACILITY = "10031000001211040000"  # Friendly, Medical Treatment Facility
SIDC_CASUALTY_COLLECTION = "10031000001211020000"  # Friendly, Casualty Collection Point
SIDC_AMBULANCE = "10031500001213020000"  # Friendly, Ambulance

# CoT Event Types (MIL-STD-2525 / APP-6 mapped)
COT_TYPE_MEDEVAC = "a-f-G-U-C-I"     # Friendly Ground Unit Combat Individual
COT_TYPE_MEDICAL = "a-f-G-I-M"        # Friendly Ground Installation Medical
COT_TYPE_CASEVAC = "a-f-G-E-V-M"      # Friendly Ground Equipment Vehicle Medical

# Triage zu NATO Evakuierungspriorität
TRIAGE_TO_EVAC = {
    "T1": "urgent-surgical",
    "T2": "urgent",
    "T3": "priority",
    "T4": "routine",
}


def generate_cot_event(patient: dict, unit_name: str = "", device_id: str = "",
                       lat: float = 48.1351, lon: float = 11.5820) -> str:
    """Generiert ein CoT XML Event für einen MEDEVAC-Patienten.

    Das Event kann von SitaWare, ATAK, WinTAK und jedem
    CoT-kompatiblen System empfangen werden.
    """
    now = datetime.now(timezone.utc)
    stale = now + timedelta(minutes=30)

    pid = patient.get("patient_id", str(uuid.uuid4()))
    triage = patient.get("triage", "T3")
    evac_priority = TRIAGE_TO_EVAC.get(triage, "routine")

    event = Element("event", {
        "version": "2.0",
        "uid": f"SAFIR-MEDEVAC-{pid}",
        "type": COT_TYPE_MEDEVAC,
        "how": "h-e",  # human-estimated
        "time": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "start": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "stale": stale.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    })

    SubElement(event, "point", {
        "lat": str(lat),
        "lon": str(lon),
        "hae": "0",
        "ce": "50",
        "le": "50",
    })

    detail = SubElement(event, "detail")

    # Kontakt / Rufzeichen
    SubElement(detail, "contact", {
        "callsign": unit_name or "SAFIR",
        "endpoint": f"*:-1:stcp",
    })

    # MEDEVAC 9-Liner Kerndaten
    remarks_text = _build_medevac_remarks(patient, unit_name)
    remarks = SubElement(detail, "remarks")
    remarks.text = remarks_text

    # Taktische Metadaten
    SubElement(detail, "_medevac_", {
        "patient_id": pid,
        "triage": triage,
        "evac_priority": evac_priority,
        "patient_name": patient.get("name", "Unbekannt"),
        "injuries": "; ".join(patient.get("injuries", [])),
        "source_device": device_id,
        "sidc": SIDC_MEDEVAC_REQUEST,
    })

    # Flow-Tags für Routing
    SubElement(detail, "_flow-tags_", {
        f"SAFIR-{device_id}": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    })

    return tostring(event, encoding="unicode", xml_declaration=False)


def _build_medevac_remarks(patient: dict, unit_name: str) -> str:
    """Baut MEDEVAC-Freitext für CoT Remarks."""
    triage = patient.get("triage", "T3")
    name = patient.get("name", "Unbekannt")
    injuries = ", ".join(patient.get("injuries", [])) or "Nicht angegeben"
    vitals = patient.get("vitals", {})

    lines = [
        f"MEDEVAC REQUEST — {unit_name}",
        f"Patient: {name} | Triage: {triage} | Priorität: {TRIAGE_TO_EVAC.get(triage, 'routine')}",
        f"Verletzungen: {injuries}",
    ]
    if vitals.get("pulse") or vitals.get("spo2"):
        vital_parts = []
        if vitals.get("pulse"): vital_parts.append(f"P:{vitals['pulse']}")
        if vitals.get("bp"): vital_parts.append(f"RR:{vitals['bp']}")
        if vitals.get("spo2"): vital_parts.append(f"SpO2:{vitals['spo2']}")
        lines.append(f"Vitals: {' '.join(vital_parts)}")

    lines.append(f"Quelle: SAFIR Feldgerät")
    return " | ".join(lines)


def generate_cot_batch(patients: list, unit_name: str = "", device_id: str = "",
                       lat: float = 48.1351, lon: float = 11.5820) -> str:
    """Generiert mehrere CoT Events als XML-Batch."""
    events = []
    for p in patients:
        events.append(generate_cot_event(p, unit_name, device_id, lat, lon))
    return "\n".join(events)


def generate_nvg_overlay(patients: list, unit_name: str = "",
                         lat: float = 48.1351, lon: float = 11.5820) -> str:
    """Generiert ein NATO Vector Graphics (NVG) Overlay mit Patienten-Symbolen.

    NVG ist der NATO-Standard für taktische Grafik-Overlays (STANAG).
    SitaWare kann NVG-Overlays direkt importieren.
    """
    nvg = Element("nvg", {
        "xmlns": "https://tide.act.nato.int/schemas/2012/10/nvg",
        "version": "2.0.2",
    })

    for p in patients:
        triage = p.get("triage", "T3")
        pid = p.get("patient_id", "")
        sidc = SIDC_MEDEVAC_REQUEST

        point = SubElement(nvg, "point", {
            "symbol": sidc,
            "x": str(lon),
            "y": str(lat),
            "label": f"{triage} {p.get('name', 'Unbekannt')}",
            "uri": f"safir://patient/{pid}",
            "modifiers": f"triage={triage};unit={unit_name}",
        })

    return tostring(nvg, encoding="unicode", xml_declaration=True)


def get_sitaware_status() -> dict:
    """Status der SitaWare-Schnittstelle für das Dashboard."""
    return {
        "available": True,
        "protocol": "CoT 2.0 / NVG 2.0.2",
        "standards": ["APP-6D", "MIL-STD-2525D", "STANAG 4609", "MIP 4.3+"],
        "export_formats": ["CoT XML", "NVG", "TacticalJSON"],
        "compatible_systems": [
            "SitaWare Edge 2.0",
            "SitaWare Frontline",
            "SitaWare Headquarters",
            "ATAK / WinTAK",
            "NATO JCOP",
        ],
    }
