#!/usr/bin/env python3
"""Power-Taster Test an Pin 37 (GPIO14) gegen Pin 39 (GND).

Kurzer Druck → Meldung
Langer Druck (>= 3s) → shutdown -h now
Strg+C zum Beenden.
"""
import time
import warnings
import subprocess
warnings.filterwarnings("ignore")

import Jetson.GPIO as GPIO

BUTTON = 37           # GPIO14, BOARD-Pin 37
LONG_PRESS_SEC = 3.0  # ab 3 Sekunden = Shutdown
DEBOUNCE_SEC = 0.05

GPIO.setmode(GPIO.BOARD)
GPIO.setup(BUTTON, GPIO.IN, pull_up_down=GPIO.PUD_UP)

def is_pressed():
    return GPIO.input(BUTTON) == GPIO.LOW

print("Power-Taster Test — Pin 29 (GPIO01) → GND")
print(f"Kurz drücken = Meldung, lange drücken (>= {LONG_PRESS_SEC}s) = Shutdown")
print("Strg+C zum Beenden\n")

try:
    last_state = False
    press_start = None

    while True:
        pressed = is_pressed()

        # Flanke: nicht-gedrückt → gedrückt
        if pressed and not last_state:
            press_start = time.monotonic()
            print("→ gedrückt")

        # Flanke: gedrückt → losgelassen
        elif not pressed and last_state:
            duration = time.monotonic() - press_start
            print(f"→ losgelassen nach {duration:.2f}s")
            if duration >= LONG_PRESS_SEC:
                print(f"\nLanger Druck erkannt — würde jetzt SHUTDOWN auslösen")
                print("(Test-Modus: kein echter Shutdown — auskommentiert)")
                # subprocess.run(["sudo", "shutdown", "-h", "now"])
            else:
                print("(kurzer Druck)")
            press_start = None

        # Während gedrückt: Live-Countdown bis Long-Press
        elif pressed and press_start is not None:
            elapsed = time.monotonic() - press_start
            if elapsed >= LONG_PRESS_SEC and int(elapsed * 2) % 2 == 0:
                print(f"  ... {elapsed:.1f}s — SHUTDOWN-Schwelle erreicht (loslassen löst aus)")

        last_state = pressed
        time.sleep(DEBOUNCE_SEC)

except KeyboardInterrupt:
    print("\nAbgebrochen")
finally:
    GPIO.cleanup()
