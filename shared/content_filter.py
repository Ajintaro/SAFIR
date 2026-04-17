"""Content-Guardrails fuer SAFIR (Messe-Hardening Phase A3).

Zweck: Vor dem LLM-Call schnell pruefen ob das Transkript ueberhaupt
medizinischen Inhalt enthaelt. Falls nicht -> Soft-Warning an den User
("Transkript scheint keinen medizinischen Inhalt zu enthalten, trotzdem
analysieren?") statt blind ein leeres Patient-Record anzulegen.

Hintergrund: Messe-Besucher sagen "Ich gehe einkaufen, die Sonne scheint"
oder lassen das Mikro offen waehrend sie diskutieren. Gemma extrahiert
dann entweder nichts (leerer Patient) oder halluziniert. Beides sieht
nach Bug aus. Mit dem Soft-Filter bekommt der User stattdessen einen
hilfreichen Dialog, entweder abbrechen oder forciert weitermachen.

Implementierung: Keyword-Dichte gegen eine kuratierte medizinisch-
militaerische Begriffs-Liste. Pure Python, ~0.5 ms pro Transkript,
keine externen Deps.

Absichtlich NICHT als harter Block: der User koennte trotzdem Recht
haben (z.B. sagt er "Patient ist ansprechbar" — das ist medizinisch,
auch wenn nur ein Keyword trifft). Der Dialog laesst die Entscheidung
beim Menschen.
"""
from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# Medizinisch-militaerische Keyword-Whitelist
# ---------------------------------------------------------------------------
# Sortiert nach Themen, alle in Kleinbuchstaben. Der Match erfolgt
# case-insensitive per Wortgrenzen-Regex, damit "Patient" nicht in
# "patientenorientiert" matched (was auch ok waere, aber so ist es
# praeziser).

MEDICAL_KEYWORDS: tuple[str, ...] = (
    # Patienten-Begriffe
    "patient", "patientin", "patienten",
    "verwundete", "verwundeter", "verwundetem", "verwundeten",
    "verletzte", "verletzter", "verletztem", "verletzten", "verletzung",
    "soldat", "soldatin", "soldaten", "zivilist", "zivilistin", "zivilisten",
    "opfer", "betroffene", "betroffener",

    # Verletzungs-Begriffe (Mechanismus)
    "schuss", "schussverletzung", "schusswunde",
    "splitter", "splitterverletzung", "splitterwunde",
    "platzwunde", "schnittwunde", "stichwunde", "bisswunde",
    "prellung", "quetschung", "distorsion", "luxation",
    "fraktur", "bruch", "knochenbruch",
    "verbrennung", "verbrannt", "verbruehung",
    "amputation", "amputiert",
    "blutung", "blutverlust", "blutet",
    "haematom", "hämatom", "blauer fleck",
    "ied", "mine", "explosion", "druckwelle",

    # Vitals & Zustand
    "puls", "herzfrequenz", "herzrhythmus", "herzfehler", "tachykard", "bradykard",
    "blutdruck", "hypotonie", "hypertonie",
    "atmung", "atemfrequenz", "luftnot", "dyspnoe", "apnoe",
    "sauerstoff", "spo2", "saettigung", "sättigung",
    "temperatur", "fieber", "hypotherm",
    "glasgow", "gcs", "bewusstsein", "bewusstlos", "ohnmaechtig", "ohnmächtig",
    "orientiert", "ansprechbar",
    "reanimation", "wiederbelebung", "herzdruckmassage",
    "schock", "kreislauf",

    # Behandlung & Materialien
    "beatmung", "intubation", "tubus", "maske",
    "verband", "druckverband", "tourniquet", "abbinden",
    "infusion", "volumenersatz", "kochsalz", "ringer",
    "schmerzmittel", "analgetikum", "morphin", "morphium", "aspirin",
    "adrenalin", "atropin", "fentanyl",
    "wundversorgung", "gipsverband", "schiene",
    "defibrillator", "defi",

    # Triage & Status
    "triage", "stabil", "instabil", "kritisch", "dringend",
    "notfall", "sofort behandlung", "lebensgefahr", "moribund",
    "abwartend", "aufschiebbar",

    # Dienstgrade (Auszug — die haeufigsten im Sanitaetsalltag)
    "gefreiter", "gefreite", "obergefreit", "hauptgefreit", "stabsgefreit",
    "oberstabsgefreit",
    "unteroffizier", "stabsunteroffizier",
    "feldwebel", "oberfeldwebel", "hauptfeldwebel", "stabsfeldwebel",
    "oberstabsfeldwebel",
    "leutnant", "oberleutnant", "hauptmann", "major", "oberst",
    "general", "admiral",
    "stabsarzt", "oberfeldarzt", "oberstabsarzt", "oberstarzt",
    "bat", "sanitaeter", "sanitäter", "notarzt",

    # Anatomie (Koerperregionen)
    "kopf", "schaedel", "schädel", "stirn", "hinterkopf", "gesicht",
    "nacken", "hals", "wirbelsaeule", "wirbel",
    "brust", "brustkorb", "thorax", "rippe", "rippenbruch",
    "bauch", "abdomen", "leber", "milz", "niere", "darm", "magen",
    "ruecken", "rücken", "becken", "huefte", "hüfte",
    "arm", "oberarm", "unterarm", "ellbogen", "ellenbogen",
    "hand", "finger", "schulter", "schulterblatt",
    "bein", "oberschenkel", "unterschenkel", "knie", "sprunggelenk",
    "fuss", "fuß", "zehe", "zehen",
    "auge", "augen", "ohr", "ohren", "mund", "kiefer", "zahn", "zaehne", "zähne",

    # Patient-Start-Signale (aus BOUNDARY_PROMPT)
    "erster patient", "zweiter patient", "dritter patient",
    "naechster patient", "nächster patient",
    "naechste verwundete", "nächste verwundete",
    "weiter mit", "als naechstes", "als nächstes",

    # Fach-Fachsprache
    "tccc", "medevac", "casevac", "9liner", "neun liner", "9-liner",
    "rettungskette", "role1", "role 1", "rettungsstation", "einsatzlazarett",
    "erstversorgung", "uebergabe", "übergabe", "handover",

    # Zeichen dass jemand diktiert (aber nicht doppelt zaehlen mit Start-Signalen)
    "untersuche", "untersucht", "behandle", "behandelt",
    "diagnose", "diagnostiziere", "verletzt sich", "verletzte sich",
)


# Word-Boundary-Regex-Pattern fuer schnellen Multi-Keyword-Check.
# Die Unterstuetzung fuer Umlaute macht das Pattern etwas komplex — wir
# duplizieren jeden Keyword zu ae/oe/ue + ä/ö/ü damit beide Schreibungen
# matchen (Whisper produziert je nach Modell-Variante beides).
def _build_pattern() -> re.Pattern:
    variants: set[str] = set()
    for kw in MEDICAL_KEYWORDS:
        variants.add(kw)
        # Umlaut <-> ae-Schreibung
        ae_form = (kw.replace("ä", "ae").replace("ö", "oe")
                     .replace("ü", "ue").replace("ß", "ss"))
        ua_form = (kw.replace("ae", "ä").replace("oe", "ö").replace("ue", "ü"))
        if ae_form != kw:
            variants.add(ae_form)
        if ua_form != kw:
            variants.add(ua_form)
    # Sortiert nach Laenge absteigend damit "oberstabsfeldwebel" vor
    # "feldwebel" steht und nicht doppelt zaehlt.
    sorted_vars = sorted(variants, key=len, reverse=True)
    # Wortgrenzen (\b) nur wenn Keyword nicht mit Sonderzeichen anfaengt
    escaped = [re.escape(v) for v in sorted_vars]
    pattern = r"\b(?:" + "|".join(escaped) + r")\b"
    return re.compile(pattern, re.IGNORECASE)


_PATTERN = _build_pattern()


# ---------------------------------------------------------------------------
# Haupt-API
# ---------------------------------------------------------------------------

# Schwellwert: so viele distinkte Keyword-Treffer sind notwendig um ein
# Transkript als "medizinisch" zu klassifizieren. Bei 2 sind die wenigsten
# false-positives zu erwarten (ein zufaelliges "patient" in "Patient Null"-
# Gespraech reicht nicht).
MIN_KEYWORDS_FOR_MEDICAL = 2


def is_medical_transcript(text: str) -> tuple[bool, int, list[str]]:
    """Prueft ob das Transkript medizinischen Inhalt enthaelt.

    Parameters
    ----------
    text : Transkript-String

    Returns
    -------
    (is_medical, num_unique_matches, matched_keywords_preview)
    - is_medical: True wenn >= MIN_KEYWORDS_FOR_MEDICAL distinkte Keywords
      gefunden wurden
    - num_unique_matches: Anzahl distinkter Keyword-Treffer (nicht Gesamt-
      Vorkommen; "Puls 80. Puls 90." zaehlt nur 1-mal fuer "puls")
    - matched_keywords_preview: bis zu 5 der gefundenen Keywords zur
      Anzeige im Frontend ("Gefunden: puls, verband, hauptmann")
    """
    if not text or not text.strip():
        return (False, 0, [])
    matches = _PATTERN.findall(text)
    if not matches:
        return (False, 0, [])
    unique = list({m.lower() for m in matches})
    is_med = len(unique) >= MIN_KEYWORDS_FOR_MEDICAL
    return (is_med, len(unique), unique[:5])


def short_reason(text: str) -> str:
    """Gibt eine menschenlesbare Kurz-Begruendung zurueck, warum das
    Transkript als 'nicht medizinisch' eingestuft wurde. Fuer Frontend-
    Dialog + Log-Ausgabe."""
    is_med, count, _ = is_medical_transcript(text)
    if is_med:
        return "ist medizinisch"
    if count == 0:
        return "enthaelt keine medizinischen Fachbegriffe"
    return f"enthaelt nur {count} medizinischen Fachbegriff — unsicher"
