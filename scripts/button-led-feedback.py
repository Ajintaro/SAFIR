#!/usr/bin/env python3
"""Taster-Rückmeldung: jeder gedrückte Taster lässt seine LED leuchten.

Taster A (Pin 26) → LED Pin 13 (BC547) — externer 150Ω Pull-Up an Pin 17
Taster B (Pin 11) → LED Pin 15 (BC547) — interner Pull-Up reicht

Strg+C zum Beenden.
"""
import time
import warnings
warnings.filterwarnings("ignore")

import Jetson.GPIO as GPIO

PAIRS = [
    ("A",  26, 15),
    ("B",  11, 13),
]

GPIO.setmode(GPIO.BOARD)
for _, btn, led in PAIRS:
    GPIO.setup(btn, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(led, GPIO.OUT, initial=GPIO.LOW)

print("Taster-Rückmeldung aktiv")
for name, btn, led in PAIRS:
    print(f"  {name}: Taster Pin {btn} → LED Pin {led}")
print("\nStrg+C zum Beenden\n")

state = {name: False for name, _, _ in PAIRS}

try:
    while True:
        for name, btn, led in PAIRS:
            pressed = GPIO.input(btn) == GPIO.LOW
            GPIO.output(led, GPIO.HIGH if pressed else GPIO.LOW)

            if pressed != state[name]:
                print(f"{name:5} {'AN ' if pressed else 'AUS'}")
                state[name] = pressed

        time.sleep(0.02)

except KeyboardInterrupt:
    print("\nAbgebrochen")
finally:
    for _, _, led in PAIRS:
        GPIO.output(led, GPIO.LOW)
    GPIO.cleanup()
