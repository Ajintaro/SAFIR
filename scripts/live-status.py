#!/usr/bin/env python3
"""Live-Status: zeigt jede 0.5s den aktuellen Zustand von Tastern und LEDs.

Drück die Taster während es läuft und beobachte ob die Werte umschalten.
Beendet mit Strg+C.
"""
import time, warnings
warnings.filterwarnings("ignore")
import Jetson.GPIO as GPIO

BTN_A, LED_A = 26, 15  # Taster A → LED Pin 15
BTN_B, LED_B = 11, 13  # Taster B → LED Pin 13

GPIO.setmode(GPIO.BOARD)
GPIO.setup(BTN_A, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(BTN_B, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(LED_A, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(LED_B, GPIO.OUT, initial=GPIO.LOW)

print(f"Taster A=Pin{BTN_A} → LED Pin{LED_A}")
print(f"Taster B=Pin{BTN_B} → LED Pin{LED_B}")
print("Drück die Taster — Status wird jede 0.5s angezeigt\n")
print(f"{'Zeit':>6}  {'BtnA':>5}  {'BtnB':>5}  {'LedA':>5}  {'LedB':>5}")
print("-" * 40)

start = time.monotonic()
try:
    while True:
        # Schnelles Polling für LED-Steuerung
        for _ in range(50):
            a_pressed = GPIO.input(BTN_A) == GPIO.LOW
            b_pressed = GPIO.input(BTN_B) == GPIO.LOW
            GPIO.output(LED_A, GPIO.HIGH if a_pressed else GPIO.LOW)
            GPIO.output(LED_B, GPIO.HIGH if b_pressed else GPIO.LOW)
            time.sleep(0.01)

        # Status-Snapshot alle 0.5s
        t = time.monotonic() - start
        print(f"{t:6.1f}  {'LOW' if a_pressed else 'HIGH':>5}  "
              f"{'LOW' if b_pressed else 'HIGH':>5}  "
              f"{'AN' if a_pressed else 'AUS':>5}  "
              f"{'AN' if b_pressed else 'AUS':>5}")

except KeyboardInterrupt:
    print("\nAbgebrochen")
finally:
    GPIO.output(LED_A, GPIO.LOW)
    GPIO.output(LED_B, GPIO.LOW)
    GPIO.cleanup()
