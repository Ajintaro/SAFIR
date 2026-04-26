"""SAFIR Version - Single Source of Truth.

Bei jedem signifikanten Build/Release wird ``VERSION`` per Hand
hochgezaehlt. Beide Backends (Jetson + Surface) lesen aus dieser
Datei und exposen den Wert ueber ``/api/status``. Das Frontend
liest ihn dort und zeigt ihn in:
  - Settings -> SAFIR Informationen (Version + Geraet)
  - Sidebar-Footer (vX.Y)
  - Footer-Badge unter der App
  - Hardware-Monitor-Overlay (Geraete-Name)

Bumping-Regeln (Empfehlung):
  0.1 -> 0.2  : kleines Feature / sichtbarer Fix
  0.x -> 1.0  : erster Demo-tauglicher Meilenstein
  Major.Minor : in der Regel reicht das, Patch nur fuer Hotfixes

Zusaetzlich liefern wir ``BUILD_HASH`` (kurzer Git-Commit-Hash)
und ``FULL_VERSION`` (``X.Y+abcdef0``) damit selbst bei vergessenem
Bump unterschiedliche Builds eindeutig unterscheidbar sind.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# WICHTIG: Dies ist die einzige Stelle an der die Versionsnummer
# angepasst werden muss. Alle UI-Elemente und APIs lesen von hier.
VERSION: str = "0.1.0"


_cached_build_hash: str | None = None


def _read_git_head_directly(repo_root: Path) -> str | None:
    """Liest den kurzen Commit-Hash direkt aus ``.git/HEAD``.

    Umgeht git's ``safe.directory``-Check, der auf dem Jetson bei
    Service-Lauf als root mit Repo-Owner ``jetson`` zuschlaegt.
    Funktioniert sowohl fuer attached HEAD (``ref: refs/heads/...``)
    mit losen oder gepackten Refs als auch fuer detached HEAD.
    """
    try:
        head_file = repo_root / ".git" / "HEAD"
        if not head_file.exists():
            return None
        head = head_file.read_text().strip()
        if head.startswith("ref:"):
            target = head.split(" ", 1)[1].strip()
            ref_file = repo_root / ".git" / target
            if ref_file.exists():
                sha = ref_file.read_text().strip()
                if sha:
                    return sha[:7]
            packed = repo_root / ".git" / "packed-refs"
            if packed.exists():
                for line in packed.read_text().splitlines():
                    if line.startswith("#") or " " not in line:
                        continue
                    sha, ref = line.split(" ", 1)
                    if ref.strip() == target:
                        return sha[:7]
        elif len(head) >= 7:
            return head[:7]
    except Exception:
        pass
    return None


def _compute_build_hash() -> str:
    """Liefert den kurzen Git-Commit-Hash als Build-Identifier.

    Erst wird ``.git/HEAD`` direkt gelesen (kein subprocess noetig,
    funktioniert auch wenn der Service als root laeuft und git
    ``safe.directory`` reklamiert). Erst danach Fallback auf das
    git-Binary mit ``safe.directory=*``. Timeout 5 s damit ein
    hangender git-Aufruf den Backend-Start nicht blockiert.

    Faellt auf ``"dev"`` zurueck wenn weder ``.git/`` noch ``git``
    verfuegbar sind (z.B. bei ausgepacktem Release-Tarball).
    """
    repo_root = Path(__file__).resolve().parent.parent
    direct = _read_git_head_directly(repo_root)
    if direct:
        return direct
    try:
        result = subprocess.run(
            ["git", "-c", "safe.directory=*", "rev-parse", "--short", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            sha = result.stdout.strip()
            if sha:
                return sha
    except Exception:
        pass
    return "dev"


def get_build_hash() -> str:
    """Lazy-cached Build-Hash. Erster Aufruf rechnet, danach gecached.

    Wenn der erste Versuch ``"dev"`` lieferte (z.B. weil git wegen
    System-Last nicht antwortete), versuchen wir es beim naechsten
    Aufruf nochmal — sodass wir nicht den ganzen Service-Lebenszyklus
    auf einem Fallback haengenbleiben.
    """
    global _cached_build_hash
    if _cached_build_hash is None or _cached_build_hash == "dev":
        _cached_build_hash = _compute_build_hash()
    return _cached_build_hash


def get_full_version() -> str:
    """Versionsstring fuer Anzeige: ``X.Y.Z+abcdef0`` oder nur ``X.Y.Z``."""
    h = get_build_hash()
    return f"{VERSION}+{h}" if h != "dev" else VERSION


# Module-level Konstanten fuer Backwards-Compat. Werden lazy
# initialisiert beim ersten Import — auf langsamen Systemen kann
# das initial "dev" sein, ``get_build_hash()`` heilt das beim
# naechsten Aufruf.
BUILD_HASH: str = get_build_hash()
FULL_VERSION: str = get_full_version()
