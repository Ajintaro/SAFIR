#!/usr/bin/env python3
"""LED-Wechselblinken mit verschiedenen Frequenzen.
Pin 13 + Pin 15 über BC547.
"""
import time
import warnings
warnings.filterwarnings("ignore")

import Jetson.GPIO as GPIO

LED_1 = 13
LED_2 = 15

GPIO.setmode(GPIO.BOARD)
GPIO.setup(LED_1, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(LED_2, GPIO.OUT, initial=GPIO.LOW)

def alternate(period, cycles, label):
    """Zwei LEDs abwechselnd toggeln. period = Sekunden pro Halbperiode."""
    print(f"\n{label}: {1/period/2:.1f} Hz — {cycles} Zyklen")
    for i in range(cycles):
        GPIO.output(LED_1, GPIO.HIGH)
        GPIO.output(LED_2, GPIO.LOW)
        time.sleep(period)
        GPIO.output(LED_1, GPIO.LOW)
        GPIO.output(LED_2, GPIO.HIGH)
        time.sleep(period)

try:
    alternate(1.0,  4,  "LANGSAM")     # 0.5 Hz
    alternate(0.5,  6,  "MITTEL")      # 1 Hz
    alternate(0.25, 12, "ZÜGIG")       # 2 Hz
    alternate(0.1,  20, "SCHNELL")     # 5 Hz
    alternate(0.05, 30, "SEHR SCHNELL")# 10 Hz
    alternate(0.02, 50, "FLIRREN")     # 25 Hz

    print("\nFinale: Beschleunigung von langsam nach schnell")
    delay = 0.5
    while delay > 0.02:
        GPIO.output(LED_1, GPIO.HIGH); GPIO.output(LED_2, GPIO.LOW)
        time.sleep(delay)
        GPIO.output(LED_1, GPIO.LOW); GPIO.output(LED_2, GPIO.HIGH)
        time.sleep(delay)
        delay *= 0.92

    print("Fertig.")

except KeyboardInterrupt:
    print("\nAbgebrochen")
finally:
    GPIO.output(LED_1, GPIO.LOW)
    GPIO.output(LED_2, GPIO.LOW)
    GPIO.cleanup()
