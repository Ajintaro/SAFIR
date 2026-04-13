#!/usr/bin/env python3
"""LED Blink-Test für die 2 Taster-LEDs über BC547.

Pin 13 und Pin 15 (BOARD) → BC547 Basis → LED schaltet gegen GND.
HIGH = Transistor leitet = LED an.
"""
import time
import warnings
warnings.filterwarnings("ignore")

import Jetson.GPIO as GPIO

LED_1 = 13  # erste LED über BC547
LED_2 = 15  # zweite LED über BC547

GPIO.setmode(GPIO.BOARD)
GPIO.setup(LED_1, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(LED_2, GPIO.OUT, initial=GPIO.LOW)

print("LED Blink-Test — Pin 11 & Pin 13 (BC547)")
print("Strg+C zum Beenden\n")

try:
    # Phase 1: beide gleichzeitig blinken
    print("Phase 1: beide LEDs synchron (5x)")
    for i in range(5):
        GPIO.output(LED_1, GPIO.HIGH)
        GPIO.output(LED_2, GPIO.HIGH)
        print(f"  [{i+1}/5] AN")
        time.sleep(0.5)
        GPIO.output(LED_1, GPIO.LOW)
        GPIO.output(LED_2, GPIO.LOW)
        print(f"  [{i+1}/5] AUS")
        time.sleep(0.5)

    # Phase 2: abwechselnd
    print("\nPhase 2: abwechselnd (10x)")
    for i in range(10):
        GPIO.output(LED_1, GPIO.HIGH)
        GPIO.output(LED_2, GPIO.LOW)
        print(f"  [{i+1}/10] LED1=AN  LED2=AUS")
        time.sleep(0.3)
        GPIO.output(LED_1, GPIO.LOW)
        GPIO.output(LED_2, GPIO.HIGH)
        print(f"  [{i+1}/10] LED1=AUS LED2=AN")
        time.sleep(0.3)

    # Phase 3: Endzustand beide aus
    GPIO.output(LED_1, GPIO.LOW)
    GPIO.output(LED_2, GPIO.LOW)
    print("\nFertig — beide LEDs AUS")

except KeyboardInterrupt:
    print("\nAbgebrochen")
finally:
    GPIO.output(LED_1, GPIO.LOW)
    GPIO.output(LED_2, GPIO.LOW)
    GPIO.cleanup()
