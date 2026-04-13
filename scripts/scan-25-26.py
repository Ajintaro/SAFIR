#!/usr/bin/env python3
"""Scannt nur Pin 25 und Pin 26 für 20 Sekunden."""
import time, warnings
warnings.filterwarnings("ignore")
import Jetson.GPIO as GPIO

GPIO.setmode(GPIO.BOARD)
GPIO.setup(26, GPIO.IN, pull_up_down=GPIO.PUD_UP)

print("Pin 26 Überwachung — 20 Sekunden")
print("Pin 25 ist GND (kein GPIO, nicht überwachbar)")
print("Drücke den Taster mehrmals\n")

state = GPIO.input(26)
print(f"  Idle: Pin26={'HIGH' if state else 'LOW'}\n")

start = time.monotonic()
events = 0
try:
    while time.monotonic() - start < 20:
        v = GPIO.input(26)
        if v != state:
            t = time.monotonic() - start
            arrow = "↓ LOW (gedrückt)" if v == 0 else "↑ HIGH (losgelassen)"
            print(f"  t={t:5.2f}s   Pin 26  {arrow}")
            state = v
            if v == 0:
                events += 1
        time.sleep(0.005)

    print(f"\nGesamt: {events} Drücke erkannt")
finally:
    GPIO.cleanup()
print("Fertig.")
