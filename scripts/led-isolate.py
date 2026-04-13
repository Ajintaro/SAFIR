#!/usr/bin/env python3
"""LED-Isolations-Test: schaltet jede LED einzeln, mit klarer Zeit-Marke.

Beobachte genau: welche physische LED leuchtet während welcher Phase?
Wenn eine LED auch in der OFF-Phase leuchtet → sie hängt nicht am BC547
sondern dauerhaft auf 5V (oder anderswo).
"""
import time, warnings
warnings.filterwarnings("ignore")
import Jetson.GPIO as GPIO

LED_A = 13
LED_B = 15

GPIO.setmode(GPIO.BOARD)
GPIO.setup(LED_A, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(LED_B, GPIO.OUT, initial=GPIO.LOW)

def phase(label, a, b, secs):
    GPIO.output(LED_A, GPIO.HIGH if a else GPIO.LOW)
    GPIO.output(LED_B, GPIO.HIGH if b else GPIO.LOW)
    print(f"  {label:35}  Pin13={'AN ' if a else 'AUS'}  Pin15={'AN ' if b else 'AUS'}")
    time.sleep(secs)

try:
    print("\n=== ISOLATIONS-TEST ===")
    print("Beobachte welche LED in welcher Phase leuchtet.\n")

    phase("0) Beide AUS (Baseline)",          False, False, 4)
    phase("1) NUR Pin 13 an",                 True,  False, 4)
    phase("2) Beide AUS",                     False, False, 3)
    phase("3) NUR Pin 15 an",                 False, True,  4)
    phase("4) Beide AUS",                     False, False, 3)
    phase("5) Beide AN",                      True,  True,  4)
    phase("6) Beide AUS — Endzustand",        False, False, 1)

    print("\nFertig.")
finally:
    GPIO.output(LED_A, GPIO.LOW)
    GPIO.output(LED_B, GPIO.LOW)
    GPIO.cleanup()
