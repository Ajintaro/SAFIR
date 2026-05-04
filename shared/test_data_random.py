"""Randomisierungs-Engine fuer Demo-Daten.

Wird von app.py beim Generieren von Test-Patienten und Pending-Diktaten
verwendet. Ziel: bei jedem Klick auf 'Demo-Szenario laden' bekommt der
Messebesucher andere Namen, IDs, Zeiten, Vitals — die Struktur und die
Logik der Demo bleiben identisch, aber der Eindruck variiert (kein 'da
ist wieder der gleiche SU Stefan Becker').

Reine Standardbibliothek, kein Faker / keine externen Dependencies —
laeuft offline und kostet nichts an Speicher.

Konventionen:
- Deterministische Seeds NICHT genutzt (jeder Aufruf liefert echte Random-
  daten). Wenn Reproducierbarkeit gewuenscht ist, kann der Aufrufer
  random.seed() vorher setzen.
- Vitals-Plausibilitaet: pulse/bp/spo2/resp_rate sind innerhalb der von
  shared/vitals.py akzeptierten Range (sonst greift der Vitals-Plausi-
  Check und filtert die Demo-Daten als 'auffaellig').
"""
from __future__ import annotations
import random
from datetime import datetime, timedelta
from typing import Optional

from shared.bundeswehr_ranks import (
    MANNSCHAFTEN,
    UNTEROFFIZIERE_OHNE_PORTEPEE,
    UNTEROFFIZIERE_MIT_PORTEPEE,
    LEUTNANTE,
    SANITAETSOFFIZIERE,
)


# ---------------------------------------------------------------------------
# Namens-Pools (DEU). Bewusst breit, damit auch nach 20 Klicks noch Varianz
# da ist. Mix aus haeufigen und mittelhaeufigen Namen, keine Sonderzeichen
# wie Umlaute (sonst muessten alle Konsumenten diese korrekt rendern).
# ---------------------------------------------------------------------------
FIRST_NAMES_M = [
    "Daniel", "Lukas", "Niklas", "Felix", "Tobias", "Jonas", "Sebastian",
    "Christian", "Stefan", "Markus", "Jan", "Philipp", "Andreas", "Florian",
    "Maximilian", "Thomas", "Patrick", "Alexander", "Matthias", "Benjamin",
    "Christoph", "David", "Dennis", "Fabian", "Julian", "Kevin", "Manuel",
    "Michael", "Oliver", "Pascal", "Sven", "Timo", "Tim", "Sascha", "Marvin",
]
FIRST_NAMES_F = [
    "Anna", "Sarah", "Laura", "Lisa", "Julia", "Katharina", "Lena",
    "Marie", "Hannah", "Vanessa", "Jessica", "Melanie", "Stefanie",
    "Sandra", "Kerstin", "Nina", "Tanja", "Christina", "Janine", "Maren",
    "Carolin", "Franziska", "Sina", "Mareike", "Verena", "Sophie",
]
LAST_NAMES = [
    "Mueller", "Schmidt", "Schneider", "Fischer", "Weber", "Becker", "Koch",
    "Bauer", "Richter", "Klein", "Wolf", "Schulz", "Vogel", "Krueger",
    "Hofmann", "Hartmann", "Werner", "Schmitt", "Lange", "Krause",
    "Meier", "Lehmann", "Schmid", "Schulze", "Maier", "Koehler", "Herrmann",
    "Walter", "Mayer", "Huber", "Kaiser", "Fuchs", "Peters", "Lang",
    "Scholz", "Moeller", "Weiss", "Jung", "Hahn", "Schubert", "Vogt",
    "Friedrich", "Keller", "Guenther", "Frank", "Berger", "Winkler",
    "Roth", "Beck", "Lorenz", "Baumann", "Franke", "Albrecht", "Simon",
]

# Einheiten — repraesentativ fuer Bundeswehr-Truppenteile, fiktive Nummern
UNITS = [
    "1./Sanitaetsregiment 1, Berlin",
    "2./Sanitaetsregiment 2, Rennerod",
    "3./Sanitaetsregiment 3, Doelitz",
    "1./Panzergrenadierbataillon 122, Oberviechtach",
    "3./Panzergrenadierbataillon 391, Bad Salzungen",
    "2./Jaegerbataillon 291, Illkirch-Graffenstaden",
    "1./Fallschirmjaegerregiment 26, Zweibruecken",
    "Stab/Fallschirmjaegerregiment 31, Seedorf",
    "2./Gebirgsjaegerbataillon 232, Bischofswiesen",
    "1./Panzerbataillon 393, Bad Frankenhausen",
    "3./Panzerlehrbataillon 93, Munster",
    "2./Aufklaerungsbataillon 13, Goerlitz",
    "1./Pionierbataillon 901, Havelberg",
]

# NATO-Phonetic-inspirierte Pickup-Site-Namen (im Demo-Szenario A1)
PICKUP_SITE_NAMES = [
    "Falcon", "Eagle", "Hawk", "Raven", "Lion", "Tiger", "Bear",
    "Wolf", "Hammer", "Anvil", "Storm", "Thunder", "Phoenix", "Cobra",
    "Viper", "Jaguar", "Panther", "Stallion", "Bronco", "Dagger",
]

# Callsign-Bausteine (Marble 37, Cobra 12, ...)
CALLSIGN_WORDS = [
    "Marble", "Cobra", "Viper", "Hammer", "Eagle", "Raven", "Falcon",
    "Saber", "Spear", "Lance", "Shield", "Wolf", "Bear", "Tiger",
    "Phoenix", "Storm", "Iron", "Steel", "Ghost", "Reaper",
]

# Operators (Sanitaeter / Bediener-Namen fuer 'created_by')
OPERATORS = [
    "OFA Hugendubel", "OF Mueller", "Sanitaetsfeldwebel Schneider",
    "Stabsfeldwebel Krause", "Hauptfeldwebel Becker", "Oberfeldwebel Vogt",
    "Sanitaetsstabsfeldwebel Lehmann", "Oberstabsarzt Dr. Hartmann",
    "Stabsarzt Dr. Werner", "Oberfeldarzt Dr. Schubert",
]


def random_first_name(sex: str = "m") -> str:
    return random.choice(FIRST_NAMES_F if sex == "w" else FIRST_NAMES_M)


def random_last_name() -> str:
    return random.choice(LAST_NAMES)


def random_full_name(sex: Optional[str] = None) -> tuple[str, str]:
    """Liefert (sex, fullname) — sex ist 'm' oder 'w', fullname 'Vorname Nachname'."""
    if sex is None:
        sex = random.choice(["m", "m", "m", "w"])  # 75/25 m/w (BW-realistisch)
    return sex, f"{random_first_name(sex)} {random_last_name()}"


def random_rank(category: str = "any", sex: str = "m") -> str:
    """Liefert einen plausiblen BW-Dienstgrad.
    category: 'mannschaft', 'uffz', 'offizier', 'sani', 'any' (Default-Mix).
    sex: 'm' filtert die weiblichen '-in'-Endungen aus, 'w' nimmt nur diese.
    """
    pools = {
        "mannschaft": [MANNSCHAFTEN],
        "uffz":       [UNTEROFFIZIERE_OHNE_PORTEPEE, UNTEROFFIZIERE_MIT_PORTEPEE],
        "offizier":   [LEUTNANTE],
        "sani":       [SANITAETSOFFIZIERE],
        "any":        [MANNSCHAFTEN, UNTEROFFIZIERE_OHNE_PORTEPEE,
                       UNTEROFFIZIERE_MIT_PORTEPEE, LEUTNANTE],
    }
    pool = random.choice(pools.get(category, pools["any"]))
    # BW-Dienstgrad-Liste enthaelt fast immer Paare maennlich/weiblich:
    #   Soldat/Soldatin, Gefreiter/Gefreite, Hauptfeldwebel/Hauptfeldwebelin,
    #   Bootsmann/Bootsfrau, Oberleutnant zur See / Oberleutnantin zur See.
    # Heuristik: wenn ein Wort X existiert UND X+'r' (oder X-Variante) auch,
    # ist X die weibliche Form (Gefreite vs. Gefreiter). Plus explizite
    # Suffix-Marker fuer 'Soldatin', 'Bootsfrau' etc.
    pool_set = set(pool)
    fem_suffix_markers = ("inin", "soldatin", "matrosin", "fliegerin",
                          "offizierin", "feldwebelin", "leutnantin",
                          "kapitaenleutnantin", "maatin", "bootsfrau", "hauptfrau")
    def _is_female(r: str) -> bool:
        rl = r.lower()
        if any(m in rl for m in fem_suffix_markers):
            return True
        # Paar-Heuristik: 'Gefreite' weiblich wenn 'Gefreiter' im Pool
        if r.endswith("e") and (r + "r") in pool_set:
            return True
        # Mehrwortrange wie 'Oberleutnantin zur See' decken die Marker schon ab
        return False
    if sex == "m":
        candidates = [r for r in pool if not _is_female(r)]
    elif sex == "w":
        candidates_f = [r for r in pool if _is_female(r)]
        candidates = candidates_f if candidates_f else pool
    else:
        candidates = pool
    return random.choice(candidates if candidates else pool)


def random_service_id(prefix: str = "DEU") -> str:
    """NATO-Service-Number-Stil: DEU-482917. 6 Stellen, vorne kein 0."""
    n = random.randint(100000, 999999)
    return f"{prefix}-{n}"


def random_dob(min_age: int = 19, max_age: int = 45) -> datetime:
    """Geburtsdatum eines aktiven Soldaten. Default 19-45 Jahre."""
    today = datetime.now()
    age = random.randint(min_age, max_age)
    base = today.replace(year=today.year - age)
    # zufaelliger Tag im Jahr (vermeidet immer-1.-Januar-Bias)
    day_offset = random.randint(0, 364)
    return base - timedelta(days=day_offset)


def random_unit() -> str:
    return random.choice(UNITS)


def random_operator() -> str:
    return random.choice(OPERATORS)


def random_pickup_site() -> str:
    return random.choice(PICKUP_SITE_NAMES)


def random_callsign() -> str:
    """'Marble 37' — Wort + zweistellige Zahl."""
    return f"{random.choice(CALLSIGN_WORDS)} {random.randint(10, 99)}"


def random_grid_mgrs() -> str:
    """MGRS-Stil 'GZD GSQID Easting Northing'. Realistische deutsche Region:
    Grid Zone 32U oder 33U (Mitteleuropa). 100km-Square 2-Letter Code,
    Easting/Northing als 5-Stellen.

    Beispiel: '32U NB 43826 91754'
    """
    gzd = random.choice(["32U", "33U"])
    # 100km-Square Codes die in Deutschland real vorkommen (Auswahl):
    grid_squares = ["NA", "NB", "NC", "ND", "PA", "PB", "PC", "PD",
                    "MV", "NV", "NU", "MT", "NT"]
    sq = random.choice(grid_squares)
    east = random.randint(10000, 99999)
    north = random.randint(10000, 99999)
    return f"{gzd} {sq} {east} {north}"


def random_blood_group() -> str:
    """A/B/AB/0 mit realistischen Anteilen (DEU-Bevoelkerung)."""
    pool = (["A+"] * 37 + ["A-"] * 6 + ["0+"] * 35 + ["0-"] * 6 +
            ["B+"] * 9 + ["B-"] * 2 + ["AB+"] * 4 + ["AB-"] * 1)
    return random.choice(pool)


def random_zulu_time(base: Optional[datetime] = None,
                     offset_min: int = 0,
                     drift_min: int = 0) -> tuple[datetime, str]:
    """Liefert (datetime, 'HHMM' Zulu-String).

    base: Ankerzeit (Default = jetzt-2h). offset_min addiert auf base.
    drift_min: zufaellige Drift +/- (z.B. drift_min=3 -> +/- 3 Min Streuung).
    """
    if base is None:
        base = datetime.utcnow() - timedelta(hours=2)
    drift = random.randint(-drift_min, drift_min) if drift_min else 0
    t = base + timedelta(minutes=offset_min + drift)
    return t, t.strftime("%H%M")


# ---------------------------------------------------------------------------
# Vitals-Generierung — plausibel fuer 4 Schweregrade
# ---------------------------------------------------------------------------
# Ranges sind so gewaehlt, dass shared/vitals.py die Werte als 'plausibel'
# durchwinkt (kein Penalty). 'critical' liegt am Rand, ist aber medizinisch
# noch korrekt fuer einen Schock-Patienten.
VITALS_RANGES = {
    "stable": {
        "pulse":     (62,  82),
        "bp_sys":    (110, 130),
        "bp_dia":    (70,  85),
        "spo2":      (96,  99),
        "resp_rate": (12,  16),
        "gcs":       (15,  15),
        "pain":      (0,   3),
    },
    "moderate": {
        "pulse":     (95,  115),
        "bp_sys":    (95,  110),
        "bp_dia":    (60,  72),
        "spo2":      (92,  96),
        "resp_rate": (18,  24),
        "gcs":       (14,  15),
        "pain":      (4,   6),
    },
    "severe": {
        "pulse":     (115, 140),
        "bp_sys":    (82,  100),
        "bp_dia":    (52,  68),
        "spo2":      (88,  94),
        "resp_rate": (22,  30),
        "gcs":       (13,  15),
        "pain":      (6,   9),
    },
    "critical": {
        "pulse":     (130, 155),
        "bp_sys":    (70,  92),
        "bp_dia":    (45,  60),
        "spo2":      (82,  90),
        "resp_rate": (28,  36),
        "gcs":       (10,  14),
        "pain":      (8,   10),
    },
}


def random_vitals(severity: str = "stable") -> dict:
    """Liefert ein Vitals-Dict mit den Standardfeldern.

    severity: 'stable' / 'moderate' / 'severe' / 'critical'.
    Strings statt Ints, weil das Patient-Schema Strings erwartet.
    """
    r = VITALS_RANGES.get(severity, VITALS_RANGES["stable"])
    pulse = random.randint(*r["pulse"])
    sys = random.randint(*r["bp_sys"])
    dia = random.randint(*r["bp_dia"])
    return {
        "pulse":     str(pulse),
        "bp":        f"{sys}/{dia}",
        "spo2":      str(random.randint(*r["spo2"])),
        "resp_rate": str(random.randint(*r["resp_rate"])),
        "gcs":       str(random.randint(*r["gcs"])),
        "pain":      str(random.randint(*r["pain"])),
    }


# ---------------------------------------------------------------------------
# Verletzungs-Pools je Schweregrad. Wird fuer Mass-Cas-Szenario genutzt
# damit die Verletzungs-Liste pro Patient variiert.
# ---------------------------------------------------------------------------
INJURIES_BY_SEVERITY = {
    "stable": [
        ["Schuerfwunden Knie", "Prellung Schulter"],
        ["Hautabschuerfungen Unterarm"],
        ["Verstauchung Fussgelenk", "Hautriss Stirn"],
    ],
    "moderate": [
        ["Splitterverletzung Oberarm", "moderate Blutung"],
        ["Geschlossene Fraktur Unterarm"],
        ["Schussstreifung Oberschenkel", "stabilisiert"],
        ["Verbrennung Hand 2. Grades"],
    ],
    "severe": [
        ["Schussverletzung Oberschenkel", "starke Blutung kontrolliert"],
        ["Splitterverletzung Thorax", "Pneumothorax"],
        ["Offene Fraktur Unterschenkel", "Tourniquet angelegt"],
        ["Bauchschuss", "innere Blutung vermutet"],
    ],
    "critical": [
        ["Multiple Schussverletzungen", "Schockzustand"],
        ["Schaedelhirntrauma offen", "Bewusstlosigkeit"],
        ["Polytrauma", "Massiver Blutverlust"],
        ["Penetrierende Thoraxverletzung", "Kreislaufversagen"],
    ],
}


def random_injuries(severity: str = "moderate") -> list[str]:
    return random.choice(INJURIES_BY_SEVERITY.get(severity, INJURIES_BY_SEVERITY["moderate"]))


# ---------------------------------------------------------------------------
# Mechanismen / Verletzungs-Ursachen (fuer FMC: 'Roadside IED strike ...')
# ---------------------------------------------------------------------------
INJURY_MECHANISMS_EN = [
    "Roadside IED strike during dismounted patrol",
    "Small-arms fire engagement during convoy escort",
    "Mortar fragmentation impact at forward observation post",
    "RPG strike on dismounted element",
    "Building collapse during urban operations",
    "Vehicle rollover during night movement",
    "Sniper engagement at vehicle checkpoint",
    "Booby trap activation during route clearance",
]
INJURY_MECHANISMS_DE = [
    "IED-Detonation am Strassenrand bei abgesessener Patrouille",
    "Beschuss durch leichte Waffen bei Konvoi-Sicherung",
    "Splittertreffer durch Moerserbeschuss am vorgeschobenen Beobachtungsposten",
    "Treffer durch Panzerfaust auf abgesessenes Element",
    "Gebaeudeeinsturz bei Operation im urbanen Gelaende",
    "Fahrzeug-Ueberschlag bei Nachtmarsch",
]


def random_mechanism(lang: str = "en") -> str:
    return random.choice(INJURY_MECHANISMS_EN if lang == "en" else INJURY_MECHANISMS_DE)


# ---------------------------------------------------------------------------
# Hauptverletzungen fuer FMC (fuer 'Main Injury') — auf Englisch.
# Mit anatomischer Lokalisation, sodass die Body-Diagramm-Anzeige spaeter
# die Region markieren kann.
# ---------------------------------------------------------------------------
FMC_MAIN_INJURIES_EN = [
    {"text": "Fragmentation wound to right upper thigh with severe bleeding, now controlled",
     "region": "thigh_r"},
    {"text": "Gunshot wound to left upper arm, exit wound present, hemorrhage controlled",
     "region": "upper_arm_l"},
    {"text": "Penetrating wound to left lower abdomen, suspected internal bleeding",
     "region": "abdomen_l"},
    {"text": "Open fracture of right tibia with significant soft tissue damage",
     "region": "lower_leg_r"},
    {"text": "Shrapnel injury to right shoulder, multiple fragments retained",
     "region": "shoulder_r"},
    {"text": "Blast injury to left chest wall, no open pneumothorax",
     "region": "chest_l"},
    {"text": "Gunshot wound to right flank, exit through lower back",
     "region": "flank_r"},
]
FMC_ADDITIONAL_INJURIES_EN = [
    "Suspected closed fracture of left forearm",
    "Multiple superficial fragmentation wounds to the back",
    "Mild concussion, no loss of consciousness",
    "Second-degree burns to right hand and forearm, approximately five percent BSA",
    "Suspected hairline fracture of right clavicle",
    "Sprained right ankle from blast displacement",
    "Lacerations to scalp, hemostasis achieved",
]


def random_fmc_main_injury() -> dict:
    return random.choice(FMC_MAIN_INJURIES_EN)


def random_fmc_additional_injury() -> str:
    return random.choice(FMC_ADDITIONAL_INJURIES_EN)


# ---------------------------------------------------------------------------
# Recorder (Sani der die FMC ausfuellt)
# ---------------------------------------------------------------------------
RECORDER_NAMES_EN = [
    ("Staff Sergeant", ["Anna Vogel", "Markus Hartmann", "Lisa Schmidt",
                        "Tobias Weber", "Sandra Wolf"]),
    ("Sergeant",       ["Daniel Krause", "Julia Lehmann", "Felix Bauer",
                        "Maren Becker", "Stefan Richter"]),
    ("Master Sergeant", ["Andreas Werner", "Katharina Vogt", "Christian Klein"]),
]


def random_recorder() -> tuple[str, str, str]:
    """Liefert (rank_en, full_name, function_en) fuer Recorder-Block."""
    rank, names = random.choice(RECORDER_NAMES_EN)
    name = random.choice(names)
    function = random.choice(["Combat Medic", "Senior Combat Medic",
                              "Platoon Medic", "Combat Lifesaver"])
    return rank, name, function


# ---------------------------------------------------------------------------
# Phonetisches Buchstabieren (Uniform November Bravo ...) fuer 9-Liner-EN
# ---------------------------------------------------------------------------
PHONETIC = {
    "A": "Alpha", "B": "Bravo", "C": "Charlie", "D": "Delta", "E": "Echo",
    "F": "Foxtrot", "G": "Golf", "H": "Hotel", "I": "India", "J": "Juliett",
    "K": "Kilo", "L": "Lima", "M": "Mike", "N": "November", "O": "Oscar",
    "P": "Papa", "Q": "Quebec", "R": "Romeo", "S": "Sierra", "T": "Tango",
    "U": "Uniform", "V": "Victor", "W": "Whiskey", "X": "X-ray", "Y": "Yankee", "Z": "Zulu",
}


def _spell_phonetic(s: str) -> str:
    return " ".join(PHONETIC.get(c.upper(), c) for c in s if c.strip())


# ---------------------------------------------------------------------------
# 9-Liner MEDEVAC English Renderer (gemaess Anhang A)
# ---------------------------------------------------------------------------
def render_nine_liner_en() -> tuple[str, dict]:
    """Liefert (transcript_text, fields_dict) fuer einen vollstaendig
    randomisierten englischen MEDEVAC 9-Liner.

    Struktur des Textes folgt 1:1 dem von Jannik gelieferten Anhang-A-Format
    (Line 1 .. Line 9 Reihenfolge). Felder im Dict sind die SAFIR-Internal-
    Repraesentation, die spaeter fuer die Anzeige genutzt wird (analog zum
    bestehenden patient.nine_liner Schema).
    """
    mgrs = random_grid_mgrs()
    # Einzelne Bestandteile fuer phonetisches Buchstabieren rausziehen
    parts = mgrs.split()  # ['32U', 'NB', '43826', '91754']
    gzd = parts[0]; sq = parts[1]; east = parts[2]; north = parts[3]
    mgrs_spelled = (
        f"grid {gzd[0]} {gzd[1]} {PHONETIC[gzd[2]]} "
        f"{PHONETIC[sq[0]]} {PHONETIC[sq[1]]} "
        f"{east} {north}"
    )

    pickup_name = random_pickup_site()
    callsign = random_callsign()
    med_net = random.randint(1, 9)
    n_patients = random.randint(1, 4)
    precedence = random.choice([
        ("urgent",          "A — URGENT"),
        ("urgent surgical", "B — URGENT SURGICAL"),
        ("priority",        "C — PRIORITY"),
        ("routine",         "D — ROUTINE"),
    ])
    n_litter = random.randint(0, n_patients)
    n_ambul = n_patients - n_litter
    special_eq = random.choice([
        ("none",                       "A — NONE"),
        ("hoist",                      "B — HOIST"),
        ("extraction equipment",       "C — EXTRACTION EQUIPMENT"),
        ("ventilator",                 "D — VENTILATOR"),
    ])
    security = random.choice([
        ("no enemy troops in the area",    "N — NO ENEMY TROOPS IN AREA"),
        ("possible enemy troops in the area", "P — POSSIBLE ENEMY TROOPS IN AREA"),
        ("enemy troops in the area, approach with caution", "E — ENEMY TROOPS IN AREA, APPROACH WITH CAUTION"),
    ])
    marking = random.choice([
        ("panel",            "A — PANEL"),
        ("pyrotechnic signal", "B — PYROTECHNIC SIGNAL"),
        ("smoke",            "C — SMOKE SIGNAL"),
        ("none",             "D — NONE"),
        ("other",            "E — OTHER"),
    ])
    nationality = random.choice([
        ("US military",     "A — US MILITARY"),
        ("US civilian",     "B — US CIVILIAN"),
        ("non-US military", "C — NON-US MILITARY"),
        ("non-US civilian", "D — NON-US CIVILIAN"),
        ("EPW",             "E — EPW"),
    ])
    nbc_choice = random.random()
    if nbc_choice < 0.85:
        nbc = ("no known nuclear, biological, chemical, or CBRN contamination",
               "No known nuclear, biological, chemical, or CBRN contamination.")
    else:
        contam = random.choice(["nuclear", "biological", "chemical"])
        nbc = (f"suspected {contam} contamination",
               f"Suspected {contam.upper()} contamination.")

    nat_detail = "1 x German soldier" if nationality[0] == "non-US military" else \
                 ("1 x US soldier" if nationality[0] == "US military" else "1 x detained personnel")

    transcript = (
        f"Line 1: Pickup location is {mgrs_spelled}. "
        f"Pickup site name {pickup_name}. "
        f"Line 2: Contact {callsign} on Med Net {med_net}. "
        f"Line 3: We have {n_patients} casualt{'y' if n_patients == 1 else 'ies'}. "
        f"Precedence is {precedence[0]}. "
        f"Line 4: {special_eq[0].capitalize()} required. "
        f"Line 5: "
    )
    if n_litter and n_ambul:
        transcript += f"{n_litter} litter, {n_ambul} ambulatory. "
    elif n_litter:
        transcript += f"The casualt{'y is a' if n_litter == 1 else 'ies are'} litter patient{'s' if n_litter > 1 else ''}. "
    else:
        transcript += f"All ambulatory. "
    transcript += (
        f"Line 6: {security[0].capitalize()}. "
        f"Line 7: Pickup site will be marked by {marking[0]}. "
        f"{'Smoke color will be confirmed on contact. ' if marking[0] == 'smoke' else ''}"
        f"Line 8: The casualty is {nationality[0]}. "
        f"Line 9: {nbc[0].capitalize()}. End of request."
    )

    fields = {
        "line1": mgrs,
        "line1_site_name": pickup_name,
        "line2": f"MEDICAL NET {med_net} | CALL SIGN: {callsign.upper()}",
        "line3": f"{precedence[1]}: {n_patients}",
        "line3_breakdown": {
            "urgent":          n_patients if precedence[0] == "urgent" else 0,
            "urgent_surgical": n_patients if precedence[0] == "urgent surgical" else 0,
            "priority":        n_patients if precedence[0] == "priority" else 0,
            "routine":         n_patients if precedence[0] == "routine" else 0,
        },
        "line4": special_eq[1],
        "line5": f"L — LITTER: {n_litter} | A — AMBULATORY: {n_ambul}",
        "line6": security[1],
        "line7": marking[1],
        "line8": f"{nationality[1]}\nDetails: {nat_detail}",
        "line9": nbc[1],
    }
    return transcript, fields


# ---------------------------------------------------------------------------
# NATO Field Medical Card (FMC) Renderer (gemaess Anhang B + AMedP-8.1)
# ---------------------------------------------------------------------------
def _spell_zulu(zulu_str: str) -> str:
    """0724 -> 'zero seven two four'."""
    digit_words = {"0":"zero","1":"one","2":"two","3":"three","4":"four",
                   "5":"five","6":"six","7":"seven","8":"eight","9":"nine"}
    return " ".join(digit_words[c] for c in zulu_str)


def render_fmc_en() -> tuple[str, dict]:
    """Liefert (transcript_text, fmc_dict) fuer eine vollstaendig
    randomisierte englische NATO Field Medical Card.

    fmc_dict-Struktur folgt der Anhang-B-Aufgliederung in Sektionen A-G,
    plus 'main_injury_region' fuer die Body-Diagramm-Anzeige in Etappe 4.
    """
    # Identitaet
    sex, full = random_full_name(sex=random.choices(["m", "w"], weights=[80, 20])[0])
    rank_en_pool = ["Private", "Private First Class", "Lance Corporal", "Corporal",
                    "Sergeant", "Staff Sergeant", "Sergeant First Class",
                    "Lieutenant", "Captain"]
    rank_en = random.choice(rank_en_pool)
    last = full.split()[-1]
    first = full.split()[0]
    sex_label = "Male" if sex == "m" else "Female"
    sex_word = "male" if sex == "m" else "female"
    dob = random_dob(min_age=22, max_age=42)
    dob_label = dob.strftime("%d %b %Y").upper()
    dob_word = dob.strftime("%-d %B %Y") if hasattr(dob, "strftime") else str(dob)
    sn = random_service_id("DEU")
    unit = random_unit()

    # Cause
    inj_date = datetime.utcnow() - timedelta(hours=random.randint(1, 4))
    inj_date_label = inj_date.strftime("%d %b %Y").upper()
    inj_date_word = inj_date.strftime("%-d %B %Y")
    _, t_inj = random_zulu_time(base=inj_date, offset_min=0)
    mechanism = random_mechanism("en")

    # Assessment
    _, t_first = random_zulu_time(base=inj_date, offset_min=random.randint(4, 8))
    main_inj = random_fmc_main_injury()
    additional_inj = random_fmc_additional_injury()
    blood_group = random_blood_group()

    # Vitals (zwei Messungen — t_first und ~20 Min spaeter)
    v1 = random_vitals("severe")
    v2 = random_vitals("moderate")  # Recheck zeigt Verbesserung
    _, t_recheck = random_zulu_time(base=inj_date, offset_min=21 + random.randint(-2, 4))

    # Treatment-Zeitleiste (alles inj_date+offset)
    _, t_tq = random_zulu_time(base=inj_date, offset_min=2)
    _, t_dressing = random_zulu_time(base=inj_date, offset_min=7)
    _, t_iv = random_zulu_time(base=inj_date, offset_min=12)
    _, t_txa = random_zulu_time(base=inj_date, offset_min=14)
    _, t_keta = random_zulu_time(base=inj_date, offset_min=16)
    _, t_ceft = random_zulu_time(base=inj_date, offset_min=18)
    _, t_fluid = random_zulu_time(base=inj_date, offset_min=20)
    _, t_splint = random_zulu_time(base=inj_date, offset_min=22)
    keta_dose = random.choice([20, 25, 30])

    # TQ-Seite folgt aus main_inj.region wenn moeglich
    region_to_side = {
        "thigh_r": "right leg", "thigh_l": "left leg",
        "lower_leg_r": "right lower leg", "lower_leg_l": "left lower leg",
        "upper_arm_r": "right arm", "upper_arm_l": "left arm",
        "shoulder_r": "right shoulder", "shoulder_l": "left shoulder",
        "abdomen_r": "right abdomen", "abdomen_l": "left abdomen",
        "chest_r": "right chest", "chest_l": "left chest",
        "flank_r": "right flank", "flank_l": "left flank",
    }
    tq_side = region_to_side.get(main_inj["region"], "right leg")

    # Movement / Evacuation
    evac_priority = random.choice(["Urgent Surgical", "Urgent", "Priority"])
    transport_cat = "Litter" if random.random() < 0.85 else "Ambulatory"
    destination = random.choice(["Role 2 via Role 1", "Role 1 then Role 2",
                                  "Role 2", "Role 2E"])

    # Recorder
    rec_rank, rec_name, rec_function = random_recorder()

    # ----- Transcript-Erzeugung — Sprachfluss aus Anhang B 1:1 -----
    transcript = (
        f"Field Medical Card for one casualty. "
        f"Patient is {rank_en} {first} {last}, {sex_word}, German Army, "
        f"service number {sn.replace('-', ' ')}, born {dob_word}. "
        f"Unit is {unit}. "
        f"The patient was wounded in action on {inj_date_word} at {t_inj} Zulu "
        f"after a {mechanism.lower()}. "
        f"First assessment at {t_first} Zulu: "
        f"patient alert, airway clear, breathing present on both sides, "
        f"no open chest wound. "
        f"Main injury is {main_inj['text'].lower()}. "
        f"{additional_inj}. "
        f"No loss of consciousness reported. "
        f"No known drug allergies. "
        f"Blood group {blood_group.replace('+', ' positive').replace('-', ' negative')}. "
        f"Vitals at {t_first} Zulu: "
        f"pulse {v1['pulse']}, blood pressure {v1['bp'].replace('/', ' over ')}, "
        f"respiratory rate {v1['resp_rate']}, oxygen saturation {v1['spo2']} percent on room air, "
        f"GCS {v1['gcs']}, pain {v1['pain']} out of 10. "
        f"CAT tourniquet applied to the {tq_side} at {t_tq} Zulu. "
        f"Hemostatic gauze and pressure dressing applied at {t_dressing} Zulu. "
        f"Hypothermia prevention applied. "
        f"IV access, 18 gauge, left antecubital, established at {t_iv} Zulu. "
        f"TXA 1 gram IV at {t_txa} Zulu. "
        f"Ketamine {keta_dose} milligrams IV at {t_keta} Zulu. "
        f"Ceftriaxone 2 grams IV at {t_ceft} Zulu. "
        f"Balanced crystalloid 500 milliliters IV started at {t_fluid} Zulu. "
        f"Left forearm splinted at {t_splint} Zulu. "
        f"Recheck at {t_recheck} Zulu: "
        f"pulse {v2['pulse']}, blood pressure {v2['bp'].replace('/', ' over ')}, "
        f"respiratory rate {v2['resp_rate']}, oxygen saturation {v2['spo2']} percent, "
        f"GCS {v2['gcs']}, pain {v2['pain']} out of 10. "
        f"Evacuation priority {evac_priority.lower()}. "
        f"Transport category {transport_cat.lower()}. "
        f"Recommended destination {destination}. "
        f"Recorded by {rec_rank} {rec_name}, {rec_function.lower()}."
    )

    fmc = {
        # A. Identification
        "section_a": {
            "last_name": last.upper(),
            "first_name": first,
            "rank": rank_en,
            "sex": sex_label,
            "dob": dob_label,
            "service_number": sn,
            "nationality": "German Armed Forces / DEU",
            "unit": unit,
        },
        # B. Cause
        "section_b": {
            "casualty_type": "WIA — Wounded in Action",
            "datetime_injury": f"{inj_date_label} / {t_inj}Z",
            "mechanism": mechanism,
        },
        # C. Initial Assessment
        "section_c": {
            "time_first_assessment": f"{t_first}Z",
            "general_condition": "Alert",
            "airway": "Clear",
            "breathing": "Present bilaterally",
            "chest": "No open chest wound identified",
            "main_injury": main_inj["text"],
            "main_injury_region": main_inj["region"],
            "additional_injury": additional_inj,
            "loss_of_consciousness": "Not reported",
            "allergies": "NKDA — No known drug allergies",
            "blood_group": blood_group,
        },
        # D. Vital Signs (zwei Messpunkte)
        "section_d": [
            {"time": f"{t_first}Z", "pulse": v1["pulse"], "bp": v1["bp"],
             "resp_rate": v1["resp_rate"], "spo2": v1["spo2"],
             "gcs": v1["gcs"], "pain": v1["pain"]},
            {"time": f"{t_recheck}Z", "pulse": v2["pulse"], "bp": v2["bp"],
             "resp_rate": v2["resp_rate"], "spo2": v2["spo2"],
             "gcs": v2["gcs"], "pain": v2["pain"]},
        ],
        # E. Treatment
        "section_e": {
            "tourniquet": f"CAT tourniquet applied to {tq_side}",
            "tourniquet_time": f"{t_tq}Z",
            "hemorrhage_control": f"Hemostatic gauze and pressure dressing applied at {t_dressing}Z",
            "hypothermia_prevention": "Applied",
            "iv_access": f"18G IV access, left antecubital, established at {t_iv}Z",
            "medications": [
                {"name": "TXA", "dose": "1 g", "route": "IV", "time": f"{t_txa}Z"},
                {"name": "Ketamine", "dose": f"{keta_dose} mg", "route": "IV", "time": f"{t_keta}Z"},
                {"name": "Ceftriaxone", "dose": "2 g", "route": "IV", "time": f"{t_ceft}Z"},
            ],
            "fluids": [
                {"name": "Balanced crystalloid", "volume": "500 ml", "route": "IV", "time": f"{t_fluid}Z"},
            ],
            "immobilization": f"Left forearm splinted at {t_splint}Z",
            "surgical_procedure": "None performed before evacuation",
        },
        # F. Movement / Evacuation
        "section_f": {
            "evacuation_priority": evac_priority,
            "transport_category": transport_cat,
            "destination": destination,
            "considerations": [
                f"{tq_side.split()[0].capitalize()} {tq_side.split()[1] if len(tq_side.split()) > 1 else ''} tourniquet in place".strip(),
                "Monitor for recurrent bleeding and shock",
                "Maintain hypothermia prevention",
                "IV access established",
            ],
        },
        # G. Documentation
        "section_g": {
            "recorded_by": f"{rec_rank} {rec_name}",
            "function": rec_function,
        },
    }
    return transcript, fmc
