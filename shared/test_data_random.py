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
