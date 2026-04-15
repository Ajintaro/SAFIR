#!/usr/bin/env python3
"""RFID Write+Read Roundtrip-Diagnose.

Schreibt einen Test-Patienten auf die Karte die gerade auf dem Reader
liegt, liest sofort danach Block 4-6 und 8-10 zurueck und vergleicht
hex-fuer-hex. Damit laesst sich isolieren, ob:
  (a) der Write klappt aber der Read alte Daten liefert (Cache/Read-Bug)
  (b) der Write nicht ankommt aber Verify trotzdem True meldet (Verify-Bug)
  (c) der Auth oder die Phase-1-Karten-Suche stillschweigend scheitert

Aufruf auf dem Jetson (im venv):
    /home/jetson/cgi-afcea-san/venv/bin/python3 scripts/rfid_write_diag.py

WICHTIG: Vorher muss der safir.service GESTOPPT sein, sonst hat der
RfidService poll-loop den SPI-Bus belegt:
    sudo systemctl stop safir
    /home/jetson/cgi-afcea-san/venv/bin/python3 scripts/rfid_write_diag.py
    sudo systemctl start safir
"""

import sys
import time

sys.path.insert(0, "/home/jetson/cgi-afcea-san")

from shared.rfid import (
    rc522_init,
    is_rc522_available,
    rc522_write_patient_to_card,
    _spi_lock,
    _rc522_request,
    _rc522_anticoll,
    _rc522_select,
    _rc522_auth,
    _rc522_read_block,
    _rc522_stop_crypto,
    _rc522_halt,
    _build_patient_payload,
    _PICC_REQIDL,
    _PICC_WUPA,
)
from shared import tts as _tts


def say(text: str):
    """TTS-Ansage mit Blocking, damit das Skript erst weiterlaeuft wenn
    der User die Ansage gehoert hat."""
    print(f"  [TTS] {text}")
    try:
        _tts.speak(text, blocking=True)
    except Exception as e:
        print(f"  [TTS-FEHLER] {e}")


def hex16(b):
    return " ".join(f"{x:02X}" for x in (b or b""))


def read_all_blocks(uid_bytes):
    """Liest Block 4-6 und 8-10 mit eigenen Auth-Calls.
    Variante mit komplettem Hardware-Reset zwischen Sektoren — wenn das
    funktioniert wissen wir dass es ein State-Problem ist und keine
    fehlgeschlagene Auth."""
    out = {}
    # Sektor 1: Auth auf Block 4, dann 4/5/6
    if not _rc522_auth(4, uid_bytes):
        print("  [READ] Auth Sektor 1 fehlgeschlagen")
        return out
    for blk in (4, 5, 6):
        out[blk] = _rc522_read_block(blk)
    _rc522_stop_crypto()
    _rc522_halt()
    time.sleep(0.05)
    # KOMPLETTER Hardware-Reset des RC522 + Karte neu finden
    print("  [READ] RC522 reinit zwischen Sektoren ...")
    rc522_init()
    time.sleep(0.05)
    # Wiederfinde die Karte (REQIDL nach Reset funktioniert wieder)
    uid_bytes_2, sak_2 = find_card(timeout=5.0)
    if uid_bytes_2 is None:
        print("  [READ] Karte nach Reset nicht wiedergefunden")
        return out
    if uid_bytes_2 != uid_bytes:
        print(f"  [READ] WARNUNG: andere Karte? {uid_bytes_2.hex()} statt {uid_bytes.hex()}")
    # Sektor 2: Auth auf Block 8, dann 8/9/10
    if not _rc522_auth(8, uid_bytes_2):
        print("  [READ] Auth Sektor 2 fehlgeschlagen (auch nach Hardware-Reset)")
        return out
    print("  [READ] Auth Sektor 2 OK")
    for blk in (8, 9, 10):
        out[blk] = _rc522_read_block(blk)
    _rc522_stop_crypto()
    return out


def find_card(timeout=10.0):
    start = time.time()
    while time.time() - start < timeout:
        ok, _ = _rc522_request(_PICC_REQIDL)
        if ok:
            uid5 = _rc522_anticoll()
            if uid5 is not None:
                sak = _rc522_select(uid5)
                if sak is not None:
                    return uid5[:4], sak
        time.sleep(0.1)
    return None, None


def main():
    print("=" * 72)
    print("RFID Write+Read Roundtrip-Diagnose")
    print("=" * 72)

    print("\n[INIT] RC522 initialisieren ...")
    rc522_init()
    if not is_rc522_available():
        print("FEHLER: RC522 nicht verfuegbar. Verkabelung pruefen.")
        return 1
    print("[INIT] OK")

    print("\n[INIT] Piper TTS laden ...")
    _tts.init_tts()
    print("[INIT] TTS bereit")
    say("RFID Diagnose startet")

    # Test-Patient mit klar erkennbaren Werten
    test_patient = {
        "patient_id": f"DIAG-{int(time.time()) % 10000:04d}",
        "name": "Diagnose Tester",
        "rank": "OFA",
        "age": 42,
        "gender": "m",
        "triage": "T2",
        "vitals": {
            "blood_pressure": "120/80",
            "pulse": 72,
            "respiration": 16,
            "spo2": 98,
            "gcs": 15,
        },
        "injury": {"mechanism": ["Stichverletzung"]},
    }
    print(f"\n[PATIENT] Test-ID: {test_patient['patient_id']}")
    print(f"[PATIENT] Name:    {test_patient['name']}")
    print(f"[PATIENT] Triage:  {test_patient['triage']}")

    # Erwartete Bytes (was wir gleich auf der Karte sehen wollen)
    expected = _build_patient_payload(test_patient)
    print("\n[PAYLOAD-EXPECTED] (was wir schreiben werden)")
    for blk in sorted(expected):
        print(f"  Block {blk:2d}: {hex16(expected[blk])}")

    # PRE-READ: Was steht aktuell auf der Karte?
    print("\n[PRE-READ] Aktueller Karten-Inhalt VOR dem Write:")
    say("Jetzt Karte auflegen")
    print("           (du hast 30 Sekunden Zeit ...)")
    with _spi_lock:
        uid_bytes, sak = find_card(timeout=30.0)
        if uid_bytes is None:
            print("FEHLER: Keine Karte gefunden in 15 s")
            return 2
        uid_hex = "".join(f"{b:02X}" for b in uid_bytes)
        print(f"  UID: {uid_hex} (SAK 0x{sak:02X})")
        pre = read_all_blocks(uid_bytes)
        for blk in sorted(pre):
            print(f"  Block {blk:2d}: {hex16(pre[blk])}")
        _rc522_halt()

    # WRITE: Den Test-Patienten schreiben (nutzt die echte Funktion)
    print("\n[WRITE] Schreibe Test-Patient ...")
    say("Karte liegen lassen, schreibe jetzt")
    t0 = time.time()
    success, result = rc522_write_patient_to_card(test_patient, timeout=10.0)
    dt = time.time() - t0
    print(f"[WRITE] success={success}  result={result}  ({dt:.2f} s)")

    if not success:
        print("\nFEHLER beim Write — siehe oben fuer Details")
        return 3

    # POST-READ: Sofort wieder lesen und vergleichen
    print("\n[POST-READ] Karten-Inhalt NACH dem Write (gleiche Karte):")
    say("Karte fuer Verifikation auflegen")
    with _spi_lock:
        uid_bytes2, _ = find_card(timeout=15.0)
        if uid_bytes2 is None:
            print("FEHLER: Karte verschwunden zwischen Write und Re-Read")
            return 4
        uid_hex2 = "".join(f"{b:02X}" for b in uid_bytes2)
        print(f"  UID: {uid_hex2}  (sollte gleich sein wie {uid_hex})")
        post = read_all_blocks(uid_bytes2)
        _rc522_halt()

    # VERGLEICH
    # WICHTIG: Block 4 enthaelt am Ende einen Unix-Timestamp (Bytes 12-15).
    # Da unser Skript expected vor dem Write berechnet und rc522_write_patient
    # _to_card den Payload selbst nochmal baut (mit aktuellem Timestamp), gibt
    # es immer eine kleine Differenz. Wir vergleichen Block 4 deshalb nur ueber
    # die ersten 12 Bytes (Magic + Version + Reserved).
    print("\n[VERGLEICH] expected vs post-read:")
    all_ok = True
    for blk in sorted(expected):
        exp = expected[blk]
        got = post.get(blk)
        if blk == 4 and exp is not None and got is not None:
            ok = (exp[:12] == got[:12])
            note = "  (Timestamp-Bytes 12-15 toleriert)"
        else:
            ok = (exp == got)
            note = ""
        marker = "OK " if ok else "!! "
        print(f"  {marker}Block {blk:2d}{note}")
        print(f"      expected: {hex16(exp)}")
        print(f"      got     : {hex16(got)}")
        if not ok:
            all_ok = False

    print("\n" + ("=" * 72))
    if all_ok:
        print("ERGEBNIS: Write+Read-Cycle ist KONSISTENT.")
        print("          Wenn der User trotzdem 'alte Daten' meldet, liegt")
        print("          der Bug woanders (z.B. Frontend-Cache, Backend-Sync).")
        say("Karte erfolgreich beschrieben und verifiziert")
    else:
        print("ERGEBNIS: !! Mismatch zwischen erwartet und gelesen !!")
        print("          Das ist der RFID-Write-Bug. Vergleiche pre-read mit")
        print("          post-read um zu sehen, ob die Karte 'irgendetwas'")
        print("          aktualisiert hat oder bei den alten Bytes geblieben ist.")
        say("Diagnose fehlgeschlagen, siehe Log")
    print("=" * 72)
    return 0 if all_ok else 5


if __name__ == "__main__":
    sys.exit(main())
