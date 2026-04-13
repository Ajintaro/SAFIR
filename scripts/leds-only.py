#!/usr/bin/env python3
"""Nur LEDs — kein OLED. Halte einen Taster, beide LEDs gehen an."""
import time
import warnings
warnings.filterwarnings("ignore")
import Jetson.GPIO as GPIO

GPIO.setmode(GPIO.BOARD)
GPIO.setup(11, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(26, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(13, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(15, GPIO.OUT, initial=GPIO.LOW)

print("Halte einen Taster — beide LEDs sollten angehen. 30 Sekunden.\n")
last = None
start = time.monotonic()
try:
    while time.monotonic() - start < 30:
        pressed = GPIO.input(11) == GPIO.LOW or GPIO.input(26) == GPIO.LOW
        GPIO.output(13, GPIO.HIGH if pressed else GPIO.LOW)
        GPIO.output(15, GPIO.HIGH if pressed else GPIO.LOW)
        if pressed != last:
            print(f"  LEDs {'AN' if pressed else 'AUS'}")
            last = pressed
        time.sleep(0.02)
finally:
    GPIO.output(13, GPIO.LOW)
    GPIO.output(15, GPIO.LOW)
    GPIO.cleanup()
print("Fertig.")
