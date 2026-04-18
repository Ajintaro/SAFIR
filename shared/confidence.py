"""Confidence-Scoring pro extrahiertem Patientenfeld (Messe-Hardening B1).

Zweck: Dem Messe-Besucher **explizit sichtbar machen, wo das System sich
sicher ist und wo nicht**. Jedes extrahierte Feld bekommt einen
Confidence-Wert zwischen 0.0 und 1.0, der im Frontend als Farb-Punkt
gerendert wird:

  🟢 Grün  ≥ 0.9   — exakter Match / hohe Sicherheit
  🟡 Gelb  0.6-0.9 — fuzzy Match / plausibel aber nicht exakt
  🔴 Rot   < 0.6   — unsicher, bitte manuell pruefen

Das entkraeftet den klassischen BWI-Vorwurf "das LLM halluziniert — wie
weiss man was stimmt?" direkt im UI. Der Sanitaeter sieht auf einen
Blick welche Felder Vertrauen verdienen und welche er pruefen sollte.

Implementierung: Pure Python, keine externen Deps, < 1 ms pro Patient.
Nutzt die bestehenden Hardening-Bausteine wieder (bundeswehr_ranks,
content_filter, vitals) — alle haben schon "weiss"-Listen oder Ranges,
die wir nur noch zu Confidence-Werten aggregieren.

Skala-Design:
  1.00 — perfekter Match gegen Whitelist (Exact-Match, Ranges im Idealbereich)
  0.90 — sehr gut (Standard-Werte, valider Format, LLM-extracted)
  0.80 — akzeptabel (fuzzy-matched, Werte am Rand des Normalbereichs)
  0.60 — grenzwertig (keine Validation moeglich, ungewoehnlich aber plausibel)
  0.40 — unsicher (wenig Evidenz, koennte halluziniert sein)
  0.00 — kein Match / verworfen
"""
from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------------------------
# Field-Scorers
# ---------------------------------------------------------------------------

def score_name(name: str) -> float:
    """Scort einen Patienten-Namen. Typisch: Nachname, capitalized, 3-30 Zeichen.
    Hohe Confidence bei klassischer Form, mittel wenn mixed case oder
    ungewoehnlich, niedrig bei Zahlen/Sonderzeichen.
    """
    if not name or not isinstance(name, str):
        return 0.0
    n = name.strip()
    if not n:
        return 0.0
    # Zahlen im Namen = sehr verdaechtig
    if any(ch.isdigit() for ch in n):
        return 0.2
    # Laenge out-of-range
    if len(n) < 2 or len(n) > 40:
        return 0.4
    # Typisch-Form: Beginnt mit Grossbuchstabe, nur Buchstaben + Whitespace + -
    if re.match(r"^[A-ZÄÖÜ][a-zäöüßA-ZÄÖÜ\-\s\.]+$", n):
        # Bonus wenn es aus 1-3 Wortteilen besteht (Vorname Nachname)
        parts = n.split()
        if 1 <= len(parts) <= 3:
            # Jeder Teil capitalized?
            if all(p[0].isupper() for p in parts if p):
                return 0.95
        return 0.85
    # Hat zwar Buchstaben aber ungewoehnliche Form (z.B. "meyer", "MEYER")
    if re.match(r"^[a-zäöüßA-ZÄÖÜ\-\s\.]+$", n):
        return 0.7
    return 0.4


def score_rank(rank: str, existing_confidence: float | None = None) -> float:
    """Scort den Dienstgrad. Wenn bereits ein rank_confidence vom
    normalize_rank-Aufruf vorliegt (bundeswehr_ranks.py), uebernehmen wir
    den direkt. Sonst: neue Whitelist-Pruefung."""
    if not rank or not isinstance(rank, str):
        return 0.0
    if existing_confidence is not None:
        try:
            return float(existing_confidence)
        except (ValueError, TypeError):
            pass
    try:
        from shared.bundeswehr_ranks import is_known_rank, normalize_rank
        if is_known_rank(rank):
            return 1.0
        _, conf = normalize_rank(rank)
        return float(conf)
    except Exception:
        # Fallback: Wenn wir das Modul nicht laden koennen, geben wir
        # mittlere Confidence — wir koennen den Rang nicht validieren.
        return 0.5


def score_injury(injury: str) -> float:
    """Scort eine einzelne Verletzungsbeschreibung. Plausibel ist:
    - medizinisches Keyword im String (Verletzung, Fraktur, Schuss, etc.)
    - realistische Laenge (< 200 Zeichen)
    - keine Zahlen-Ketten oder Injection-Marker
    """
    if not injury or not isinstance(injury, str):
        return 0.0
    s = injury.strip()
    if not s:
        return 0.0
    if len(s) > 300:
        return 0.3  # verdaechtig lang
    # Medical-Keyword-Check: wenn die content_filter-Pattern matched,
    # ist das ein starkes Signal dass es eine echte Verletzungsbeschreibung
    # ist.
    try:
        from shared.content_filter import _PATTERN as _MED_PATTERN
        if _MED_PATTERN.search(s):
            # Zusatz-Check: hat das Wort typische Verletzungs-Endungen?
            injury_markers = (
                "verletzung", "wunde", "fraktur", "bruch", "riss",
                "prellung", "quetschung", "distorsion", "amputation",
                "blutung", "verbrennung", "haematom", "hämatom",
                "schuss", "splitter", "platz", "schnitt", "stich",
            )
            low = s.lower()
            if any(m in low for m in injury_markers):
                return 0.95
            return 0.80  # anatomisch/medizinisch aber kein klarer Verletzungs-Begriff
    except Exception:
        pass
    # Kein Medical-Keyword, aber trotzdem plausible Laenge — koennte
    # legitim sein (z.B. "Kreislaufprobleme", "Schmerzen") ohne dass das
    # Pattern ihn erwischt. Gelb.
    return 0.55


def score_mechanism(mech: str) -> float:
    """Verletzungs-Mechanismus (Schussverletzung, IED, Sturz, etc.).
    Whitelist der typischen Mechanismen — Exact-Match = hoch, fuzzy = mittel."""
    if not mech or not isinstance(mech, str):
        return 0.0
    MECHS_CANONICAL = {
        # Kampf
        "schussverletzung", "schuss", "splitterverletzung", "splitter",
        "ied", "mine", "explosion", "druckwelle", "granate",
        # Zivil
        "sturz", "verkehrsunfall", "fahrzeugunfall", "unfall",
        "stichverletzung", "schnittverletzung", "bisswunde",
        # Umgebung
        "verbrennung", "verbruehung", "unterkuehlung", "hitzeschlag",
        "ertrinken", "stromschlag",
        # Sonst
        "kontusion", "distorsion", "fraktur",
    }
    low = mech.strip().lower()
    if not low:
        return 0.0
    # Exact / Teilstring-Match
    for canonical in MECHS_CANONICAL:
        if canonical in low:
            return 0.95
    # Plausible Laenge aber unbekannter Mechanismus
    if 3 <= len(low) <= 60:
        return 0.55
    return 0.3


# Vitals-Ideal-Ranges (engere "grüne" Zone als VITALS_RANGES in vitals.py).
# Wenn Wert im Ideal-Bereich: high confidence. Rand des Normbereich: medium.
# Ausserhalb Normalbereich (aber noch in VITALS_RANGES drin weil nicht
# verworfen): low confidence (Warning-Kandidat).

_VITALS_IDEAL = {
    "pulse":     (50, 110),     # Ruhepuls / leicht erhoeht
    "spo2":      (94, 100),     # unauffaellig
    "resp_rate": (10, 20),
    "temp":      (36.0, 38.5),
    "gcs":       (13, 15),      # leichte bis keine Stoerung
}

# Akzeptabler Randbereich (noch medium confidence)
_VITALS_ACCEPTABLE = {
    "pulse":     (40, 150),
    "spo2":      (88, 100),
    "resp_rate": (8, 30),
    "temp":      (34.0, 40.0),
    "gcs":       (9, 15),
}


def score_vital(field: str, value: Any) -> float:
    """Scort einen einzelnen Vital-Wert. Der A2-Validator hat unplausible
    Werte bereits rausgeworfen; hier beurteilen wir nur die Plausibilitaet
    INNERHALB des Normalbereichs (Normal / Grenzbereich / ausser Norm).
    """
    if value in (None, "", 0):
        return 0.0
    # In Zahl umwandeln
    try:
        if isinstance(value, (int, float)):
            num = float(value)
        else:
            s = str(value).strip().replace(",", ".")
            s = re.sub(r"[^\d.\-+]", "", s)
            if not s:
                return 0.0
            num = float(s)
    except (ValueError, TypeError):
        return 0.0

    ideal = _VITALS_IDEAL.get(field)
    accept = _VITALS_ACCEPTABLE.get(field)
    if ideal and accept:
        lo_i, hi_i = ideal
        lo_a, hi_a = accept
        if lo_i <= num <= hi_i:
            return 0.95
        if lo_a <= num <= hi_a:
            return 0.75
        # Noch irgendwo plausibel (A2 hat's nicht rausgeworfen)
        return 0.55
    # Unbekannter Vital-Typ
    return 0.7


def score_bp(bp_str: str) -> float:
    """Scort Blutdruck-String. Parsbar und beide Werte im Normbereich = 0.95."""
    if not bp_str or not isinstance(bp_str, str):
        return 0.0
    try:
        from shared.vitals import _parse_bp
        parsed = _parse_bp(bp_str)
    except Exception:
        return 0.5
    if parsed is None:
        return 0.3  # nicht parsbar
    sys_v, dia_v = parsed
    # Normalbereich (enger als Validierung in A2)
    sys_ok = 100 <= sys_v <= 160
    dia_ok = 60 <= dia_v <= 100
    sys_accept = 80 <= sys_v <= 200
    dia_accept = 40 <= dia_v <= 120
    if sys_ok and dia_ok:
        return 0.95
    if sys_accept and dia_accept:
        return 0.75
    return 0.55


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------

def compute_confidences(enrichment: dict) -> dict:
    """Baut ein Confidence-Dict aus einem Enrichment-Result.

    Rueckgabe-Dict enthaelt einen Eintrag pro Top-Level-Feld; Listen-Felder
    (injuries) bekommen einen Eintrag pro Listen-Item + einen aggregierten
    Gesamtwert.

    Beispiel-Ausgabe:
      {
        "name":      0.95,
        "rank":      1.00,
        "mechanism": 0.95,
        "injuries":  [0.95, 0.80],       # pro Injury-Item
        "injuries_avg": 0.88,
        "vitals": {
          "pulse":     0.95,
          "bp":        0.75,
          "spo2":      0.95,
        },
      }
    """
    if not isinstance(enrichment, dict):
        return {}
    out: dict = {}

    # Einfache Felder
    if enrichment.get("name"):
        out["name"] = round(score_name(enrichment["name"]), 3)
    existing_rc = enrichment.get("rank_confidence")
    if enrichment.get("rank"):
        out["rank"] = round(score_rank(enrichment["rank"], existing_rc), 3)
    if enrichment.get("mechanism"):
        out["mechanism"] = round(score_mechanism(enrichment["mechanism"]), 3)

    # Injuries-Liste
    injuries = enrichment.get("injuries") or []
    if isinstance(injuries, list) and injuries:
        inj_scores = [round(score_injury(x), 3) for x in injuries if x]
        if inj_scores:
            out["injuries"] = inj_scores
            out["injuries_avg"] = round(sum(inj_scores) / len(inj_scores), 3)

    # Vitals
    vitals_out: dict = {}
    for field in ("pulse", "spo2", "resp_rate", "temp", "gcs"):
        if field in enrichment and enrichment[field] not in (None, "", 0):
            vitals_out[field] = round(score_vital(field, enrichment[field]), 3)
    bp = enrichment.get("bp")
    if bp:
        vitals_out["bp"] = round(score_bp(bp), 3)
    if vitals_out:
        out["vitals"] = vitals_out

    return out


def confidence_class(score: float) -> str:
    """Gibt eine CSS-Klasse-Schlussfolgerung fuer UI zurueck:
    'cf-high' / 'cf-med' / 'cf-low'. Genutzt direkt im Frontend als
    data-attribute wenn wir das Score mit rausgeben."""
    if score >= 0.9:
        return "cf-high"
    if score >= 0.6:
        return "cf-med"
    return "cf-low"
