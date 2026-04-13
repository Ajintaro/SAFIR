#!/usr/bin/env python3
"""Pin 26 Test mit periodischem Reset.

Schaltet Pin 26 alle 100ms kurz auf OUTPUT HIGH (zwingt HIGH), dann zurück
auf INPUT mit Pull-Up. So überschreiben wir den klebrigen Floating-LOW.
"""
import time, warnings
warnings.filterwarnings("ignore")
import Jetson.GPIO as GPIO

GPIO.setmode(GPIO.BOARD)

print("Pin 26 mit aktivem Reset — 20 Sekunden")
print("Drücke den Taster mehrmals\n")

state = None
events = 0
start = time.monotonic()

try:
    while time.monotonic() - start < 20:
        # Aktiv HIGH treiben — überschreibt jeden klebrigen LOW
        GPIO.setup(26, GPIO.OUT, initial=GPIO.HIGH)
        time.sleep(0.001)
        # Zurück auf Input mit Pull-Up
        GPIO.setup(26, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        time.sleep(0.005)
        v = GPIO.input(26)

        if v != state:
            t = time.monotonic() - start
            arrow = "↓ LOW (gedrückt)" if v == 0 else "↑ HIGH (idle)"
            print(f"  t={t:5.2f}s   Pin 26  {arrow}")
            state = v
            if v == 0:
                events += 1

        time.sleep(0.02)

    print(f"\nGesamt: {events} Drücke erkannt")
finally:
    GPIO.cleanup()
print("Fertig.")
