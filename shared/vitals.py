"""Vitals-Plausibility-Filter für SAFIR (Messe-Hardening Phase A2).

Zweck: Messe-Besucher diktieren "Patient hat Puls 5000" oder "Blutdruck
minus 10" — Gemma extrahiert das wortgetreu und SAFIR zeigt unsinnige
Werte an. Hier post-validieren wir die extrahierten Vitals gegen
physiologische Plausibilitaetsgrenzen und verwerfen Out-of-Range-Werte.

Wichtig: Wir werfen NICHTS weg, was nur "ungewoehnlich" ist (z.B. Puls
30 bei einem Sportler unter Sedierung) — nur was physiologisch
UNMOEGLICH ist. Die Grenzen sind bewusst weit gewaehlt, damit echte
Extrem-Werte durchkommen (z.B. Puls 200 im Schock).

Rueckgabe: bereinigtes vitals-Dict + Liste von Warnings als Strings.
Warnings koennen im Patient-Record persistiert werden (PATIENT_SCHEMA
bekommt Feld "warnings": []) und im Frontend als Warn-Icon dargestellt.

Kein LLM-Call, keine externen Deps — reines Python + Regex. Laufzeit
< 1 ms pro Patient.
"""
from __future__ import annotations

import re
from typing import Optional


# ---------------------------------------------------------------------------
# Physiologische Grenzen
# ---------------------------------------------------------------------------
# Die Ranges sind bewusst weit gewaehlt, um echten Extrem-Werten
# Durchlass zu geben (z.B. Bradykardie bei Sportler, Tachykardie im
# Schock). Nur physiologisch unmoegliche Werte werden blockiert.

VITALS_RANGES: dict[str, tuple[float, float]] = {
    "pulse":     (20, 250),      # bpm — < 20 = nicht vital, > 250 = Tachy-Arrhythmie-Grenze
    "spo2":      (40, 100),      # % — < 40 nicht ueberlebensfaehig, > 100 unmoeglich
    "resp_rate": (4, 60),        # /min — < 4 Schnapp-Atmung, > 60 Hecheln
    "temp":      (25.0, 43.0),   # °C — < 25 Hypothermie-Tod, > 43 Hitzetod
    "gcs":       (3, 15),        # Glasgow Coma Scale, offizielle Range 3-15
}

# Blutdruck (bp) wird separat behandelt weil Format "systolisch/diastolisch"
BP_SYS_RANGE = (50, 260)    # mmHg systolisch
BP_DIA_RANGE = (20, 160)    # mmHg diastolisch

# Alter ausserhalb Vitals aber auch eine Plausibility-Check-Groesse
AGE_RANGE = (0, 120)

# ---------------------------------------------------------------------------
# BP-Parser — akzeptiert verschiedene vom LLM produzierte Formate
# ---------------------------------------------------------------------------

_BP_PATTERN = re.compile(
    r"^\s*(-?\d{1,4})\s*(?:/|\\|zu|auf|ueber|über)\s*(-?\d{1,4})\s*$",
    re.IGNORECASE,
)


def _parse_bp(bp_str: str) -> Optional[tuple[int, int]]:
    """Parst Blutdruck-Strings. Akzeptiert:
      "120/80", "120 / 80", "120 zu 80", "120 auf 80", "120 ueber 80".
    Rueckgabe: (systolisch, diastolisch) oder None bei unparsebar."""
    if not bp_str or not isinstance(bp_str, str):
        return None
    m = _BP_PATTERN.match(bp_str.strip())
    if not m:
        return None
    try:
        sys_v = int(m.group(1))
        dia_v = int(m.group(2))
        return (sys_v, dia_v)
    except (ValueError, TypeError):
        return None


def _to_number(v) -> Optional[float]:
    """Konvertiert einen Vital-Wert in float. LLM liefert oft Strings
    ("130") oder Zahlen (130) — wir akzeptieren beides. Leere Strings
    und None -> None (nicht validiert, "kein Wert"). Andere nicht-Zahlen
    -> None (suspicious, aber nicht unser Job hier zu flaggen)."""
    if v in (None, "", "--", "-"):
        return None
    if isinstance(v, bool):
        return None  # True/False ist kein Vitals-Wert
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().replace(",", ".")
        # Prozent-Zeichen, bpm-Suffix etc. abschneiden
        s = re.sub(r"[^\d.\-+]", "", s)
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Haupt-Validator
# ---------------------------------------------------------------------------

def validate_vitals(vitals: dict, age: Optional[str] = None) -> tuple[dict, list[str]]:
    """Validiert ein Vitals-Dict gegen physiologische Grenzen.

    Parameters
    ----------
    vitals : dict mit Keys pulse, bp, resp_rate, spo2, temp, gcs (alle optional)
    age    : optionaler Alter-String/-Zahl fuer separate Validierung

    Returns
    -------
    (cleaned_vitals, warnings)
    - cleaned_vitals: Kopie des Input-Dicts, invalide Werte durch "" ersetzt
    - warnings: Liste von Strings im Format "puls=5000 unplausibel (erwartet 20-250)"
    """
    if not isinstance(vitals, dict):
        return ({}, [])

    cleaned = dict(vitals)
    warnings: list[str] = []

    # Einfache numerische Felder durchpruefen
    for field, (lo, hi) in VITALS_RANGES.items():
        raw = cleaned.get(field)
        if raw in (None, "", "--", "-"):
            continue
        num = _to_number(raw)
        if num is None:
            # LLM hat Unsinn ausgegeben (z.B. "unbekannt"): leeren, nicht warnen
            cleaned[field] = ""
            continue
        if not (lo <= num <= hi):
            cleaned[field] = ""
            # Warnung in menschenlesbarer Form fuers Frontend
            label = {
                "pulse": "Puls",
                "spo2": "SpO2",
                "resp_rate": "Atemfrequenz",
                "temp": "Temperatur",
                "gcs": "GCS",
            }.get(field, field)
            # Zahl-Darstellung ohne unnoetige Dezimalstellen
            num_str = f"{int(num)}" if num == int(num) else f"{num:g}"
            warnings.append(f"{label}={num_str} unplausibel (erwartet {lo:g}-{hi:g})")
        else:
            # Numerisch valide -> optional den urspruenglichen Typ beibehalten.
            # Wenn LLM einen String geliefert hat (pulse "130"), lassen wir
            # das so, sonst bricht die Downstream-Code der Strings erwartet.
            pass

    # Blutdruck separat
    bp = cleaned.get("bp")
    if bp:
        parsed = _parse_bp(bp) if isinstance(bp, str) else None
        if parsed is None:
            # Nicht-parsebarer BP-String (z.B. "unbekannt", "120") -> leeren, keine Warnung
            if not isinstance(bp, str) or not re.search(r"\d", bp):
                cleaned["bp"] = ""
        else:
            sys_v, dia_v = parsed
            sys_ok = BP_SYS_RANGE[0] <= sys_v <= BP_SYS_RANGE[1]
            dia_ok = BP_DIA_RANGE[0] <= dia_v <= BP_DIA_RANGE[1]
            if not (sys_ok and dia_ok):
                cleaned["bp"] = ""
                warnings.append(
                    f"Blutdruck={sys_v}/{dia_v} unplausibel "
                    f"(erwartet {BP_SYS_RANGE[0]}-{BP_SYS_RANGE[1]}/"
                    f"{BP_DIA_RANGE[0]}-{BP_DIA_RANGE[1]})"
                )
            elif sys_v <= dia_v:
                # Systolisch muss > diastolisch sein (sonst Transkriptions-
                # dreher). Beispiel: BP 80/120 -> wahrscheinlich meinte
                # Sprecher 120/80. Wir behalten den Wert, warnen aber.
                warnings.append(
                    f"Blutdruck {sys_v}/{dia_v}: systolisch < diastolisch — "
                    f"bitte pruefen (evtl. Reihenfolge vertauscht)"
                )

    # Age check (ausserhalb Vitals)
    if age is not None:
        num_age = _to_number(age)
        if num_age is not None:
            lo, hi = AGE_RANGE
            if not (lo <= num_age <= hi):
                warnings.append(f"Alter={int(num_age)} unplausibel (erwartet {lo}-{hi})")

    return (cleaned, warnings)
