#!/usr/bin/env python3
"""Liest nur Pin 40 für 10 Sekunden — prüft ob er ohne Last sauber HIGH ist."""
import time, warnings
warnings.filterwarnings("ignore")
import Jetson.GPIO as GPIO

GPIO.setmode(GPIO.BOARD)
GPIO.setup(40, GPIO.IN, pull_up_down=GPIO.PUD_UP)

print("Pin 40 (sollte HIGH sein wenn nichts dran):")
last = None
start = time.monotonic()
try:
    while time.monotonic() - start < 10:
        v = GPIO.input(40)
        if v != last:
            t = time.monotonic() - start
            print(f"  t={t:5.2f}s   Pin40={'HIGH' if v else 'LOW'}")
            last = v
        time.sleep(0.05)
finally:
    GPIO.cleanup()
print("Fertig.")
