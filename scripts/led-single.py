#!/usr/bin/env python3
"""Einzeln-Test: nur Pin 11, dann nur Pin 13."""
import sys, time, warnings
warnings.filterwarnings("ignore")
import Jetson.GPIO as GPIO

pin = int(sys.argv[1]) if len(sys.argv) > 1 else 11
GPIO.setmode(GPIO.BOARD)
GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)

print(f"Pin {pin} blinkt 10x (1 Sekunde)")
try:
    for i in range(10):
        GPIO.output(pin, GPIO.HIGH)
        print(f"  [{i+1}/10] AN")
        time.sleep(0.5)
        GPIO.output(pin, GPIO.LOW)
        print(f"  [{i+1}/10] AUS")
        time.sleep(0.5)
finally:
    GPIO.output(pin, GPIO.LOW)
    GPIO.cleanup()
