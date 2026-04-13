#!/usr/bin/env python3
"""Taster-Test mit OLED-Feedback: zeigt einen Smiley mit Name beim Drücken.

Taster A (Pin 26) → Smiley + "TASTER A" im OLED
Taster B (Pin 11) → Smiley + "TASTER B" im OLED
Beide losgelassen → "BEREIT"

Strg+C zum Beenden.
"""
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

# Pfad zum jetson/oled.py-Modul für OLED-Init
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import Jetson.GPIO as GPIO
from PIL import Image, ImageDraw, ImageFont
from jetson.oled import OledMenu, WIDTH, HEIGHT, FONT_LG, FONT_MD

BTN_A, LED_A = 11, 15  # Taster A → LED Pin 15 (über BC547)
BTN_B, LED_B = 26, 13  # Taster B → LED Pin 13 (über BC547)

# OLED initialisieren (via OledMenu, I2C Bus 7, Adresse 0x3C)
oled = OledMenu()
ok = oled.init_hardware()
if not ok:
    print("FEHLER: OLED nicht erreichbar")
    sys.exit(1)

# GPIO
GPIO.setmode(GPIO.BOARD)
GPIO.setup(BTN_A, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(BTN_B, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(LED_A, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(LED_B, GPIO.OUT, initial=GPIO.LOW)


def draw_smiley(draw: ImageDraw, cx: int, cy: int, r: int):
    """Zeichnet einen einfachen Smiley bei (cx, cy) mit Radius r."""
    # Gesicht (Kreis)
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=1, width=2)
    # Augen
    eye_r = max(2, r // 6)
    eye_dx = r // 2
    eye_dy = r // 4
    draw.ellipse([cx - eye_dx - eye_r, cy - eye_dy - eye_r,
                  cx - eye_dx + eye_r, cy - eye_dy + eye_r], fill=1)
    draw.ellipse([cx + eye_dx - eye_r, cy - eye_dy - eye_r,
                  cx + eye_dx + eye_r, cy - eye_dy + eye_r], fill=1)
    # Mund (Bogen)
    mouth_r = r // 2
    draw.arc([cx - mouth_r, cy - mouth_r // 2,
              cx + mouth_r, cy + mouth_r], 20, 160, fill=1, width=2)


def render_pressed(name: str) -> Image.Image:
    """Rendert Smiley mit Name."""
    img = Image.new("1", (WIDTH, HEIGHT), 0)
    draw = ImageDraw.Draw(img)
    # Smiley links
    draw_smiley(draw, 28, 32, 24)
    # Name rechts
    bbox = FONT_LG.getbbox(name)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = 60 + (66 - tw) // 2
    y = (HEIGHT - th) // 2 - 2
    draw.text((x, y), name, font=FONT_LG, fill=1)
    return img


def render_blank() -> Image.Image:
    """Komplett leeres Display."""
    return Image.new("1", (WIDTH, HEIGHT), 0)


# Initial: leer
oled._display_image(render_blank())
print("Bereit. Drücke Taster A (Pin 26) oder Taster B (Pin 11). Strg+C zum Beenden.\n")

last_state = None  # 'A', 'B', None
last_debug = 0.0
try:
    while True:
        a_raw = GPIO.input(BTN_A)
        b_raw = GPIO.input(BTN_B)
        a = a_raw == GPIO.LOW
        b = b_raw == GPIO.LOW

        # LEDs spiegeln Tasterzustand direkt
        GPIO.output(LED_A, GPIO.HIGH if a else GPIO.LOW)
        GPIO.output(LED_B, GPIO.HIGH if b else GPIO.LOW)

        if a:
            current = "A"
        elif b:
            current = "B"
        else:
            current = None

        if current != last_state:
            if current == "A":
                print("→ Taster A gedrückt — LED A an, OLED: TASTER A")
                oled._display_image(render_pressed("TASTER A"))
            elif current == "B":
                print("→ Taster B gedrückt — LED B an, OLED: TASTER B")
                oled._display_image(render_pressed("TASTER B"))
            else:
                print("→ losgelassen — alles aus")
                oled._display_image(render_blank())
            last_state = current

        # Heartbeat alle 2 Sekunden mit Roh-Status
        now = time.monotonic()
        if now - last_debug > 2.0:
            print(f"  [hb] Pin{BTN_A}={'HIGH' if a_raw else 'LOW '}  "
                  f"Pin{BTN_B}={'HIGH' if b_raw else 'LOW '}  "
                  f"current={current}", flush=True)
            last_debug = now

        time.sleep(0.02)

except KeyboardInterrupt:
    print("\nAbgebrochen")
finally:
    GPIO.output(LED_A, GPIO.LOW)
    GPIO.output(LED_B, GPIO.LOW)
    oled._display_image(render_blank())
    GPIO.cleanup()
