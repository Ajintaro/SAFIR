#!/usr/bin/env python3
"""
SAFIR OLED Message — schreibt zwei Zeilen auf das SSD1306 OLED (128×64) via I2C.

Wird von den systemd Boot- und Shutdown-Splash-Hooks verwendet. Läuft
komplett unabhängig von SAFIR (kein venv, keine SAFIR-Imports). Nur System-
Python plus smbus2 + PIL, beides ist auf dem Jetson system-weit installiert.

Benutzung:
    safir-oled-msg "Zeile 1" "Zeile 2"

Rückgabecode:
    0 bei Erfolg, 1 bei Fehler (z.B. I2C nicht erreichbar).

Design:
    - Beide Zeilen mittig in großer Schrift (FONT_XL, 16 px Bold)
    - Zeile 1 oben (y=8), Zeile 2 darunter (y=32)
    - Dünner Rahmen um das Display für klare Abgrenzung
"""
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
    import smbus2
except ImportError as e:
    print(f"safir-oled-msg: Abhängigkeit fehlt: {e}", file=sys.stderr)
    sys.exit(1)

WIDTH = 128
HEIGHT = 64
I2C_BUS = 7
I2C_ADDR = 0x3C

# SSD1306 Init-Sequenz (Charge Pump ON, Kontrast max)
_SSD1306_INIT = [
    0xAE, 0xD5, 0x80, 0xA8, 0x3F, 0xD3, 0x00, 0x40,
    0x8D, 0x14,
    0x20, 0x00,
    0xA1, 0xC8, 0xDA, 0x12,
    0x81, 0xFF,
    0xD9, 0xF1, 0xDB, 0x40, 0xA4, 0xA6, 0xAF,
]

FONT_BOLD_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
FONT_REG_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"


def _load_font(size):
    for path in (FONT_BOLD_PATH, FONT_REG_PATH):
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _center_x(draw, text, font):
    bbox = font.getbbox(text)
    tw = bbox[2] - bbox[0]
    return max(0, (WIDTH - tw) // 2)


def render_two_lines(line1: str, line2: str) -> Image.Image:
    """Baut ein 128×64 Bild mit zwei zentrierten Zeilen in XL-Schrift."""
    img = Image.new("1", (WIDTH, HEIGHT), 0)
    draw = ImageDraw.Draw(img)

    # Rahmen für sichtbare Abgrenzung
    draw.rectangle([0, 0, WIDTH - 1, HEIGHT - 1], outline=1)

    font_xl = _load_font(16)

    # Zeile 1 oben
    if line1:
        draw.text((_center_x(draw, line1, font_xl), 8), line1, font=font_xl, fill=1)

    # Zeile 2 darunter
    if line2:
        draw.text((_center_x(draw, line2, font_xl), 32), line2, font=font_xl, fill=1)

    return img


def write_to_display(img: Image.Image):
    """Sendet ein 128×64 Monochrom-Bild an das SSD1306 via smbus2."""
    bus = smbus2.SMBus(I2C_BUS)
    try:
        # Init-Sequenz
        for cmd in _SSD1306_INIT:
            bus.write_byte_data(I2C_ADDR, 0x00, cmd)

        # Pixel in Page-Format kodieren
        pixels = list(img.getdata())
        for page in range(8):
            bus.write_byte_data(I2C_ADDR, 0x00, 0xB0 + page)  # Page start
            bus.write_byte_data(I2C_ADDR, 0x00, 0x00)         # Col lower
            bus.write_byte_data(I2C_ADDR, 0x00, 0x10)         # Col upper
            buf = []
            for x in range(WIDTH):
                byte = 0
                for bit in range(8):
                    y = page * 8 + bit
                    if pixels[y * WIDTH + x]:
                        byte |= (1 << bit)
                buf.append(byte)
            for i in range(0, WIDTH, 16):
                bus.write_i2c_block_data(I2C_ADDR, 0x40, buf[i:i + 16])
    finally:
        bus.close()


def main():
    if len(sys.argv) < 2:
        print("Benutzung: safir-oled-msg <Zeile1> [Zeile2]", file=sys.stderr)
        return 1

    line1 = sys.argv[1] if len(sys.argv) > 1 else ""
    line2 = sys.argv[2] if len(sys.argv) > 2 else ""

    try:
        img = render_two_lines(line1, line2)
        write_to_display(img)
        return 0
    except Exception as e:
        print(f"safir-oled-msg: Fehler beim OLED-Zugriff: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
