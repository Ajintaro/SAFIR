#!/usr/bin/env python3
"""
SAFIR Operator-Karte registrieren — interaktives Helper-Skript.

Benutzung:
  python3 scripts/register-operator.py

Voraussetzung:
  - SAFIR darf NICHT laufen (sonst hat der App-Prozess den RC522 in Beschlag).
  - Blaue Operator-Karte bereit halten.

Ablauf:
  1. Skript initialisiert den RC522
  2. Fragt nach Label (A/B/...), Name, Rolle
  3. Wartet auf RFID-Scan
  4. Trägt den Operator in config.json ein (Duplikate werden ersetzt)
"""
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))
CONFIG_PATH = PROJECT_DIR / "config.json"

from shared.rfid import rc522_init, rc522_read_uid


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)


def main():
    print("\n=== SAFIR Operator-Karte registrieren ===\n")

    cfg = load_config()
    rfid_cfg = cfg.setdefault("rfid", {})
    operators = rfid_cfg.setdefault("operators", [])
    available_roles = list(rfid_cfg.get("roles", {}).keys()) or ["bat_soldat_1", "arzt"]

    print(f"Aktuelle Operatoren ({len(operators)}):")
    for op in operators:
        print(f"  [{op.get('label')}] {op.get('name')} — {op.get('role')} — UID {op.get('uid')}")
    print()

    label = input("Label (z.B. A, B, C): ").strip().upper()
    if not label:
        print("Abgebrochen — kein Label.")
        return 1

    name = input("Name (z.B. 'Sani-1'): ").strip()
    if not name:
        print("Abgebrochen — kein Name.")
        return 1

    print(f"\nVerfügbare Rollen: {', '.join(available_roles)}")
    role = input("Rolle: ").strip()
    if role not in available_roles:
        print(f"Abgebrochen — Rolle '{role}' existiert nicht.")
        return 1

    print("\nRC522 initialisieren...")
    if not rc522_init():
        print("FEHLER: RC522 nicht erreichbar. Läuft SAFIR noch?")
        return 1

    print("\nJetzt bitte die blaue Operator-Karte auflegen (15 s Timeout)...")
    uid = rc522_read_uid(timeout=15.0)
    if not uid:
        print("Timeout — keine Karte erkannt.")
        return 1

    print(f"\nUID erkannt: {uid}")

    # Duplikat-Check
    existing_idx = None
    for i, op in enumerate(operators):
        if op.get("uid", "").upper() == uid.upper():
            existing_idx = i
            print(f"WARNUNG: UID bereits registriert als [{op.get('label')}] {op.get('name')}")
            break

    confirm = input(f"Als [{label}] {name} ({role}) {'ERSETZEN' if existing_idx is not None else 'eintragen'}? [j/N] ").strip().lower()
    if confirm != "j":
        print("Abgebrochen.")
        return 1

    new_entry = {"uid": uid.upper(), "label": label, "name": name, "role": role}
    if existing_idx is not None:
        operators[existing_idx] = new_entry
    else:
        operators.append(new_entry)

    save_config(cfg)
    print(f"\nOK: Operator eingetragen in config.json")
    print(f"    [{label}] {name} — {role} — UID {uid}")
    print("\nSAFIR neu starten damit die Änderung aktiv wird.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        print("\nAbgebrochen.")
        sys.exit(1)
