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

# SSD1306 Init-Sequenz (Charge Pump aktiv, Kontrast MAX)
_SSD1306_INIT = [
    0xAE, 0xD5, 0x80, 0xA8, 0x3F, 0xD3, 0x00, 0x40,
    0x8D, 0x14,  # Charge Pump ON
    0x20, 0x00,  # Horizontal Addressing
    0xA1, 0xC8, 0xDA, 0x12,
    0x81, 0xFF,  # Kontrast MAX
    0xD9, 0xF1, 0xDB, 0x40, 0xA4, 0xA6, 0xAF,
]

# Display-Konstanten
WIDTH = 128
HEIGHT = 64
PAGES = ["models", "operator", "patient", "cardwrite"]
PAGE_TITLES = {
    "models": "KI-STATUS",
    "operator": "BEDIENER",
    "patient": "PATIENT",
    "cardwrite": "KARTE",
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
FONT_XL = _load_font(16)


class OledMenu:
    """Verwaltet OLED-Seiten und rendert in ein PIL-Image."""

    def __init__(self):
        self.current_page = 0
        self.stats = {}              # System-Stats (CPU, RAM, GPU, Temperaturen, ...)
        self.network_info = {}       # Netzwerk-Info (Hostname, IP)
        self.patient_info = {}       # Patienten-Übersicht (Anzahl, etc.)
        self.power_info = {}         # Strom/Power (Watt, Modus, Uptime)
        self.operator_info = {}      # Eingeloggter Bediener (RFID)
        self.cardwrite_info = {}     # Aktiver Patient für Schreiben auf Karte
        self.active_patient_info = {}  # Aktiver Patient (Name, Triage, Flow-Status)
        self.models_status = {}      # KI-Modelle (Whisper/Ollama) geladen + auf GPU?
        # Altlasten — werden nicht mehr gerendert aber von app.py noch befüllt:
        self.audio_info = {}
        self.model_info = {}
        self.hardware_info = {}
        self._i2c_bus = None    # smbus2 Bus (None = Software-only)
        self._i2c_addr = 0x3C
        self._status_mode = False  # True = Vollbild-Status statt Menü
        self._status_text = ""
        self._status_sub = ""
        self._status_progress = -1  # -1 = kein Balken, 0-100 = Prozent
        self._last_activity = time.time()  # Burn-in Schutz
        self._display_off = False
        self.SCREENSAVER_SECONDS = 300  # 5 Minuten

    def init_hardware(self):
        """Versucht SSD1306 über I2C zu initialisieren. Fehlschlag = Software-only."""
        try:
            import smbus2
            self._i2c_bus = smbus2.SMBus(7)
            for cmd in _SSD1306_INIT:
                self._i2c_bus.write_byte_data(self._i2c_addr, 0x00, cmd)
            self._last_activity = time.time()
            print("OLED: SSD1306 auf I2C initialisiert (Charge Pump aktiv)")
            return True
        except Exception as e:
            print(f"OLED: Kein Hardware-Display ({e}) — Software-Simulator aktiv")
            self._i2c_bus = None
            return False

    def _wake(self):
        """Aktiviert Display und setzt Inaktivitäts-Timer zurück."""
        self._last_activity = time.time()
        if self._display_off and self._i2c_bus:
            self._i2c_bus.write_byte_data(self._i2c_addr, 0x00, 0xAF)  # Display ON
            self._display_off = False

    def wake(self):
        """Public Alias für _wake() — von Hardware-Service/Buttons aufgerufen."""
        self._wake()

    @property
    def is_sleeping(self) -> bool:
        """True wenn das Display im Standby (Burn-in-Schutz) ist."""
        return self._display_off

    def _sleep_display(self):
        """Schaltet Display aus (Burn-in Schutz)."""
        if not self._display_off and self._i2c_bus:
            self._i2c_bus.write_byte_data(self._i2c_addr, 0x00, 0xAE)  # Display OFF
            self._display_off = True

    def check_screensaver(self):
        """Prüft ob Screensaver aktiviert werden soll. Aus _oled_update_loop aufrufen."""
        if self._display_off:
            return
        if time.time() - self._last_activity > self.SCREENSAVER_SECONDS:
            self._sleep_display()

    def _display_image(self, img: Image.Image):
        """Sendet ein PIL-Image direkt an das SSD1306 via smbus2."""
        if not self._i2c_bus:
            return
        pixels = list(img.getdata())
        for page in range(8):
            self._i2c_bus.write_byte_data(self._i2c_addr, 0x00, 0xB0 + page)
            self._i2c_bus.write_byte_data(self._i2c_addr, 0x00, 0x00)
            self._i2c_bus.write_byte_data(self._i2c_addr, 0x00, 0x10)
            buf = []
            for x in range(128):
                byte = 0
                for bit in range(8):
                    y = page * 8 + bit
                    if pixels[y * 128 + x]:
                        byte |= (1 << bit)
                buf.append(byte)
            for i in range(0, 128, 16):
                self._i2c_bus.write_i2c_block_data(self._i2c_addr, 0x40, buf[i:i + 16])

    # ---- Status-Anzeige (Vollbild) ----
    def show_status(self, text: str, sub: str = "", progress: int = -1):
        """Zeigt Vollbild-Status auf dem Display. progress: -1=kein Balken, 0-100=Prozent."""
        self._wake()
        self._status_mode = True
        self._status_text = text
        self._status_sub = sub
        self._status_progress = progress
        self._render_fullscreen_status()

    def clear_status(self):
        """Schaltet zurück zur normalen Menü-Ansicht."""
        self._status_mode = False

    def _render_fullscreen_status(self):
        """Rendert den Vollbild-Status-Overlay und sendet ans Display (für show_status())."""
        img = Image.new("1", (WIDTH, HEIGHT), 0)
        draw = ImageDraw.Draw(img)

        # Rand
        draw.rectangle([0, 0, WIDTH - 1, HEIGHT - 1], outline=1)
        draw.rectangle([2, 2, WIDTH - 3, HEIGHT - 3], outline=1)

        # Haupttext zentriert
        bbox = FONT_LG.getbbox(self._status_text)
        tw = bbox[2] - bbox[0]
        x = (WIDTH - tw) // 2
        y_main = 16 if self._status_sub or self._status_progress >= 0 else 22
        draw.text((x, y_main), self._status_text, font=FONT_LG, fill=1)

        # Untertext
        if self._status_sub:
            bbox2 = FONT_SM.getbbox(self._status_sub)
            tw2 = bbox2[2] - bbox2[0]
            x2 = (WIDTH - tw2) // 2
            draw.text((x2, y_main + 18), self._status_sub, font=FONT_SM, fill=1)

        # Fortschrittsbalken
        if self._status_progress >= 0:
            bar_y = HEIGHT - 16
            draw.rectangle([8, bar_y, WIDTH - 9, bar_y + 7], outline=1)
            fill_w = int((WIDTH - 20) * min(self._status_progress, 100) / 100)
            if fill_w > 0:
                draw.rectangle([10, bar_y + 1, 9 + fill_w, bar_y + 6], fill=1)

        self._display_image(img)
        return img

    # ---- Navigation ----
    def button_up(self):
        """Vorherige Seite."""
        self._wake()
        self.current_page = (self.current_page - 1) % len(PAGES)

    def button_down(self):
        """Nächste Seite."""
        self._wake()
        self.current_page = (self.current_page + 1) % len(PAGES)

    def button_ok(self):
        """Aktion auf der aktuellen Seite."""
        self._wake()
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

    def update_operator(self, info: dict):
        self.operator_info = info

    def update_hardware(self, info: dict):
        self.hardware_info = info

    def update_cardwrite(self, info: dict):
        self.cardwrite_info = info

    def update_active_patient(self, info: dict):
        self.active_patient_info = info

    def update_models_status(self, info: dict):
        self.models_status = info

    # ---- Rendering ----
    def render(self) -> Image.Image:
        """Rendert die aktuelle Seite als 128×64 PIL-Image."""
        # Im Status-Modus: Vollbild-Status anzeigen
        if self._status_mode:
            return self._render_fullscreen_status()

        img = Image.new("1", (WIDTH, HEIGHT), 0)  # Monochrom, schwarz
        draw = ImageDraw.Draw(img)
        page = PAGES[self.current_page]

        # Kein Header — volle 64 Pixel Höhe für Content

        # Seiteninhalt — 4-Seiten-Design (KI-Status / Bediener / Patient / Karte)
        if page == "models":
            self._render_models_status(draw)
        elif page == "operator":
            self._render_operator(draw)
        elif page == "patient":
            self._render_patient(draw)
        elif page == "cardwrite":
            self._render_cardwrite(draw)

        # Auf Hardware-Display schreiben (falls vorhanden)
        self._display_image(img)

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

    # ---- Seite: KI-STATUS (Whisper + Qwen Bereitschaft) ----
    def _render_models_status(self, draw: ImageDraw):
        m = self.models_status
        whisper_ok = m.get("whisper_ok", False)
        qwen_ok = m.get("qwen_ok", False)

        # WHISPER-Zeile
        whisper_text = "WHISPER=OK" if whisper_ok else "WHISPER=??"
        draw.text((2, 4), whisper_text, font=FONT_XL, fill=1)

        # QWEN-Zeile
        qwen_text = "QWEN=OK" if qwen_ok else "QWEN=??"
        draw.text((2, 30), qwen_text, font=FONT_XL, fill=1)

        # Unten: Hinweis wenn beide bereit, oder welches fehlt
        if whisper_ok and qwen_ok:
            # Beide OK → invertierter "BEREIT"-Balken unten
            draw.rectangle([0, 52, WIDTH - 1, 63], fill=1)
            draw.text((30, 53), "EINSATZBEREIT", font=FONT_MD, fill=0)
        else:
            missing = []
            if not whisper_ok:
                missing.append("Whisper")
            if not qwen_ok:
                missing.append("Qwen")
            draw.text((2, 54), f"Warte: {' + '.join(missing)}", font=FONT_SM, fill=1)

    # ---- Seite: BEDIENER (nutzt volle 64 px, kein Header) ----
    def _render_operator(self, draw: ImageDraw):
        op = self.operator_info
        if not op.get("logged_in", False):
            draw.text((2, 4),  "KEIN",   font=FONT_XL, fill=1)
            draw.text((2, 24), "LOGIN",  font=FONT_XL, fill=1)
            draw.text((2, 48), "Blaue Karte auflegen", font=FONT_SM, fill=1)
            return

        label = op.get("label", "?")
        name = op.get("name", "")
        role = op.get("role", "")
        since = op.get("since", "")

        # Oben: Label + Name groß (XL)
        draw.text((2, 2), f"[{label}] {name[:10]}", font=FONT_XL, fill=1)
        # Mitte: Rolle in MD
        draw.text((2, 24), role[:20], font=FONT_MD, fill=1)
        # Unten: Login-Zeit (klein) + OK-Hinweis rechtsbündig
        if since:
            draw.text((2, 40), f"seit {since}", font=FONT_MD, fill=1)
        self._text_r(draw, 126, 54, "[OK] Logout", FONT_SM)

    # ---- Seite: PATIENT (aktiver Patient) ----
    def _render_patient(self, draw: ImageDraw):
        p = self.active_patient_info
        if not p or not p.get("patient_id"):
            draw.text((2, 4),  "KEIN",    font=FONT_XL, fill=1)
            draw.text((2, 24), "PATIENT", font=FONT_XL, fill=1)
            return

        name = (p.get("name") or "").strip() or "Unbekannt"
        triage = p.get("triage", "")
        flow = p.get("flow_status", "")

        # Name oben (XL), max 10 Zeichen
        draw.text((2, 2), name[:10], font=FONT_XL, fill=1)
        # Triage mittig, groß
        if triage:
            draw.text((2, 24), f"Triage: {triage}", font=FONT_MD, fill=1)
        # Flow-Status unten
        if flow:
            draw.text((2, 44), flow[:20], font=FONT_MD, fill=1)

    # ---- Seite: KARTE SCHREIBEN ----
    def _render_cardwrite(self, draw: ImageDraw):
        c = self.cardwrite_info
        if not c.get("operator_logged_in", False):
            draw.text((2, 4),  "KEIN",   font=FONT_XL, fill=1)
            draw.text((2, 24), "LOGIN",  font=FONT_XL, fill=1)
            draw.text((2, 48), "Blaue Karte auflegen", font=FONT_SM, fill=1)
            return
        if not c.get("has_permission", False):
            draw.text((2, 4),  "KEINE", font=FONT_XL, fill=1)
            draw.text((2, 24), "RECHTE", font=FONT_XL, fill=1)
            return
        if not c.get("has_active_patient", False):
            draw.text((2, 4),  "KEIN",    font=FONT_XL, fill=1)
            draw.text((2, 24), "PATIENT", font=FONT_XL, fill=1)
            return

        name = (c.get("patient_name") or c.get("patient_id", ""))[:10]
        triage = c.get("triage", "")

        # Patient oben groß
        draw.text((2, 2), name, font=FONT_XL, fill=1)
        if triage:
            draw.text((2, 24), f"Triage: {triage}", font=FONT_MD, fill=1)
        # Call-to-Action unten invertiert in einem Kasten
        draw.rectangle([0, 44, WIDTH - 1, 63], fill=1)
        draw.text((4, 47), "[OK] SCHREIBEN", font=FONT_MD, fill=0)


# Singleton für globalen Zugriff
oled_menu = OledMenu()
