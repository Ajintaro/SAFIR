#!/usr/bin/env python3
"""RC522 RFID-Leser Hardwaretest auf Jetson Orin Nano.

Verkabelung:
  VCC=Pin17(3.3V), RST=Pin7, GND=Pin20, MISO=Pin21,
  MOSI=Pin19, SCK=Pin23, NSS=Pin24(CS0)

Beenden mit Strg+C.
"""

import signal
import sys
import time

# GPIO-Warnung unterdrücken (Jetson.GPIO)
import warnings
warnings.filterwarnings("ignore")

def test_spi_device():
    """Prüft ob /dev/spidev0.0 ansprechbar ist."""
    import spidev
    spi = spidev.SpiDev()
    try:
        spi.open(0, 0)
        spi.max_speed_hz = 1000000
        print(f"[OK] SPI0.0 geöffnet (max {spi.max_speed_hz // 1000} kHz)")
        # Testbyte senden
        resp = spi.xfer2([0x00])
        print(f"[OK] SPI-Kommunikation funktioniert (Response: {resp})")
        spi.close()
        return True
    except Exception as e:
        print(f"[FEHLER] SPI: {e}")
        return False


def test_rc522():
    """Testet den RC522 über die mfrc522-Bibliothek."""
    from mfrc522 import MFRC522, SimpleMFRC522
    import RPi.GPIO as GPIO

    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BOARD)

    # BOARD-Modus Pin 7 = RST, explizit übergeben
    rc522 = MFRC522(bus=0, device=0, spd=1000000, pin_mode=GPIO.BOARD, pin_rst=7)
    reader = SimpleMFRC522()
    print("[OK] RC522 initialisiert (SPI0, CS0, RST=BOARD Pin 7)")

    # Firmware-Version direkt aus dem MFRC522-Register lesen
    ver = rc522.Read_MFRC522(0x37)  # VersionReg
    if ver == 0x92:
        print(f"[OK] RC522 Firmware: v2.0 (0x{ver:02X})")
    elif ver == 0x91:
        print(f"[OK] RC522 Firmware: v1.0 (0x{ver:02X})")
    elif ver == 0x88:
        print(f"[OK] Clone-Chip erkannt (0x{ver:02X})")
    elif ver == 0x00 or ver == 0xFF:
        print(f"[FEHLER] Keine Antwort vom RC522 (0x{ver:02X}) — Verkabelung prüfen!")
        GPIO.cleanup()
        return False
    else:
        print(f"[INFO] Unbekannte Firmware-Version: 0x{ver:02X}")

    print()
    print("Halte jetzt eine RFID-Karte/Tag an den Leser...")
    print("(Strg+C zum Beenden)")
    print()

    try:
        while True:
            tag_id, text = reader.read_no_block()
            if tag_id:
                print(f"  TAG ERKANNT!")
                print(f"  ID:   {tag_id}")
                print(f"  Text: '{text.strip()}'" if text.strip() else "  Text: (leer)")
                print()
                time.sleep(1)  # Entprellen
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\nBeendet.")
    finally:
        GPIO.cleanup()


if __name__ == "__main__":
    print("=" * 50)
    print("SAFIR — RC522 RFID Hardwaretest")
    print("=" * 50)
    print()

    # Schritt 1: SPI prüfen
    print("--- SPI-Test ---")
    if not test_spi_device():
        sys.exit(1)

    print()

    # Schritt 2: RC522 testen
    print("--- RC522-Test ---")
    test_rc522()
