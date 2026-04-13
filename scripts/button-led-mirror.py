#!/usr/bin/env python3
"""Taster spiegelt LED: solange Power-Taster gedrückt → LED an.

Power-Taster: Pin 29 (GPIO01) → GND, Pull-Up intern
Power-LED:    Pin 13 → BC547 Basis (HIGH = LED an)

Strg+C zum Beenden.
"""
import time
import warnings
warnings.filterwarnings("ignore")

import Jetson.GPIO as GPIO

BUTTON = 29
LED    = 13

GPIO.setmode(GPIO.BOARD)
GPIO.setup(BUTTON, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(LED, GPIO.OUT, initial=GPIO.LOW)

print(f"Taster Pin {BUTTON} → LED Pin {LED}")
print("Drücken = LED an, Loslassen = LED aus")
print("Strg+C zum Beenden\n")

last = None
try:
    while True:
        pressed = GPIO.input(BUTTON) == GPIO.LOW
        GPIO.output(LED, GPIO.HIGH if pressed else GPIO.LOW)

        if pressed != last:
            print("LED AN " if pressed else "LED AUS")
            last = pressed

        time.sleep(0.02)  # 50 Hz Polling, kein spürbares Lag

except KeyboardInterrupt:
    print("\nAbgebrochen")
finally:
    GPIO.output(LED, GPIO.LOW)
    GPIO.cleanup()
