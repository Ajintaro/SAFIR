#!/usr/bin/env python3
"""Bit-Bang SPI Test für RC522 — ohne SPI-Controller.
Liest VersionReg (0x37) direkt über GPIO-Pins.
"""
import time
import warnings
warnings.filterwarnings("ignore")

import Jetson.GPIO as GPIO

# Pin-Belegung (BOARD-Modus)
CS   = 24  # SDA/NSS
SCK  = 22
MOSI = 19
MISO = 21
RST  = 7

GPIO.setmode(GPIO.BOARD)
GPIO.setup(CS, GPIO.OUT, initial=GPIO.HIGH)
GPIO.setup(SCK, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(MOSI, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(RST, GPIO.OUT, initial=GPIO.HIGH)
GPIO.setup(MISO, GPIO.IN)

def spi_transfer_byte(byte_out):
    """Sendet 1 Byte MSB-first, liest gleichzeitig 1 Byte."""
    byte_in = 0
    for i in range(8):
        # MOSI setzen
        bit = (byte_out >> (7 - i)) & 1
        GPIO.output(MOSI, bit)
        time.sleep(0.0001)
        # SCK HIGH → Daten takten
        GPIO.output(SCK, GPIO.HIGH)
        time.sleep(0.0001)
        # MISO lesen
        byte_in = (byte_in << 1) | GPIO.input(MISO)
        # SCK LOW
        GPIO.output(SCK, GPIO.LOW)
        time.sleep(0.0001)
    return byte_in

def rc522_read_reg(reg):
    """Liest ein RC522-Register (Adresse wird als (reg<<1)|0x80 gesendet)."""
    GPIO.output(CS, GPIO.LOW)
    time.sleep(0.001)
    addr = ((reg << 1) & 0x7E) | 0x80  # Lese-Bit setzen
    spi_transfer_byte(addr)
    val = spi_transfer_byte(0x00)
    GPIO.output(CS, GPIO.HIGH)
    time.sleep(0.001)
    return val

try:
    # RST toggeln
    print("RST Toggle...")
    GPIO.output(RST, GPIO.LOW)
    time.sleep(0.1)
    GPIO.output(RST, GPIO.HIGH)
    time.sleep(0.1)

    # Pin-Status prüfen
    print(f"\nPin-Status:")
    print(f"  MISO (Pin {MISO}): {'HIGH' if GPIO.input(MISO) else 'LOW'}")
    print(f"  CS   (Pin {CS}):  HIGH (idle)")
    print(f"  RST  (Pin {RST}):   HIGH (active)")

    # VersionReg lesen
    ver = rc522_read_reg(0x37)
    print(f"\nVersionReg (0x37): 0x{ver:02X}")

    if ver == 0x92:
        print("→ RC522 v2.0 erkannt!")
    elif ver == 0x91:
        print("→ RC522 v1.0 erkannt!")
    elif ver == 0x88:
        print("→ Clone-Chip erkannt!")
    elif ver in (0x00, 0xFF):
        print("→ KEINE Antwort — RC522 kommuniziert nicht")
    else:
        print(f"→ Unbekannte Version")

    # Mehrere Register lesen zum Vergleich
    print(f"\nWeitere Register:")
    for reg, name in [(0x01, "CommandReg"), (0x04, "ComIEnReg"), (0x05, "DivIEnReg"), (0x0A, "TxControlReg")]:
        val = rc522_read_reg(reg)
        print(f"  {name} (0x{reg:02X}): 0x{val:02X}")

finally:
    GPIO.cleanup()
