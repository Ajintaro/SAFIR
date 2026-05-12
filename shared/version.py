"""SAFIR Version - Single Source of Truth.

``VERSION`` ist die einzige Versionsangabe. Bei jeder Aenderung
(Feature, Fix, Refactor) wird sie manuell hochgezaehlt — Schrittweite
0.0.1. Beispiel: 0.1.1 -> 0.1.2 -> 0.1.3 ...

Beide Backends (Jetson + SINA Workstation) lesen aus dieser Datei und
exposen den Wert ueber ``/api/status`` und im Heartbeat. Das Frontend
zeigt sie in:
  - Settings -> SAFIR Informationen (Version + Geraet)
  - Sidebar-Footer (vX.Y.Z)
  - Footer-Badge unter der App
  - Netzwerk-Teilnehmer-Dialog (Version pro Peer)

Bumping-Regel: jede Aenderung +0.01. Keine Build-Hashes, keine
Counter — die einzige Wahrheit ist VERSION.
"""

from __future__ import annotations

# WICHTIG: Bei JEDER Aenderung (Feature/Fix/Refactor) hochzaehlen.
# Schrittweite 0.0.1. Das ist die einzige Stelle an der die
# Versionsnummer gepflegt wird.
VERSION: str = "0.1.10"


def get_full_version() -> str:
    """Versionsstring fuer Anzeige. Identisch zu ``VERSION``."""
    return VERSION


# Module-level Konstante fuer Backwards-Compat.
FULL_VERSION: str = VERSION
