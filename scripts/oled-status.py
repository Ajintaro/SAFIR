#!/usr/bin/env python3
"""
SAFIR OLED Boot/Shutdown Status — SSD1306 128×64 auf I2C Bus 7.
Verwendung:
  oled-status.py boot       → "BOOTING..." dann "OS READY"
  oled-status.py shutdown   → "SHUTTING DOWN..."
  oled-status.py reboot     → "REBOOTING..."
  oled-status.py <text>     → Beliebiger Text
"""

import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# --- Display-Konstanten ---
I2C_BUS = 7
I2C_ADDR = 0x3C
WIDTH = 128
HEIGHT = 64

SSD1306_INIT = [
    0xAE, 0xD5, 0x80, 0xA8, 0x3F, 0xD3, 0x00, 0x40,
    0x8D, 0x14, 0x20, 0x00, 0xA1, 0xC8, 0xDA, 0x12,
    0x81, 0xFF, 0xD9, 0xF1, 0xDB, 0x40, 0xA4, 0xA6, 0xAF,
]


def _font(size=11):
    for p in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ]:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


FONT_BIG = _font(14)
FONT_SM = _font(9)


def init_display(bus):
    for cmd in SSD1306_INIT:
        bus.write_byte_data(I2C_ADDR, 0x00, cmd)


def send_image(bus, img: Image.Image):
    pixels = list(img.get_flattened_data() if hasattr(img, 'get_flattened_data') else img.getdata())
    for page in range(8):
        bus.write_byte_data(I2C_ADDR, 0x00, 0xB0 + page)
        bus.write_byte_data(I2C_ADDR, 0x00, 0x00)
        bus.write_byte_data(I2C_ADDR, 0x00, 0x10)
        buf = []
        for x in range(128):
            byte = 0
            for bit in range(8):
                y = page * 8 + bit
                if pixels[y * 128 + x]:
                    byte |= (1 << bit)
            buf.append(byte)
        for i in range(0, 128, 16):
            bus.write_i2c_block_data(I2C_ADDR, 0x40, buf[i:i + 16])


def render(text: str, sub: str = "", animate: bool = False):
    img = Image.new("1", (WIDTH, HEIGHT), 0)
    draw = ImageDraw.Draw(img)

    # Doppelter Rahmen
    draw.rectangle([0, 0, WIDTH - 1, HEIGHT - 1], outline=1)
    draw.rectangle([2, 2, WIDTH - 3, HEIGHT - 3], outline=1)

    # SAFIR Label oben
    label = "[ SAFIR ]"
    lbox = FONT_SM.getbbox(label)
    lw = lbox[2] - lbox[0]
    draw.text(((WIDTH - lw) // 2, 6), label, font=FONT_SM, fill=1)

    # Haupttext zentriert
    bbox = FONT_BIG.getbbox(text)
    tw = bbox[2] - bbox[0]
    draw.text(((WIDTH - tw) // 2, 24), text, font=FONT_BIG, fill=1)

    # Untertext
    if sub:
        sbox = FONT_SM.getbbox(sub)
        sw = sbox[2] - sbox[0]
        draw.text(((WIDTH - sw) // 2, 44), sub, font=FONT_SM, fill=1)

    return img


def main():
    import smbus2

    mode = sys.argv[1] if len(sys.argv) > 1 else "boot"
    bus = smbus2.SMBus(I2C_BUS)
    init_display(bus)

    if mode == "boot":
        # Phase 1: BOOTING
        img = render("BOOTING...", "Systeme laden")
        send_image(bus, img)
        # Warte bis Multi-User-Target erreicht ist (max 120s)
        for _ in range(120):
            time.sleep(1)
        # Falls wir hier ankommen: OS READY (normalerweise beendet systemd uns vorher)
        img = render("OS READY", "Bereit")
        send_image(bus, img)

    elif mode == "ready":
        img = render("OS READY", "Systeme bereit")
        send_image(bus, img)
        time.sleep(5)

    elif mode == "shutdown":
        img = render("SHUTTING DOWN", "Bitte warten...")
        send_image(bus, img)
        time.sleep(30)

    elif mode == "reboot":
        img = render("REBOOTING...", "Bitte warten...")
        send_image(bus, img)
        time.sleep(30)

    else:
        # Beliebiger Text
        img = render(mode)
        send_image(bus, img)

    bus.close()


if __name__ == "__main__":
    main()
