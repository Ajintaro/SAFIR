#!/usr/bin/env python3
"""Sucht den richtigen Input-Pin für einen Taster.

Setzt alle als Input geeigneten Pins mit Pull-Up und loggt jede Flanke.
User drückt im Sekundentakt einen Taster — der Pin der Flanken zeigt ist der richtige.

Ausgeschlossen: Pin 13/15 (LED-Outputs), 7/19/21/22/24 (RC522), 3/5 (I2C OLED).
"""
import time, warnings
warnings.filterwarnings("ignore")
import Jetson.GPIO as GPIO

CANDIDATES = [11, 12, 16, 18, 26, 29, 31, 32, 33, 35, 36, 37, 38, 40]

GPIO.setmode(GPIO.BOARD)
for p in CANDIDATES:
    GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# Initial-Snapshot
state = {p: GPIO.input(p) for p in CANDIDATES}

print(f"Überwache {len(CANDIDATES)} Pins für 30 Sekunden")
print("Drücke jetzt im Sekundentakt EINEN Taster\n")

# Idle-State zeigen
high = sorted(p for p, v in state.items() if v == 1)
low  = sorted(p for p, v in state.items() if v == 0)
print(f"  Idle HIGH: {high}")
print(f"  Idle LOW : {low}\n")

start = time.monotonic()
counts = {p: 0 for p in CANDIDATES}

try:
    while time.monotonic() - start < 30:
        for p in CANDIDATES:
            v = GPIO.input(p)
            if v != state[p]:
                t = time.monotonic() - start
                arrow = "↓ LOW " if v == 0 else "↑ HIGH"
                print(f"  t={t:5.2f}s   Pin {p:2d}  {arrow}")
                state[p] = v
                if v == 0:
                    counts[p] += 1
        time.sleep(0.005)

    print("\nFlanken-Zähler (LOW-Events = Drücke):")
    for p in sorted(counts, key=lambda x: -counts[x]):
        if counts[p] > 0:
            print(f"  Pin {p:2d}: {counts[p]} Drücke")

finally:
    GPIO.cleanup()
print("\nFertig.")
