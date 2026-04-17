"""Dienstgrad-Whitelist + Fuzzy-Matching fuer SAFIR.

Zweck: Whisper-ASR-Fehler bei selten-benutzten BW-Dienstgraden korrigieren,
ohne das LLM damit zu belasten (das soll das Modell nicht erfinden, was
nicht im Text stand). Nach der Gemma-Extraktion schauen wir ob der
`rank`-String auch wirklich ein zulaessiger BW-Dienstgrad ist, und wenn
nicht, fuzzy-matchen gegen die Liste.

Beispiel: Whisper hoert "Oberstabselwebel" -> Gemma extrahiert exakt das
-> _normalize_rank() findet "Oberstabsfeldwebel" mit Distance 2, ratio
~0.89 -> ersetzt.

Kosten: ~0.5 ms pro Patient (difflib ist pure-Python, keine LLM-Calls,
keine externen Deps). Bei 10 Patienten pro Diktat also ~5 ms total —
komplett vernachlaessigbar.

Liste ist nicht exhaustiv (~100 Dienstgrade insgesamt in der BW inkl.
aller Truppengattungen und Reserveoffizier-Varianten). Sanitaetsdienst-
spezifische Grade sind priorisiert, da SAFIR primaer im San-Kontext
laeuft.
"""
from __future__ import annotations

from difflib import SequenceMatcher, get_close_matches
from typing import Iterable


# ---------------------------------------------------------------------------
# Dienstgrad-Liste
# ---------------------------------------------------------------------------
# Aufbau: haeufigste Formen zuerst, mit weiblicher Form direkt dahinter.
# Das LLM bekommt den String 1:1 zurueck, also ist die Schreibweise hier
# die, die im Patient-Record steht.

MANNSCHAFTEN = [
    "Soldat", "Soldatin",
    # Truppengattungs-Mannschaften (Heer)
    "Schuetze", "Jaeger", "Grenadier", "Panzerschuetze", "Panzergrenadier",
    "Kanonier", "Pionier", "Funker", "Kraftfahrer", "Sanitaetssoldat",
    "Sanitaetssoldatin",
    # Marine-Mannschaften
    "Matrose", "Matrosin", "Sanitaetsmatrose",
    # Luftwaffe-Mannschaften
    "Flieger", "Fliegerin", "Sanitaetsflieger",
    # Aufstiegsstufen
    "Gefreiter", "Gefreite",
    "Obergefreiter", "Obergefreite",
    "Hauptgefreiter", "Hauptgefreite",
    "Stabsgefreiter", "Stabsgefreite",
    "Oberstabsgefreiter", "Oberstabsgefreite",
]

UNTEROFFIZIERE_OHNE_PORTEPEE = [
    "Unteroffizier", "Unteroffizierin",
    "Stabsunteroffizier", "Stabsunteroffizierin",
    # Marine-Entsprechung
    "Maat", "Maatin",
    "Obermaat", "Obermaatin",
]

UNTEROFFIZIERE_MIT_PORTEPEE = [
    # Heer / Luftwaffe
    "Feldwebel", "Feldwebelin",
    "Oberfeldwebel", "Oberfeldwebelin",
    "Hauptfeldwebel", "Hauptfeldwebelin",
    "Stabsfeldwebel", "Stabsfeldwebelin",
    "Oberstabsfeldwebel", "Oberstabsfeldwebelin",
    # Marine
    "Bootsmann", "Bootsfrau",
    "Oberbootsmann", "Oberbootsfrau",
    "Hauptbootsmann", "Hauptbootsfrau",
    "Stabsbootsmann", "Stabsbootsfrau",
    "Oberstabsbootsmann", "Oberstabsbootsfrau",
]

LEUTNANTE = [
    "Leutnant", "Leutnantin",
    "Oberleutnant", "Oberleutnantin",
    "Hauptmann", "Hauptfrau",
    # Marine
    "Leutnant zur See", "Leutnantin zur See",
    "Oberleutnant zur See", "Oberleutnantin zur See",
    "Kapitaenleutnant", "Kapitaenleutnantin",
]

STABSOFFIZIERE = [
    "Major", "Majorin",
    "Oberstleutnant", "Oberstleutnantin",
    "Oberst", "Oberstin",
    # Marine
    "Korvettenkapitaen", "Korvettenkapitaenin",
    "Fregattenkapitaen", "Fregattenkapitaenin",
    "Kapitaen zur See", "Kapitaenin zur See",
]

GENERALE = [
    "Brigadegeneral", "Brigadegeneralin",
    "Generalmajor", "Generalmajorin",
    "Generalleutnant", "Generalleutnantin",
    "General", "Generalin",
    # Marine
    "Flottillenadmiral", "Flottillenadmiralin",
    "Konteradmiral", "Konteradmiralin",
    "Vizeadmiral", "Vizeadmiralin",
    "Admiral", "Admiralin",
]

# Sanitaetsoffiziere — parallel zu Hauptmann/Major/Oberstleutnant/Oberst
SANITAETSOFFIZIERE = [
    "Stabsarzt", "Stabsaerztin",
    "Oberstabsarzt", "Oberstabsaerztin",
    "Oberfeldarzt", "Oberfeldaerztin",
    "Oberstarzt", "Oberstaerztin",
    "Generalarzt", "Generalaerztin",
    "Oberstabsarzt", "Oberstabsaerztin",
    "Admiralarzt",
    "Generalstabsarzt", "Generalstabsaerztin",
    # Veterinaere
    "Stabsveterinaer", "Stabsveterinaerin",
    "Oberstabsveterinaer", "Oberstabsveterinaerin",
    "Oberfeldveterinaer", "Oberfeldveterinaerin",
    "Oberstveterinaer", "Oberstveterinaerin",
    "Generalveterinaer",
    # Apotheker
    "Stabsapotheker", "Stabsapothekerin",
    "Oberstabsapotheker", "Oberstabsapothekerin",
    "Oberfeldapotheker", "Oberfeldapothekerin",
    "Oberstapotheker", "Oberstapothekerin",
]


ALL_RANKS: list[str] = (
    MANNSCHAFTEN
    + UNTEROFFIZIERE_OHNE_PORTEPEE
    + UNTEROFFIZIERE_MIT_PORTEPEE
    + LEUTNANTE
    + STABSOFFIZIERE
    + GENERALE
    + SANITAETSOFFIZIERE
)


# ---------------------------------------------------------------------------
# Aliases / Abkuerzungen die Whisper/Nutzer manchmal produzieren
# ---------------------------------------------------------------------------
# Keys sind normalisiert (lowercase, ohne Umlaute). Values sind die Volltitel
# wie sie in ALL_RANKS stehen.

RANK_ALIASES: dict[str, str] = {
    # Sanitaetsdienst-Kurzformen
    "ofa": "Oberfeldarzt",
    "ostarzt": "Oberstarzt",
    "stabsarzt": "Stabsarzt",
    "oa": "Oberarzt",       # nicht in Liste, bleibt als Alias
    # Unteroffizier-Kurzformen
    "uffz": "Unteroffizier",
    "stuffz": "Stabsunteroffizier",
    "fw": "Feldwebel",
    "ofw": "Oberfeldwebel",
    "hfw": "Hauptfeldwebel",
    "stfw": "Stabsfeldwebel",
    "ostfw": "Oberstabsfeldwebel",
    # Mannschaften-Kurzformen
    "gefr": "Gefreiter",
    "ogefr": "Obergefreiter",
    "hgefr": "Hauptgefreiter",
    "sgefr": "Stabsgefreiter",
    "ostgefr": "Oberstabsgefreiter",
    # Offizier-Kurzformen
    "lt": "Leutnant",
    "olt": "Oberleutnant",
    "hptm": "Hauptmann",
    "maj": "Major",
    "oltl": "Oberstleutnant",
    "obst": "Oberst",
    # Typische Whisper-Verhaspeler (empirisch gesammelt)
    "oberstabselwebel": "Oberstabsfeldwebel",   # Kern-Problem: "feld" verschluckt
    "oberstabselwebelin": "Oberstabsfeldwebelin",
    "stabselwebel": "Stabsfeldwebel",
    "hauptselwebel": "Hauptfeldwebel",
    "oberselwebel": "Oberfeldwebel",
    "selwebel": "Feldwebel",
}


# ---------------------------------------------------------------------------
# Normalisierung
# ---------------------------------------------------------------------------

def _normalize_key(s: str) -> str:
    """Klein, ohne Umlaute, ohne Sonderzeichen — fuer Fuzzy-Vergleich."""
    s = (s or "").strip().lower()
    return (s.replace("ae", "a").replace("oe", "o").replace("ue", "u")
             .replace("ä", "a").replace("ö", "o").replace("ü", "u")
             .replace("ß", "ss").replace(".", "").replace("-", ""))


def normalize_rank(raw: str, min_ratio: float = 0.78) -> tuple[str, float]:
    """Matcht einen extrahierten Dienstgrad gegen die BW-Whitelist.

    Parameters
    ----------
    raw : Der vom LLM extrahierte Dienstgrad-String (z.B. "Oberstabselwebel").
    min_ratio : Minimaler difflib-SequenceMatcher-Ratio fuer Fuzzy-Match.
        0.78 entspricht ~2 Tippfehler in einem 15-Zeichen-Wort.

    Returns
    -------
    (normalized_rank, confidence)
    - Exact-Match oder Alias -> (rank, 1.0)
    - Fuzzy-Match >= min_ratio -> (rank, ratio)
    - Kein Match -> (raw, 0.0) (Original bleibt, falls der User einen
      Dienstgrad nennt der nicht in unserer Liste steht — z.B.
      Spezialdienstgrade oder falsche Transkription die wir nicht
      automatisch korrigieren koennen)
    """
    raw = (raw or "").strip()
    if not raw:
        return ("", 1.0)

    # 1. Exact Match (case-insensitive, Umlaut-normalisiert)
    key = _normalize_key(raw)
    for rank in ALL_RANKS:
        if _normalize_key(rank) == key:
            return (rank, 1.0)

    # 2. Alias (typische Whisper-Fehler, Kurzformen)
    if key in RANK_ALIASES:
        return (RANK_ALIASES[key], 1.0)

    # 3. Fuzzy-Match — der SequenceMatcher.ratio() ueber die normalisierten
    # Keys ist robust gegen Umlaut- und Gross-/Kleinschreibungs-Unterschiede.
    best_rank = ""
    best_ratio = 0.0
    for rank in ALL_RANKS:
        r = SequenceMatcher(None, key, _normalize_key(rank)).ratio()
        if r > best_ratio:
            best_ratio = r
            best_rank = rank

    if best_ratio >= min_ratio:
        return (best_rank, round(best_ratio, 3))

    # Kein ueberzeugender Match — Original behalten, Unsicherheit signalisieren
    return (raw, 0.0)


def is_known_rank(raw: str) -> bool:
    """Schnelle Ja/Nein-Abfrage ob ein Dienstgrad in der Whitelist steht."""
    if not raw:
        return False
    key = _normalize_key(raw)
    if key in RANK_ALIASES:
        return True
    return any(_normalize_key(r) == key for r in ALL_RANKS)
