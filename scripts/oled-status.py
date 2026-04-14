#!/usr/bin/env python3
"""
SAFIR OLED Boot/Shutdown Status — SSD1306 128×64 auf I2C Bus 7.
Verwendung:
  oled-status.py boot        → "BOOTING..." dann "OS READY"
  oled-status.py ready       → "OS READY"
  oled-status.py ssh-ready   → Hostname + Tailscale/LAN-IP für SSH-Verbindung
  oled-status.py shutdown    → "SHUTTING DOWN..."
  oled-status.py reboot      → "REBOOTING..."
  oled-status.py <text>      → Beliebiger Text
"""

import socket
import subprocess
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
    # Pillow 14-kompatibel: tobytes() gibt bei Mode "1" ein gepacktes Bit-Array
    raw = img.tobytes()
    row_bytes = (WIDTH + 7) // 8

    def px(x: int, y: int) -> bool:
        return bool(raw[y * row_bytes + (x >> 3)] & (0x80 >> (x & 7)))

    for page in range(8):
        bus.write_byte_data(I2C_ADDR, 0x00, 0xB0 + page)
        bus.write_byte_data(I2C_ADDR, 0x00, 0x00)
        bus.write_byte_data(I2C_ADDR, 0x00, 0x10)
        buf = []
        for x in range(WIDTH):
            byte = 0
            for bit in range(8):
                y = page * 8 + bit
                if px(x, y):
                    byte |= (1 << bit)
            buf.append(byte)
        for i in range(0, WIDTH, 16):
            bus.write_i2c_block_data(I2C_ADDR, 0x40, buf[i:i + 16])


def _get_hostname() -> str:
    try:
        return subprocess.run(
            ["hostname"], capture_output=True, text=True, timeout=2
        ).stdout.strip() or "jetson"
    except Exception:
        return "jetson"


def _get_tailscale_ip() -> str:
    try:
        r = subprocess.run(
            ["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=3
        )
        if r.returncode == 0:
            for line in r.stdout.strip().splitlines():
                line = line.strip()
                if line:
                    return line
    except Exception:
        pass
    return ""


def _get_lan_ip() -> str:
    # Primärroute-IP ermitteln ohne echten Traffic
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("100."):
            return ip
    except Exception:
        pass
    # Fallback: hostname -I, ersten nicht-Tailscale-Wert nehmen
    try:
        out = subprocess.run(
            ["hostname", "-I"], capture_output=True, text=True, timeout=2
        ).stdout
        for ip in out.split():
            if "." in ip and not ip.startswith("100.") and not ip.startswith("169.254."):
                return ip
    except Exception:
        pass
    return ""


def _count_remote_sessions() -> int:
    """Zählt aktive Remote-Login-Sessions (SSH via sshd oder Tailscale SSH)
    über systemd-logind. Filter: Remote=yes + State=active/online."""
    try:
        out = subprocess.run(
            ["loginctl", "list-sessions", "--no-legend"],
            capture_output=True, text=True, timeout=2,
        ).stdout
        sids = [line.split()[0] for line in out.splitlines() if line.strip()]
        if not sids:
            return 0
        result = subprocess.run(
            ["loginctl", "show-session", "--property=Remote", "--property=State"] + sids,
            capture_output=True, text=True, timeout=3,
        ).stdout
        count = 0
        current = {}
        for line in list(result.splitlines()) + [""]:
            if not line.strip():
                if current.get("Remote") == "yes" and current.get("State") in ("active", "online"):
                    count += 1
                current = {}
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                current[k] = v
        return count
    except Exception:
        return 0


def _safir_is_running() -> bool:
    """Erkennt ob SAFIR (uvicorn auf Port 8080 oder whisper-server) läuft —
    dann übernimmt die App die OLED-Kontrolle und wir beenden den Watcher."""
    try:
        r = subprocess.run(
            ["pgrep", "-f", "uvicorn app:app"],
            capture_output=True, text=True, timeout=2,
        )
        if r.returncode == 0:
            return True
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["pgrep", "-f", "whisper-server"],
            capture_output=True, text=True, timeout=2,
        )
        return r.returncode == 0
    except Exception:
        return False


def render_network(
    hostname: str, ts_ip: str, lan_ip: str, connected: bool = False
) -> Image.Image:
    """Vier-Zeilen-Layout für SSH-Status. Titel wechselt je nach Verbindungs-
    zustand. Einmal rendern reicht — SSD1306 hält den Inhalt."""
    img = Image.new("1", (WIDTH, HEIGHT), 0)
    draw = ImageDraw.Draw(img)

    draw.rectangle([0, 0, WIDTH - 1, HEIGHT - 1], outline=1)
    if connected:
        # Inverse Kopfzeile: weißer Balken mit schwarzer Schrift
        draw.rectangle([1, 1, WIDTH - 2, 20], fill=1)

    title = "SSH AKTIV" if connected else "SSH BEREIT"
    tb = FONT_BIG.getbbox(title)
    tw = tb[2] - tb[0]
    draw.text(
        ((WIDTH - tw) // 2, 4), title, font=FONT_BIG, fill=(0 if connected else 1)
    )

    hb = FONT_SM.getbbox(hostname)
    hw = hb[2] - hb[0]
    draw.text(((WIDTH - hw) // 2, 24), hostname, font=FONT_SM, fill=1)

    draw.line([(6, 37), (WIDTH - 7, 37)], fill=1)

    ts_line = ts_ip if ts_ip else "(kein Tailscale)"
    tsb = FONT_SM.getbbox(ts_line)
    tsw = tsb[2] - tsb[0]
    draw.text(((WIDTH - tsw) // 2, 40), ts_line, font=FONT_SM, fill=1)

    lan_line = lan_ip if lan_ip else "(kein LAN)"
    lb = FONT_SM.getbbox(lan_line)
    lw = lb[2] - lb[0]
    draw.text(((WIDTH - lw) // 2, 52), lan_line, font=FONT_SM, fill=1)

    return img


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

    elif mode == "ssh-ready":
        # Einmalige Anzeige: warten auf Netzwerk, dann rendern und beenden
        ts_ip = ""
        lan_ip = ""
        for _ in range(20):
            ts_ip = _get_tailscale_ip()
            lan_ip = _get_lan_ip()
            if ts_ip or lan_ip:
                break
            time.sleep(1)
        img = render_network(_get_hostname(), ts_ip, lan_ip)
        send_image(bus, img)
        # Kein sleep — SSD1306 behält Inhalt, bis SAFIR-App das OLED übernimmt

    elif mode == "ssh-watch":
        # Langlebiger Monitor: initial anzeigen, dann alle 2 s Remote-Sessions
        # pollen und Titel zwischen "SSH BEREIT" und "SSH AKTIV" wechseln.
        # Beendet sich sobald SAFIR startet — dann übernimmt die App das OLED.
        ts_ip = ""
        lan_ip = ""
        for _ in range(20):
            ts_ip = _get_tailscale_ip()
            lan_ip = _get_lan_ip()
            if ts_ip or lan_ip:
                break
            time.sleep(1)

        hostname = _get_hostname()
        last_connected = None  # None = initial, damit das erste Rendern immer feuert
        last_ips = (ts_ip, lan_ip)
        last_ip_refresh = time.time()
        print(f"ssh-watch started hostname={hostname} ts={ts_ip} lan={lan_ip}", flush=True)
        while True:
            if _safir_is_running():
                print("ssh-watch: SAFIR detected, exiting", flush=True)
                break
            connected = _count_remote_sessions() > 0
            if connected != last_connected:
                print(f"ssh-watch: state change -> connected={connected}", flush=True)
                img = render_network(hostname, ts_ip, lan_ip, connected=connected)
                send_image(bus, img)
                last_connected = connected
            # IP-Cache alle 30 s auffrischen (z. B. nach DHCP-Lease-Wechsel)
            if time.time() - last_ip_refresh >= 30:
                last_ip_refresh = time.time()
                new_ts = _get_tailscale_ip()
                new_lan = _get_lan_ip()
                if (new_ts, new_lan) != last_ips:
                    ts_ip, lan_ip = new_ts, new_lan
                    last_ips = (ts_ip, lan_ip)
                    img = render_network(hostname, ts_ip, lan_ip, connected=connected)
                    send_image(bus, img)
            time.sleep(2)

    elif mode == "shutdown":
        img = render("SHUTTING DOWN", "Bitte warten...")
        send_image(bus, img)

    elif mode == "reboot":
        img = render("REBOOTING...", "Bitte warten...")
        send_image(bus, img)

    else:
        # Beliebiger Text
        img = render(mode)
        send_image(bus, img)

    bus.close()


if __name__ == "__main__":
    main()
