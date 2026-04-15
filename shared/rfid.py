"""
SAFIR — RFID-Modul für Patientenregistrierung.
RC522 MFRC522 v2.0 über Bit-Bang SPI am Jetson Orin Nano GPIO Header.
Fallback: Keyboard-Simulation wenn kein RC522 erkannt wird.

Pinbelegung (festgelötet):
  SDA=lila(24), SCK=schwarz(23), MOSI=blau(19), MISO=weiß(21),
  GND=grau(20), RST=rot(7), VCC=braun(17)
"""

import uuid
import logging
import threading
from datetime import datetime

log = logging.getLogger("safir.rfid")

# RC522 Hardware-Zugriff (Bit-Bang SPI über Jetson.GPIO)
_rc522_available = False
_GPIO = None

# Globaler SPI-Lock: serialisiert alle High-Level-Zugriffe auf den RC522.
# Nötig weil RfidService._run() im Loop rc522_read_uid() aufruft und parallel
# voice_write_card() rc522_write_patient_to_card() triggert — beide würden
# sonst gleichzeitig auf denselben Bit-Bang-SPI-Bus zugreifen und sich
# gegenseitig zerstören (hängen oder Silent-Fail).
_spi_lock = threading.Lock()

# Pin-Nummern (BOARD-Modus)
_MOSI = 19
_MISO = 21
_SCK = 23
_CS = 24
_RST = 7


def _spi_byte(tx):
    """Sendet/empfängt ein Byte über Bit-Bang SPI."""
    rx = 0
    for i in range(7, -1, -1):
        _GPIO.output(_MOSI, (tx >> i) & 1)
        _GPIO.output(_SCK, _GPIO.HIGH)
        rx = (rx << 1) | _GPIO.input(_MISO)
        _GPIO.output(_SCK, _GPIO.LOW)
    return rx


def rc522_read(addr):
    """Liest ein Register vom RC522."""
    _GPIO.output(_CS, _GPIO.LOW)
    _spi_byte(((addr << 1) & 0x7E) | 0x80)
    val = _spi_byte(0x00)
    _GPIO.output(_CS, _GPIO.HIGH)
    return val


def rc522_write(addr, val):
    """Schreibt ein Register am RC522."""
    _GPIO.output(_CS, _GPIO.LOW)
    _spi_byte((addr << 1) & 0x7E)
    _spi_byte(val)
    _GPIO.output(_CS, _GPIO.HIGH)


def rc522_init():
    """Initialisiert den RC522 RFID-Reader. Gibt True zurück wenn erkannt."""
    global _rc522_available, _GPIO
    try:
        import time
        import Jetson.GPIO as GPIO
        _GPIO = GPIO
        GPIO.setmode(GPIO.BOARD)
        GPIO.setwarnings(False)

        GPIO.setup([_MOSI, _SCK, _CS, _RST], GPIO.OUT)
        GPIO.setup(_MISO, GPIO.IN)
        GPIO.output(_CS, GPIO.HIGH)
        GPIO.output(_SCK, GPIO.LOW)

        # Hard Reset
        GPIO.output(_RST, GPIO.LOW)
        time.sleep(0.05)
        GPIO.output(_RST, GPIO.HIGH)
        time.sleep(0.05)

        ver = rc522_read(0x37)
        if ver not in (0x91, 0x92):
            log.warning(f"RC522 nicht erkannt (Version: 0x{ver:02X})")
            return False

        # Soft Reset
        rc522_write(0x01, 0x0F)
        time.sleep(0.05)

        # Timer: Auto-Start, ~25ms Timeout
        rc522_write(0x2A, 0x8D)  # TModeReg
        rc522_write(0x2B, 0x3E)  # TPrescalerReg
        rc522_write(0x2C, 0x00)  # TReloadReg Hi
        rc522_write(0x2D, 0x1E)  # TReloadReg Lo

        # 100% ASK-Modulation + CRC-Preset 0x6363
        rc522_write(0x15, 0x40)  # TxASKReg
        rc522_write(0x11, 0x3D)  # ModeReg

        # Empfangsverstärker auf Maximum (48dB)
        rc522_write(0x26, 0x70)  # RFCfgReg

        # Antenne einschalten
        tx_ctrl = rc522_read(0x14)
        rc522_write(0x14, tx_ctrl | 0x03)

        _rc522_available = True
        log.info(f"RC522 erkannt (v{ver - 0x90}.0), Antenne aktiv, Gain max")
        return True
    except Exception as e:
        log.warning(f"RC522 Init fehlgeschlagen: {e}")
        return False


def rc522_read_uid(timeout=5.0):
    """Wartet auf eine RFID-Karte und gibt die UID als Hex-String zurück.
    Gibt None zurück bei Timeout oder wenn kein RC522 verfügbar.

    Hält während des gesamten Polling-Zyklus den globalen SPI-Lock —
    solange der Lock belegt ist (z. B. durch einen Write-Vorgang) wartet
    der Caller hier. Kleine Timeouts (≤ 0.5 s aus RfidService) halten den
    Lock nur kurz, damit Writes nicht blockieren."""
    if not _rc522_available:
        return None

    import time
    start = time.time()

    with _spi_lock:
        while time.time() - start < timeout:
            # REQA senden (ISO 14443A Short Frame)
            rc522_write(0x01, 0x00)  # Idle
            rc522_write(0x04, 0x7F)  # Alle IRQs löschen
            rc522_write(0x0A, 0x80)  # FlushBuffer
            rc522_write(0x0D, 0x07)  # BitFramingReg: TxLastBits=7
            rc522_write(0x09, 0x26)  # REQA in FIFO
            rc522_write(0x01, 0x0C)  # Transceive
            rc522_write(0x0D, 0x87)  # StartSend

            # Warte auf IRQ (RxIRQ, IdleIRQ oder TimerIRQ)
            for _ in range(50):
                irq = rc522_read(0x04)
                if irq & 0x31:
                    break
                time.sleep(0.001)

            err = rc522_read(0x06)
            fifo = rc522_read(0x0A)

            if (irq & 0x20) and fifo >= 2 and not (err & 0x1B):
                # ATQA empfangen — Anti-Collision starten
                rc522_write(0x01, 0x00)
                rc522_write(0x04, 0x7F)
                rc522_write(0x0A, 0x80)
                rc522_write(0x0D, 0x00)  # Volle Bytes
                rc522_write(0x09, 0x93)  # SEL CL1
                rc522_write(0x09, 0x20)  # NVB = 2 Bytes
                rc522_write(0x01, 0x0C)  # Transceive
                rc522_write(0x0D, 0x80)  # StartSend

                for _ in range(50):
                    irq = rc522_read(0x04)
                    if irq & 0x31:
                        break
                    time.sleep(0.001)

                level = rc522_read(0x0A)
                if level >= 5:
                    uid_bytes = [rc522_read(0x09) for _ in range(5)]
                    # BCC prüfen
                    bcc = uid_bytes[0] ^ uid_bytes[1] ^ uid_bytes[2] ^ uid_bytes[3]
                    if bcc == uid_bytes[4]:
                        uid = "".join(f"{b:02X}" for b in uid_bytes[:4])
                        log.info(f"RFID-Karte erkannt: {uid}")
                        return uid

            time.sleep(0.15)

    return None


def is_rc522_available():
    """Gibt True zurück wenn ein RC522 RFID-Reader angeschlossen ist."""
    return _rc522_available


# ---------------------------------------------------------------------------
# MIFARE Classic 1K Read/Write — Low-Level-Protokoll
# ---------------------------------------------------------------------------
# Befehls-Konstanten nach MFRC522-Datenblatt bzw. ISO/IEC 14443A
_PCD_IDLE        = 0x00
_PCD_CALCCRC     = 0x03
_PCD_TRANSCEIVE  = 0x0C
_PCD_AUTHENT     = 0x0E
_PCD_SOFTRESET   = 0x0F

_PICC_REQIDL     = 0x26  # REQA — spricht nur Karten im IDLE-Zustand an
_PICC_WUPA       = 0x52  # Wake-Up All — spricht ALLE Karten an, auch nach Auth
_PICC_ANTICOLL   = 0x93
_PICC_SElECTTAG  = 0x93
_PICC_AUTHENT1A  = 0x60
_PICC_READ       = 0x30
_PICC_WRITE      = 0xA0
_PICC_HALT       = 0x50

_MIFARE_DEFAULT_KEY = [0xFF] * 6


def _rc522_calc_crc(data):
    """Lässt den RC522 den ISO14443-CRC_A über ein Byte-Array berechnen."""
    import time
    rc522_write(0x05, 0x04)       # DivIrqReg — CRCIRq clear
    rc522_write(0x0A, 0x80)       # FIFO flush
    for b in data:
        rc522_write(0x09, b)      # FIFO write
    rc522_write(0x01, _PCD_CALCCRC)
    for _ in range(255):
        irq = rc522_read(0x05)
        if irq & 0x04:
            break
        time.sleep(0.0005)
    lo = rc522_read(0x22)         # CRCResultReg Low
    hi = rc522_read(0x21)         # CRCResultReg High
    return [lo, hi]


def _rc522_to_card(command, data, tx_last_bits: int = 0):
    """Wrapper um die Transceive-Operation. Gibt (ok, response_bytes, response_bits).

    ``tx_last_bits`` steuert die BitFramingReg TxLastBits für Short Frames
    (REQA/WUPA brauchen 7 Bits, alles andere volle Bytes = 0).
    """
    import time
    wait_irq = 0x30 if command == _PCD_TRANSCEIVE else 0x10
    irq_en = 0x77 if command == _PCD_TRANSCEIVE else 0x12

    rc522_write(0x02, irq_en | 0x80)  # ComIEnReg: enable IRQs + invert pin
    rc522_write(0x04, 0x7F)           # clear all IRQ bits
    rc522_write(0x0A, 0x80)           # flush FIFO
    rc522_write(0x01, _PCD_IDLE)      # CommandReg: idle
    # BitFramingReg: TxLastBits BEVOR wir Daten in FIFO schreiben (manche
    # Controller latchen das sonst nicht). Wert ohne StartSend.
    rc522_write(0x0D, tx_last_bits & 0x07)
    for b in data:
        rc522_write(0x09, b)          # fill FIFO
    rc522_write(0x01, command)        # fire command
    if command == _PCD_TRANSCEIVE:
        # StartSend = Bit 7, TxLastBits in Bits 0..2 — BEIDE müssen gesetzt
        # bleiben sonst sendet der RC522 volle Bytes und das REQA-Short-Frame
        # wird von der Karte ignoriert.
        rc522_write(0x0D, 0x80 | (tx_last_bits & 0x07))

    # Poll IRQ bis Timer abgelaufen oder gewünschte IRQ gesetzt
    for _ in range(2000):
        irq = rc522_read(0x04)
        if irq & 0x01:                # TimerIRq
            break
        if irq & wait_irq:
            break
        time.sleep(0.0005)

    rc522_write(0x0D, 0x00)           # StartSend + TxLastBits clear

    err = rc522_read(0x06)            # ErrorReg
    if err & 0x1B:
        return (False, [], 0)

    if not (irq & wait_irq & 0x01):   # nichts angekommen
        pass

    if command != _PCD_TRANSCEIVE:
        return (True, [], 0)

    # Response aus FIFO lesen
    n = rc522_read(0x0A)              # FIFOLevel
    last_bits = rc522_read(0x0C) & 0x07  # ControlReg letzte Bits
    total_bits = (n - 1) * 8 + last_bits if last_bits else n * 8
    if n > 16:
        n = 16
    resp = [rc522_read(0x09) for _ in range(n)]
    return (True, resp, total_bits)


def _rc522_request(req_mode=_PICC_REQIDL):
    """Sendet REQA/WUPA als 7-Bit Short Frame, gibt (ok, atqa_bits)."""
    ok, resp, bits = _rc522_to_card(_PCD_TRANSCEIVE, [req_mode], tx_last_bits=7)
    if not ok or bits != 0x10:
        return (False, 0)
    return (True, (resp[0] << 8) | resp[1] if len(resp) >= 2 else 0)


def _rc522_anticoll():
    """Anti-Collision Loop 1 — liefert 5 Byte UID (4 + BCC) oder None."""
    rc522_write(0x0D, 0x00)
    data = [_PICC_ANTICOLL, 0x20]
    ok, resp, bits = _rc522_to_card(_PCD_TRANSCEIVE, data)
    if not ok or len(resp) != 5:
        return None
    # BCC-Check
    bcc = resp[0] ^ resp[1] ^ resp[2] ^ resp[3]
    if bcc != resp[4]:
        return None
    return resp  # 5 Byte inkl. BCC


def _rc522_select(uid5):
    """PICC_SELECT — aktiviert die Karte, gibt SAK (1 Byte) zurück."""
    buf = [_PICC_SElECTTAG, 0x70] + list(uid5)   # inkl. BCC
    buf += _rc522_calc_crc(buf)
    rc522_write(0x0D, 0x00)
    ok, resp, bits = _rc522_to_card(_PCD_TRANSCEIVE, buf)
    if not ok or bits != 0x18:
        return None
    return resp[0]  # SAK


def _rc522_auth(block_addr, uid4, key=_MIFARE_DEFAULT_KEY):
    """MIFARE Classic Authentifizierung Key A auf einen Block."""
    buf = [_PICC_AUTHENT1A, block_addr] + list(key) + list(uid4)
    ok, _, _ = _rc522_to_card(_PCD_AUTHENT, buf)
    if not ok:
        return False
    status2 = rc522_read(0x08)
    return (status2 & 0x08) != 0


def _rc522_stop_crypto():
    """Schaltet den Crypto1-State nach Auth ab (sonst funktionieren weitere REQs nicht)."""
    status2 = rc522_read(0x08)
    rc522_write(0x08, status2 & ~0x08)


def _rc522_halt():
    """Schickt PICC_HALT damit die Karte nicht mehr antwortet."""
    buf = [_PICC_HALT, 0x00]
    buf += _rc522_calc_crc(buf)
    rc522_write(0x0D, 0x00)
    _rc522_to_card(_PCD_TRANSCEIVE, buf)


def _rc522_read_block(block_addr):
    """Liest 16 Byte aus einem authentifizierten Block. None bei Fehler."""
    buf = [_PICC_READ, block_addr]
    buf += _rc522_calc_crc(buf)
    ok, resp, bits = _rc522_to_card(_PCD_TRANSCEIVE, buf)
    if not ok or len(resp) != 16:
        return None
    return bytes(resp)


def _rc522_write_block(block_addr, data16):
    """Schreibt 16 Byte in einen authentifizierten Block.

    Gibt (True, "") bei Erfolg zurück, sonst (False, fehlerbeschreibung).
    Die MIFARE-Karte braucht nach einem Write ~10 ms internen Write-Cycle
    bevor sie auf den nächsten Befehl reagiert — wir warten explizit,
    weil manche Karten sonst den nachfolgenden Write/Verify mit NACK
    beantworten oder gar nicht reagieren.
    """
    import time as _t
    if len(data16) != 16:
        raise ValueError("data16 muss genau 16 Bytes haben")

    # Phase 1: WRITE-Befehl (2-Byte WRITE + CRC)
    buf = [_PICC_WRITE, block_addr]
    buf += _rc522_calc_crc(buf)
    ok, resp, bits = _rc522_to_card(_PCD_TRANSCEIVE, buf)
    if not ok:
        return (False, f"Phase1 to_card failed (err=0x{rc522_read(0x06):02X})")
    if bits != 4:
        return (False, f"Phase1 wrong bit count {bits} (resp={resp})")
    if (resp[0] & 0x0F) != 0x0A:
        return (False, f"Phase1 NACK 0x{resp[0]:02X} (expected ACK 0x0A)")

    # Phase 2: Daten senden (16 Byte + CRC)
    buf = list(data16)
    buf += _rc522_calc_crc(buf)
    ok, resp, bits = _rc522_to_card(_PCD_TRANSCEIVE, buf)
    if not ok:
        return (False, f"Phase2 to_card failed (err=0x{rc522_read(0x06):02X})")
    if bits != 4:
        return (False, f"Phase2 wrong bit count {bits} (resp={resp})")
    if (resp[0] & 0x0F) != 0x0A:
        return (False, f"Phase2 NACK 0x{resp[0]:02X} (expected ACK 0x0A)")

    # MIFARE Classic Write-Cycle: ~10 ms bis die Karte wirklich fertig ist.
    # Ohne das Sleep antworten manche Karten beim nächsten Read/Write mit
    # NACK weil sie noch im internen EEPROM-Write stecken.
    _t.sleep(0.012)
    return (True, "")


# ---------------------------------------------------------------------------
# SAFIR-Patientendaten auf MIFARE-Karte schreiben
# ---------------------------------------------------------------------------
# Layout (MIFARE Classic 1K, Default Key A = FFFFFFFFFFFF):
#   Sektor 1 Block 4  = Header:  "SAFIR\0\0\0" (8) + Version (1) + Reserved (3) + Unix-TS (4)
#   Sektor 1 Block 5  = Patient-ID (16 B ASCII, \0-pad)
#   Sektor 1 Block 6  = Triage (1) + Alter (1) + Geschlecht (1) + Flags (1) + Vitals (12)
#                       Vitals-Layout: RR_sys, RR_dia, Puls, AF, SpO2, GCS, plus 6 reserved
#   Sektor 2 Block 8  = Name Teil 1 (16 B UTF-8, \0-pad)
#   Sektor 2 Block 9  = Name Teil 2 (16 B UTF-8, \0-pad)
#   Sektor 2 Block 10 = Verletzungs-Mechanismus (16 B ASCII, \0-pad)
#
# Block 7 / 11 sind Sector-Trailer und werden NICHT angefasst.

SAFIR_CARD_MAGIC = b"SAFIR\0\0\0"
SAFIR_CARD_VERSION = 1


def _pad16(b: bytes) -> bytes:
    """Kürzt oder padded ein Byte-Array auf 16 Byte (Null-Padding)."""
    if len(b) >= 16:
        return b[:16]
    return b + b"\x00" * (16 - len(b))


def _triage_byte(triage: str) -> int:
    """Wandelt Triage-Kategorie in Byte-Code um (1..4, 0 = unbekannt)."""
    t = (triage or "").upper()
    if t.startswith("T1") or "ROT" in t:
        return 1
    if t.startswith("T2") or "GELB" in t:
        return 2
    if t.startswith("T3") or "GR" in t:
        return 3
    if t.startswith("T4") or "BLAU" in t:
        return 4
    return 0


def _build_patient_payload(patient: dict) -> dict:
    """Konvertiert ein Patient-Dict in das Block-Layout."""
    import struct
    import time as _t

    header = bytearray(16)
    header[0:8] = SAFIR_CARD_MAGIC
    header[8] = SAFIR_CARD_VERSION
    # Bytes 9..11 reserved (0)
    ts = int(_t.time())
    struct.pack_into("<I", header, 12, ts)

    patient_id = _pad16(patient.get("patient_id", "").encode("ascii", errors="ignore"))

    vitals = patient.get("vitals", {}) or {}
    def _int_safe(v, default=0):
        try:
            return int(float(v)) & 0xFF
        except Exception:
            return default
    block6 = bytearray(16)
    block6[0] = _triage_byte(patient.get("triage", ""))
    block6[1] = _int_safe(patient.get("age"))
    gender = (patient.get("gender", "") or "").lower()
    block6[2] = ord("m") if gender.startswith("m") else (ord("w") if gender.startswith("w") or gender.startswith("f") else 0)
    block6[3] = 0  # flags (reserved)
    block6[4] = _int_safe(vitals.get("blood_pressure_systolic") or _split_bp(vitals.get("blood_pressure"), 0))
    block6[5] = _int_safe(vitals.get("blood_pressure_diastolic") or _split_bp(vitals.get("blood_pressure"), 1))
    block6[6] = _int_safe(vitals.get("pulse"))
    block6[7] = _int_safe(vitals.get("respiration") or vitals.get("breathing_rate"))
    block6[8] = _int_safe(vitals.get("spo2"))
    block6[9] = _int_safe(vitals.get("gcs"))
    # 10..15 reserved

    name_bytes = (patient.get("name", "") or "").encode("utf-8")
    name1 = _pad16(name_bytes[:16])
    name2 = _pad16(name_bytes[16:32])

    mechanism = ""
    mech_list = patient.get("injury", {}).get("mechanism") if isinstance(patient.get("injury"), dict) else None
    if isinstance(mech_list, list) and mech_list:
        mechanism = str(mech_list[0])
    mech_bytes = _pad16(mechanism.encode("utf-8")[:16])

    return {
        4: bytes(header),
        5: bytes(patient_id),
        6: bytes(block6),
        8: bytes(name1),
        9: bytes(name2),
        10: bytes(mech_bytes),
    }


def _split_bp(bp_str, index):
    """Parst '120/80' → [120, 80]. Gibt 0 zurück wenn nicht parsebar."""
    if not bp_str:
        return 0
    try:
        parts = str(bp_str).replace(" ", "").split("/")
        return int(parts[index]) if index < len(parts) else 0
    except Exception:
        return 0


def rc522_write_patient_to_card(patient: dict, timeout: float = 10.0) -> tuple[bool, str]:
    """
    Komplett-Flow: wartet auf Karte, selektiert, authentifiziert, schreibt
    alle Blöcke und verifiziert durch Re-Read.

    Gibt (erfolg, uid_oder_fehlermeldung) zurück.

    Hält den globalen SPI-Lock während des gesamten Flows — der RfidService-
    Poll-Loop pausiert solange und greift nicht auf den Bus zu.
    """
    import time as _t

    if not _rc522_available:
        return (False, "RC522 nicht verfügbar")

    log.info(f"RFID-Write gestartet für Patient {patient.get('patient_id')} — warte auf SPI-Lock")
    with _spi_lock:
        log.info("SPI-Lock erhalten, suche Karte …")
        start = _t.time()
        # Phase 1: Karte finden (REQA + Anticoll + Select)
        uid_bytes = None
        sak = None
        while _t.time() - start < timeout:
            ok, _atqa = _rc522_request(_PICC_REQIDL)
            if not ok:
                _t.sleep(0.1)
                continue
            uid5 = _rc522_anticoll()
            if uid5 is None:
                _t.sleep(0.1)
                continue
            sak = _rc522_select(uid5)
            if sak is None:
                _t.sleep(0.1)
                continue
            uid_bytes = uid5[:4]
            break

        if uid_bytes is None:
            log.warning("RFID-Write: Phase 1 Timeout — keine Karte gefunden")
            return (False, "Timeout — keine Karte gefunden")

        uid_hex = "".join(f"{b:02X}" for b in uid_bytes)
        log.info(f"Karte gefunden zum Schreiben: UID {uid_hex}, SAK 0x{sak:02X}")

        # Phase 2: Payload bauen
        payload = _build_patient_payload(patient)

        # Phase 3: Schreiben (Sektor 1 = Blöcke 4-6, Sektor 2 = Blöcke 8-10)
        sector_blocks = {
            1: [4, 5, 6],
            2: [8, 9, 10],
        }

        def _write_and_verify(sector, auth_block, blk, data) -> tuple[bool, str]:
            """Ein Block-Write mit Re-Auth-Retry. Wenn der Write-Cycle oder
            der Verify-Read scheitert, einmal re-authentifizieren und
            nochmal versuchen — MIFARE verliert manchmal den Crypto1-State
            wenn ein Befehl zum falschen Zeitpunkt kommt."""
            for attempt in (1, 2):
                ok, detail = _rc522_write_block(blk, data)
                if ok:
                    verify = _rc522_read_block(blk)
                    if verify == data:
                        return (True, "")
                    detail = f"Verify mismatch (got {verify.hex() if verify else 'None'})"
                log.warning(
                    f"RFID-Write: Block {blk} Versuch {attempt} fehlgeschlagen: {detail}"
                )
                if attempt == 1:
                    # Re-Auth für den Sektor — nach einem Fehler kann der
                    # Crypto1-State inkonsistent sein
                    _rc522_stop_crypto()
                    import time as _t2
                    _t2.sleep(0.02)
                    if not _rc522_auth(auth_block, uid_bytes):
                        return (False, f"Re-Auth Sektor {sector} fehlgeschlagen")
            return (False, f"Block {blk}: {detail}")

        try:
            import time as _t3
            for sector_idx, (sector, blocks) in enumerate(sector_blocks.items()):
                auth_block = blocks[0]  # Auth auf ersten Block des Sektors
                # KRITISCH: Vor jedem NEUEN Sektor-Auth zuerst einen
                # KOMPLETTEN HARDWARE-RESET des RC522 + die Karte neu
                # finden. Hintergrund: Nach erfolgreicher Sektor-1-Auth
                # + Operations bleiben RC522-Register und Karten-Crypto1-
                # State so verwoben, dass weder REQA noch WUPA noch
                # einfaches stop_crypto die Karte fuer einen Sektor-2-
                # Auth zurueckholen. Nur ein Soft-Reset des RC522
                # (rc522_init) + neue REQA + Anticoll + Select bringt
                # die Hardware in einen sauberen State, in dem der
                # zweite Sektor-Auth funktioniert.
                #
                # Ohne diesen Reset schlug Sektor-2-Auth still fehl,
                # _rc522_auth meldete trotzdem True (wegen Status2-Bit
                # vom alten Sektor 1), und die Block-8/9/10 Writes
                # gingen ins Nirvana — Block 5/6 (patient_id, vitals)
                # waren neu, aber Block 8/9 (Name) blieben alt.
                # Der User-Bug "Karte schreibt aber alte Daten drauf"
                # waren genau die Name-Blocks aus Sektor 2.
                # Diagnose siehe scripts/rfid_write_diag.py
                # (Phase 4.1 vom 15.04.2026).
                if sector_idx > 0:
                    _rc522_stop_crypto()
                    _rc522_halt()
                    _t3.sleep(0.05)
                    rc522_init()
                    _t3.sleep(0.05)
                    # Karte neu finden — kann ein paar REQA-Cycles brauchen
                    found = False
                    for _attempt in range(20):
                        ok_req, _ = _rc522_request(_PICC_REQIDL)
                        if not ok_req:
                            _t3.sleep(0.05)
                            continue
                        uid5_re = _rc522_anticoll()
                        if uid5_re is None:
                            _t3.sleep(0.05)
                            continue
                        if _rc522_select(uid5_re) is None:
                            _t3.sleep(0.05)
                            continue
                        found = True
                        break
                    if not found:
                        log.warning(f"RFID-Write: Karte nach Reset vor Sektor {sector} nicht wiedergefunden")
                        return (False, f"Karte nach Reset vor Sektor {sector} nicht wiedergefunden")
                if not _rc522_auth(auth_block, uid_bytes):
                    log.warning(f"RFID-Write: Auth fehlgeschlagen auf Sektor {sector}")
                    return (False, f"Auth fehlgeschlagen auf Sektor {sector}")
                log.info(f"RFID-Write: Sektor {sector} authentifiziert (Block {auth_block})")
                for blk in blocks:
                    data = payload.get(blk)
                    if data is None:
                        continue
                    ok, err = _write_and_verify(sector, auth_block, blk, data)
                    if not ok:
                        log.warning(f"RFID-Write: Fehlgeschlagen auf Block {blk}: {err}")
                        return (False, f"Block {blk}: {err}")
                    log.info(f"RFID-Write: Block {blk} OK ({len(data)} bytes)")
            log.info(f"RFID-Write erfolgreich (alle Sektoren): UID {uid_hex}")
            return (True, uid_hex)
        finally:
            _rc522_stop_crypto()
            _rc522_halt()


def rc522_read_patient_from_card(timeout: float = 5.0) -> tuple[dict | None, str]:
    """
    Liest SAFIR-Patientendaten von einer Karte (nur Header + Patient-ID + Triage).
    Gibt ({fields...}, uid_hex) zurück oder (None, fehlermeldung).

    Hält den globalen SPI-Lock während des gesamten Read-Flows.
    """
    import struct
    import time as _t

    if not _rc522_available:
        return (None, "RC522 nicht verfügbar")

    with _spi_lock:
        start = _t.time()
        uid_bytes = None
        while _t.time() - start < timeout:
            ok, _ = _rc522_request(_PICC_REQIDL)
            if ok:
                uid5 = _rc522_anticoll()
                if uid5 is not None:
                    sak = _rc522_select(uid5)
                    if sak is not None:
                        uid_bytes = uid5[:4]
                        break
            _t.sleep(0.1)

        if uid_bytes is None:
            return (None, "Timeout — keine Karte gefunden")

        uid_hex = "".join(f"{b:02X}" for b in uid_bytes)
        try:
            if not _rc522_auth(4, uid_bytes):
                return (None, "Auth fehlgeschlagen")
            b4 = _rc522_read_block(4)
            b5 = _rc522_read_block(5)
            b6 = _rc522_read_block(6)
            if not b4 or not b4[:8] == SAFIR_CARD_MAGIC:
                return (None, "Keine SAFIR-Karte (Magic fehlt)")
            version = b4[8]
            ts = struct.unpack_from("<I", b4, 12)[0]
            patient_id = (b5 or b"").rstrip(b"\x00").decode("ascii", errors="ignore")
            triage_byte = (b6 or b"\x00")[0]
            triage_map = {1: "T1", 2: "T2", 3: "T3", 4: "T4"}
            triage = triage_map.get(triage_byte, "")
            return ({
                "version": version,
                "written_unix": ts,
                "patient_id": patient_id,
                "triage": triage,
                "uid": uid_hex,
            }, uid_hex)
        finally:
            _rc522_stop_crypto()
            _rc522_halt()


def generate_patient_id() -> str:
    """Generiert eine eindeutige Patienten-ID (UUID-basiert, kurz)."""
    return f"PAT-{uuid.uuid4().hex[:8].upper()}"


def generate_rfid_tag() -> str:
    """Generiert eine simulierte RFID-Tag-ID (Fallback ohne RC522)."""
    return f"RFID-{uuid.uuid4().hex[:12].upper()}"


def lookup_by_rfid(rfid_map: dict, tag_id: str) -> str | None:
    """Sucht Patient-ID anhand der RFID-Tag-ID."""
    return rfid_map.get(tag_id)


def create_patient_record(
    name: str,
    triage: str = "",
    rfid_tag_id: str = "",
    device_id: str = "jetson-01",
    created_by: str = "",
) -> dict:
    """Erstellt einen neuen Patientendatensatz mit Grunddaten."""
    from shared.models import PATIENT_SCHEMA
    import copy

    patient = copy.deepcopy(PATIENT_SCHEMA)
    patient["patient_id"] = generate_patient_id()
    patient["timestamp_created"] = datetime.now().isoformat()
    patient["name"] = name
    patient["triage"] = triage
    patient["rfid_tag_id"] = rfid_tag_id or generate_rfid_tag()
    patient["device_id"] = device_id
    patient["created_by"] = created_by
    patient["flow_status"] = "registered"
    patient["current_role"] = "phase0"

    # Initiales Timeline-Event
    patient["timeline"].append({
        "time": datetime.now().isoformat(),
        "role": "phase0",
        "event": "registered",
        "details": f"Patient registriert von {created_by or 'Unbekannt'} ({device_id})",
    })

    return patient
