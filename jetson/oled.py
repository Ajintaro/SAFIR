#!/usr/bin/env python3
"""
SAFIR OLED-Display Manager — SSD1306 128×64 Pixel
Rendert Systemstatus, Audio, Netzwerk, Patienten, Power und Modelle
auf ein kleines OLED-Display oder als Software-Simulator.
"""

import base64
import io
import time
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Display-Konstanten
WIDTH = 128
HEIGHT = 64
PAGES = ["system", "audio", "network", "patients", "power", "models"]
PAGE_TITLES = {
    "system": "SYSTEM",
    "audio": "AUDIO",
    "network": "NETZWERK",
    "patients": "PATIENTEN",
    "power": "POWER",
    "models": "KI-MODELLE",
}


def _load_font(size=10):
    """Lädt einen Monospace-Font oder Fallback."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
        "/System/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/Monaco.dfont",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


# Fonts vorladen
FONT_SM = _load_font(9)
FONT_MD = _load_font(11)
FONT_LG = _load_font(13)


class OledMenu:
    """Verwaltet OLED-Seiten und rendert in ein PIL-Image."""

    def __init__(self):
        self.current_page = 0
        self.stats = {}         # System-Stats (CPU, RAM, GPU, ...)
        self.audio_info = {}    # Mikrofon-Status
        self.network_info = {}  # Netzwerk-Info
        self.patient_info = {}  # Patienten-Übersicht
        self.model_info = {}    # KI-Modelle Status
        self.power_info = {}    # Strom/Power
        self._hw_device = None  # luma.oled Device (None = Software-only)

    def init_hardware(self):
        """Versucht SSD1306 über I2C zu initialisieren. Fehlschlag = Software-only."""
        try:
            from luma.core.interface.serial import i2c
            from luma.oled.device import ssd1306
            serial = i2c(port=1, address=0x3C)
            self._hw_device = ssd1306(serial, width=WIDTH, height=HEIGHT)
            print("OLED: SSD1306 auf I2C initialisiert")
            return True
        except Exception as e:
            print(f"OLED: Kein Hardware-Display ({e}) — Software-Simulator aktiv")
            self._hw_device = None
            return False

    # ---- Navigation ----
    def button_up(self):
        """Vorherige Seite."""
        self.current_page = (self.current_page - 1) % len(PAGES)

    def button_down(self):
        """Nächste Seite."""
        self.current_page = (self.current_page + 1) % len(PAGES)

    def button_ok(self):
        """Aktion auf der aktuellen Seite."""
        page = PAGES[self.current_page]
        # Seitenspezifische Aktionen werden vom App-Layer behandelt
        return {"page": page, "action": "ok"}

    # ---- Daten aktualisieren ----
    def update_stats(self, stats: dict):
        self.stats = stats

    def update_audio(self, info: dict):
        self.audio_info = info

    def update_network(self, info: dict):
        self.network_info = info

    def update_patients(self, info: dict):
        self.patient_info = info

    def update_power(self, info: dict):
        self.power_info = info

    def update_models(self, info: dict):
        self.model_info = info

    # ---- Rendering ----
    def render(self) -> Image.Image:
        """Rendert die aktuelle Seite als 128×64 PIL-Image."""
        img = Image.new("1", (WIDTH, HEIGHT), 0)  # Monochrom, schwarz
        draw = ImageDraw.Draw(img)
        page = PAGES[self.current_page]

        # Header
        self._draw_header(draw, page)

        # Seiteninhalt
        if page == "system":
            self._render_system(draw)
        elif page == "audio":
            self._render_audio(draw)
        elif page == "network":
            self._render_network(draw)
        elif page == "patients":
            self._render_patients(draw)
        elif page == "power":
            self._render_power(draw)
        elif page == "models":
            self._render_models(draw)

        # Auf Hardware-Display schreiben (falls vorhanden)
        if self._hw_device:
            self._hw_device.display(img)

        return img

    def render_base64(self) -> str:
        """Rendert und gibt Base64-encodiertes PNG zurück."""
        img = self.render()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")

    # ---- Header ----
    def _draw_header(self, draw: ImageDraw, page: str):
        title = PAGE_TITLES.get(page, page.upper())
        now = datetime.now().strftime("%H:%M")
        draw.text((1, 0), title, font=FONT_MD, fill=1)
        draw.text((WIDTH - 30, 0), now, font=FONT_SM, fill=1)
        # Seitenindikator (Punkte)
        for i in range(len(PAGES)):
            x = WIDTH // 2 - len(PAGES) * 4 + i * 8
            if i == self.current_page:
                draw.rectangle([x, 1, x + 4, 5], fill=1)
            else:
                draw.point((x + 2, 3), fill=1)
        draw.line([(0, 10), (WIDTH - 1, 10)], fill=1)

    # ---- Hilfsfunktionen ----
    def _draw_bar(self, draw: ImageDraw, x, y, w, h, percent):
        """Zeichnet einen Fortschrittsbalken."""
        draw.rectangle([x, y, x + w - 1, y + h - 1], outline=1)
        fill_w = max(0, int((w - 2) * min(percent, 100) / 100))
        if fill_w > 0:
            draw.rectangle([x + 1, y + 1, x + fill_w, y + h - 2], fill=1)

    def _text_r(self, draw, x, y, text, font=None):
        """Rechtsbündiger Text."""
        font = font or FONT_SM
        bbox = font.getbbox(text)
        tw = bbox[2] - bbox[0]
        draw.text((x - tw, y), text, font=font, fill=1)

    # ---- Seite 1: System Status ----
    def _render_system(self, draw: ImageDraw):
        s = self.stats
        y = 13
        cpu = s.get("cpu_percent", 0)
        ram_pct = s.get("ram_percent", 0)
        ram_used = s.get("ram_used_mb", 0)
        ram_total = s.get("ram_total_mb", 0)
        gpu = s.get("gpu_usage", "N/A")
        disk_pct = s.get("disk_percent", 0)

        # CPU
        draw.text((1, y), "CPU", font=FONT_SM, fill=1)
        self._draw_bar(draw, 24, y, 60, 8, cpu)
        self._text_r(draw, 126, y, f"{cpu:.0f}%", FONT_SM)

        # RAM
        y += 11
        draw.text((1, y), "RAM", font=FONT_SM, fill=1)
        self._draw_bar(draw, 24, y, 60, 8, ram_pct)
        ram_gb = f"{ram_used / 1024:.1f}/{ram_total / 1024:.0f}G"
        self._text_r(draw, 126, y, ram_gb, FONT_SM)

        # GPU
        y += 11
        draw.text((1, y), "GPU", font=FONT_SM, fill=1)
        if gpu != "N/A":
            gpu_val = float(gpu)
            self._draw_bar(draw, 24, y, 60, 8, gpu_val)
            self._text_r(draw, 126, y, f"{gpu_val:.0f}%", FONT_SM)
        else:
            draw.text((24, y), "Shared Memory", font=FONT_SM, fill=1)

        # Disk
        y += 11
        draw.text((1, y), "DSK", font=FONT_SM, fill=1)
        self._draw_bar(draw, 24, y, 60, 8, disk_pct)
        self._text_r(draw, 126, y, f"{disk_pct:.0f}%", FONT_SM)

        # Untere Zeile: Unit-Info
        y += 12
        unit = s.get("unit_name", "")
        pat_count = s.get("patient_count", 0)
        if unit:
            draw.rectangle([0, y, 3, y + 3], fill=1)  # Punkt
            draw.text((6, y - 1), f"{unit}  {pat_count} Pat.", font=FONT_SM, fill=1)

    # ---- Seite 2: Audio ----
    def _render_audio(self, draw: ImageDraw):
        a = self.audio_info
        y = 13
        rms = a.get("rms", 0)
        db = max(0, min(99, int(rms * 1000)))

        # Pegelanzeige
        bar_w = 100
        draw.text((1, y), "Pegel", font=FONT_SM, fill=1)
        y += 10
        self._draw_bar(draw, 1, y, bar_w, 8, db)
        self._text_r(draw, 126, y, f"{db} dB", FONT_SM)

        # Geräte-Info
        y += 12
        device = a.get("device_name", "Kein Gerät")
        draw.text((1, y), f"Geraet: {device[:18]}", font=FONT_SM, fill=1)

        y += 10
        rate = a.get("sample_rate", 16000)
        draw.text((1, y), f"Rate:   {rate} Hz", font=FONT_SM, fill=1)

        y += 10
        status = a.get("status", "Bereit")
        duration = a.get("duration", 0)
        draw.text((1, y), f"Status: {status}", font=FONT_SM, fill=1)
        if duration > 0:
            mins, secs = divmod(int(duration), 60)
            self._text_r(draw, 126, y, f"{mins:02d}:{secs:02d}", FONT_SM)

    # ---- Seite 3: Netzwerk ----
    def _render_network(self, draw: ImageDraw):
        n = self.network_info
        y = 13

        wlan = n.get("ssid", "---")
        draw.text((1, y), f"WLAN: {wlan[:18]}", font=FONT_SM, fill=1)

        y += 10
        ip = n.get("ip", "---")
        draw.text((1, y), f"IP:   {ip}", font=FONT_SM, fill=1)

        y += 10
        ts_ip = n.get("tailscale_ip", "---")
        draw.text((1, y), f"TS:   {ts_ip}", font=FONT_SM, fill=1)

        y += 14
        role1 = n.get("role1_status", "getrennt")
        indicator = "●" if role1 == "verbunden" else "○"
        draw.text((1, y), f"Role1: {indicator} {role1}", font=FONT_SM, fill=1)

        y += 10
        peers = n.get("peers", 0)
        draw.text((1, y), f"Peers: {peers}", font=FONT_SM, fill=1)

    # ---- Seite 4: Patienten ----
    def _render_patients(self, draw: ImageDraw):
        p = self.patient_info
        total = p.get("total", 0)
        y = 13

        # Titel rechts: Anzahl
        self._text_r(draw, 126, 0, f"{total} total", FONT_SM)

        # Triage-Übersicht
        t1 = p.get("t1", 0)
        t2 = p.get("t2", 0)
        t3 = p.get("t3", 0)
        t4 = p.get("t4", 0)

        draw.text((1, y), f"T1", font=FONT_SM, fill=1)
        self._draw_bar(draw, 16, y, 30, 7, t1 * 20 if total else 0)
        draw.text((48, y), f"{t1}", font=FONT_SM, fill=1)

        draw.text((65, y), f"T2", font=FONT_SM, fill=1)
        self._draw_bar(draw, 80, y, 30, 7, t2 * 20 if total else 0)
        draw.text((112, y), f"{t2}", font=FONT_SM, fill=1)

        y += 11
        draw.text((1, y), f"T3", font=FONT_SM, fill=1)
        self._draw_bar(draw, 16, y, 30, 7, t3 * 20 if total else 0)
        draw.text((48, y), f"{t3}", font=FONT_SM, fill=1)

        draw.text((65, y), f"T4", font=FONT_SM, fill=1)
        self._draw_bar(draw, 80, y, 30, 7, t4 * 20 if total else 0)
        draw.text((112, y), f"{t4}", font=FONT_SM, fill=1)

        # Letzter Patient
        y += 14
        last_name = p.get("last_patient", "---")
        draw.text((1, y), f"Letzt: {last_name[:16]}", font=FONT_SM, fill=1)

        y += 10
        sync = p.get("synced", 0)
        draw.text((1, y), f"Sync:  {sync}/{total} uebermittelt", font=FONT_SM, fill=1)

    # ---- Seite 5: Power ----
    def _render_power(self, draw: ImageDraw):
        pw = self.power_info
        y = 13

        mode = pw.get("power_mode", "15W (MaxN)")
        draw.text((1, y), f"Modus: {mode}", font=FONT_SM, fill=1)

        y += 10
        watts = pw.get("current_watts", 0)
        if watts > 0:
            draw.text((1, y), f"Verb.: ~{watts:.1f} W", font=FONT_SM, fill=1)
        else:
            draw.text((1, y), "Verb.: N/A", font=FONT_SM, fill=1)

        # Temperaturen
        y += 14
        temps = self.stats.get("temperatures", {})
        cpu_t = temps.get("cpu-thermal", temps.get("CPU", "?"))
        gpu_t = temps.get("gpu-thermal", temps.get("GPU", "?"))
        draw.text((1, y), f"CPU {cpu_t}C  GPU {gpu_t}C", font=FONT_SM, fill=1)

        soc_t = temps.get("soc0-thermal", temps.get("SoC", ""))
        if soc_t:
            y += 10
            draw.text((1, y), f"SoC {soc_t}C", font=FONT_SM, fill=1)

        # Uptime
        y += 10
        uptime = pw.get("uptime_hours", 0)
        if uptime > 0:
            draw.text((1, y), f"Uptime: {uptime:.1f}h", font=FONT_SM, fill=1)

    # ---- Seite 6: Modelle ----
    def _render_models(self, draw: ImageDraw):
        m = self.model_info
        y = 13

        # Whisper
        whisper = m.get("whisper_model", "---")
        whisper_loaded = m.get("whisper_loaded", False)
        whisper_mb = m.get("whisper_mb", 0)
        status = "●" if whisper_loaded else "○"
        draw.text((1, y), f"Whisper: {whisper} {status}", font=FONT_SM, fill=1)
        if whisper_mb:
            self._text_r(draw, 126, y, f"{whisper_mb}MB", FONT_SM)

        # Ollama
        y += 10
        ollama = m.get("ollama_model", "---")
        ollama_loaded = m.get("ollama_loaded", False)
        ollama_mb = m.get("ollama_mb", 0)
        status = "●" if ollama_loaded else "○"
        draw.text((1, y), f"Ollama: {ollama} {status}", font=FONT_SM, fill=1)
        if ollama_mb:
            self._text_r(draw, 126, y, f"{ollama_mb}MB", FONT_SM)

        # Vosk
        y += 10
        vosk_active = m.get("vosk_active", False)
        status = "● aktiv" if vosk_active else "○ aus"
        draw.text((1, y), f"Vosk:   de-sm {status}", font=FONT_SM, fill=1)

        # VRAM frei
        y += 14
        vram_free = m.get("vram_free_mb", 0)
        if vram_free > 0:
            draw.text((1, y), f"VRAM frei: {vram_free / 1024:.1f} GB", font=FONT_SM, fill=1)

        # Aktion
        y += 10
        action = m.get("ok_action", "Whisper laden")
        draw.text((1, y), f"[OK] {action}", font=FONT_SM, fill=1)


# Singleton für globalen Zugriff
oled_menu = OledMenu()
