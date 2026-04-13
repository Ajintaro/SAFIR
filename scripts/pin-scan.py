#!/usr/bin/env python3
"""Scannt alle relevanten Pins — Zustand lesen + CS-Toggle-Reaktion prüfen."""
import time
import warnings
warnings.filterwarnings("ignore")
import Jetson.GPIO as GPIO

# Aktuelle Verkabelung
PINS = {
    7:  "RST (rot)",
    19: "MOSI (blau)",
    21: "MISO (weiß)",
    22: "SCK (schwarz)",
    24: "SDA/CS (lila)",
}

GPIO.setmode(GPIO.BOARD)

# Alle als Input lesen
for pin in PINS:
    GPIO.setup(pin, GPIO.IN)

print("=== Pin-Zustand (alle als Input) ===")
for pin, name in sorted(PINS.items()):
    val = GPIO.input(pin)
    print(f"  Pin {pin:2d} [{name:20s}]: {'HIGH' if val else 'LOW'}")

GPIO.cleanup()

# Jetzt CS toggeln und MISO beobachten
print("\n=== CS-Toggle Test ===")
GPIO.setmode(GPIO.BOARD)
GPIO.setup(24, GPIO.OUT, initial=GPIO.HIGH)  # CS
GPIO.setup(22, GPIO.OUT, initial=GPIO.LOW)   # SCK
GPIO.setup(19, GPIO.OUT, initial=GPIO.LOW)   # MOSI
GPIO.setup(7,  GPIO.OUT, initial=GPIO.HIGH)  # RST
GPIO.setup(21, GPIO.IN)                       # MISO

print(f"  MISO vor CS-LOW:  {'HIGH' if GPIO.input(21) else 'LOW'}")
GPIO.output(24, GPIO.LOW)
time.sleep(0.01)
print(f"  MISO nach CS-LOW: {'HIGH' if GPIO.input(21) else 'LOW'}")
GPIO.output(24, GPIO.HIGH)
time.sleep(0.01)
print(f"  MISO nach CS-HIGH: {'HIGH' if GPIO.input(21) else 'LOW'}")

# RST toggeln und MISO beobachten
print("\n=== RST-Toggle Test ===")
GPIO.output(7, GPIO.LOW)
time.sleep(0.05)
print(f"  MISO bei RST LOW:  {'HIGH' if GPIO.input(21) else 'LOW'}")
GPIO.output(7, GPIO.HIGH)
time.sleep(0.05)
print(f"  MISO bei RST HIGH: {'HIGH' if GPIO.input(21) else 'LOW'}")

# MOSI durchschalten und MISO beobachten (Kurzschluss-Check)
print("\n=== MOSI→MISO Kurzschluss-Check ===")
GPIO.output(19, GPIO.HIGH)
time.sleep(0.001)
miso_h = GPIO.input(21)
GPIO.output(19, GPIO.LOW)
time.sleep(0.001)
miso_l = GPIO.input(21)
print(f"  MOSI HIGH → MISO: {'HIGH' if miso_h else 'LOW'}")
print(f"  MOSI LOW  → MISO: {'HIGH' if miso_l else 'LOW'}")
if miso_h and not miso_l:
    print("  ⚠ MISO folgt MOSI — möglicherweise Kurzschluss!")

GPIO.cleanup()
