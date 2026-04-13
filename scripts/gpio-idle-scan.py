#!/usr/bin/env python3
"""Scannt alle freien GPIO-Pins und zeigt Idle-Zustand mit Pull-Up.

Hilft zu finden welche Pins für Taster geeignet sind (= idle HIGH).
WICHTIG: Vorher physisch alle Taster abklemmen!
"""
import warnings
warnings.filterwarnings("ignore")
import Jetson.GPIO as GPIO

# Pin 11 ist belegt mit OLED-Taster. Pin 13/15 sind LED-Outputs.
# Restliche freie Inputs aus dem 40-Pin Header:
PINS_TO_TEST = [12, 16, 18, 22, 26, 29, 31, 32, 33, 35, 36, 37, 38, 40]

GPIO.setmode(GPIO.BOARD)
results = {}
for pin in PINS_TO_TEST:
    try:
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        results[pin] = GPIO.input(pin)
    except Exception as e:
        results[pin] = f"ERR: {e}"

print(f"{'Pin':>4}  Idle-Zustand")
print("-" * 25)
for pin, val in results.items():
    if isinstance(val, int):
        print(f"{pin:>4}  {'HIGH ✓' if val else 'LOW (floating?)'}")
    else:
        print(f"{pin:>4}  {val}")

GPIO.cleanup()
