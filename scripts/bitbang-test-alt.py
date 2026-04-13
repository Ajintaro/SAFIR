#!/usr/bin/env python3
"""Bit-Bang SPI Test — ALTERNATIVE PIN-BELEGUNG.
RST=29, MOSI=31, MISO=33, SCK=35, CS=37, VCC=17, GND=20
"""
import time
import warnings
warnings.filterwarnings("ignore")
import Jetson.GPIO as GPIO

# Alternative Belegung (rechte Seite, Pins 29-37)
CS   = 37  # SDA/NSS (lila)
SCK  = 35  # (schwarz)
MOSI = 31  # (blau)
MISO = 33  # (weiß)
RST  = 29  # (rot)

GPIO.setmode(GPIO.BOARD)
GPIO.setup(CS, GPIO.OUT, initial=GPIO.HIGH)
GPIO.setup(SCK, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(MOSI, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(RST, GPIO.OUT, initial=GPIO.HIGH)
GPIO.setup(MISO, GPIO.IN)

def spi_transfer_byte(byte_out):
    byte_in = 0
    for i in range(8):
        bit = (byte_out >> (7 - i)) & 1
        GPIO.output(MOSI, bit)
        time.sleep(0.0001)
        GPIO.output(SCK, GPIO.HIGH)
        time.sleep(0.0001)
        byte_in = (byte_in << 1) | GPIO.input(MISO)
        GPIO.output(SCK, GPIO.LOW)
        time.sleep(0.0001)
    return byte_in

def rc522_read_reg(reg):
    GPIO.output(CS, GPIO.LOW)
    time.sleep(0.001)
    addr = ((reg << 1) & 0x7E) | 0x80
    spi_transfer_byte(addr)
    val = spi_transfer_byte(0x00)
    GPIO.output(CS, GPIO.HIGH)
    time.sleep(0.001)
    return val

try:
    # Pin-Status vor Reset
    print("=== Alternative Belegung (Pins 29-37) ===")
    print(f"  RST  Pin {RST} (rot)")
    print(f"  MOSI Pin {MOSI} (blau)")
    print(f"  MISO Pin {MISO} (weiß)")
    print(f"  SCK  Pin {SCK} (schwarz)")
    print(f"  CS   Pin {CS} (lila)")

    # RST toggeln
    print("\nRST Toggle...")
    GPIO.output(RST, GPIO.LOW)
    time.sleep(0.1)
    GPIO.output(RST, GPIO.HIGH)
    time.sleep(0.1)

    print(f"\nMISO nach Reset: {'HIGH' if GPIO.input(MISO) else 'LOW'}")

    # VersionReg lesen
    ver = rc522_read_reg(0x37)
    print(f"\nVersionReg (0x37): 0x{ver:02X}")

    if ver == 0x92:
        print(">>> RC522 v2.0 ERKANNT! <<<")
    elif ver == 0x91:
        print(">>> RC522 v1.0 ERKANNT! <<<")
    elif ver == 0x88:
        print(">>> Clone-Chip ERKANNT! <<<")
    elif ver in (0x00, 0xFF):
        print(">>> KEINE Antwort <<<")
    else:
        print(f">>> Unbekannte Version <<<")

    # Weitere Register
    print(f"\nWeitere Register:")
    for reg, name in [(0x01, "CommandReg"), (0x04, "ComIEnReg"),
                      (0x05, "DivIEnReg"), (0x0A, "TxControlReg")]:
        val = rc522_read_reg(reg)
        print(f"  {name} (0x{reg:02X}): 0x{val:02X}")

finally:
    GPIO.cleanup()
