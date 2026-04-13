#!/usr/bin/env python3
"""Schneller OLED-Test: zeigt einen Smiley + Text 5 Sekunden lang."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw
from jetson.oled import OledMenu, WIDTH, HEIGHT, FONT_LG

oled = OledMenu()
if not oled.init_hardware():
    print("OLED nicht gefunden")
    sys.exit(1)

img = Image.new("1", (WIDTH, HEIGHT), 0)
d = ImageDraw.Draw(img)

# Smiley
d.ellipse([10, 8, 60, 58], outline=1, width=2)
d.ellipse([22, 22, 28, 28], fill=1)
d.ellipse([42, 22, 48, 28], fill=1)
d.arc([22, 28, 48, 50], 20, 160, fill=1, width=2)

# Text
d.text((68, 24), "TEST", font=FONT_LG, fill=1)

oled._display_image(img)
print("Display zeigt jetzt Smiley + TEST für 5 Sekunden")
time.sleep(5)
oled._display_image(Image.new("1", (WIDTH, HEIGHT), 0))
print("Fertig.")
