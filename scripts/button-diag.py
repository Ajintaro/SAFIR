#!/usr/bin/env python3
"""Diagnose: liest Pin 29 und Pin 11 kontinuierlich (10 Hz, 15 Sekunden)."""
import time, warnings
warnings.filterwarnings("ignore")
import Jetson.GPIO as GPIO

GPIO.setmode(GPIO.BOARD)
GPIO.setup(26, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(11, GPIO.IN, pull_up_down=GPIO.PUD_UP)

print("Lese Pin 26 (PWR) und Pin 11 (OLED) — 15 Sekunden")
print("Erwartet im Idle: HIGH/HIGH    Bei Druck: LOW")
print("Drück nacheinander beide Taster\n")

start = time.monotonic()
last = (None, None)
try:
    while time.monotonic() - start < 15:
        s26v = GPIO.input(26)
        s11 = GPIO.input(11)
        if (s26v, s11) != last:
            t = time.monotonic() - start
            print(f"  t={t:5.2f}s   Pin26={'HIGH' if s26v else 'LOW '}   Pin11={'HIGH' if s11 else 'LOW '}")
            last = (s26v, s11)
        time.sleep(0.05)
finally:
    GPIO.cleanup()
print("Fertig.")
