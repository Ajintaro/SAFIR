#!/usr/bin/env python3
"""Allereinfachster Test: Halte einen Taster gedrückt, sieh die LED und OLED."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import Jetson.GPIO as GPIO
from PIL import Image, ImageDraw
from jetson.oled import OledMenu, WIDTH, HEIGHT, FONT_LG

# OLED init
oled = OledMenu()
oled.init_hardware()

# GPIO init
GPIO.setmode(GPIO.BOARD)
GPIO.setup(11, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(26, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(13, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(15, GPIO.OUT, initial=GPIO.LOW)


def show(text):
    img = Image.new("1", (WIDTH, HEIGHT), 0)
    d = ImageDraw.Draw(img)
    d.text((20, 24), text, font=FONT_LG, fill=1)
    oled._display_image(img)


print("Halte einen Taster gedrückt — irgendeinen. 30 Sekunden Test.")
print("Strg+C zum Beenden\n")

show("WARTE")
GPIO.output(13, GPIO.LOW)
GPIO.output(15, GPIO.LOW)

start = time.monotonic()
last = "WARTE"
try:
    while time.monotonic() - start < 30:
        v11 = GPIO.input(11)
        v26 = GPIO.input(26)

        if v11 == GPIO.LOW or v26 == GPIO.LOW:
            # Irgendein Taster gedrückt
            GPIO.output(13, GPIO.HIGH)
            GPIO.output(15, GPIO.HIGH)
            new = "GEDRUECKT"
        else:
            GPIO.output(13, GPIO.LOW)
            GPIO.output(15, GPIO.LOW)
            new = "WARTE"

        if new != last:
            print(f"  → {new} (Pin11={'L' if v11==0 else 'H'}, Pin26={'L' if v26==0 else 'H'})")
            show(new)
            last = new

        time.sleep(0.05)

except KeyboardInterrupt:
    print("\nAbgebrochen")
finally:
    GPIO.output(13, GPIO.LOW)
    GPIO.output(15, GPIO.LOW)
    img = Image.new("1", (WIDTH, HEIGHT), 0)
    oled._display_image(img)
    GPIO.cleanup()
    print("Fertig.")
