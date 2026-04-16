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
PAGES = ["models", "network", "operator", "patient"]
PAGE_TITLES = {
    "models": "KI-STATUS",
    "network": "VERBINDUNG",
    "operator": "LOGIN",
    "patient": "PATIENT",
}

# 2-Level-Menü: Liste von (action_id, label) pro Haupt-Screen.
# "models" und "network" haben absichtlich kein Untermenü — beides reine
# Diagnose-Screens.
# Phase 11: "operator" = LOGIN/VERWALTUNG. Untermenue bietet Chip
# registrieren (wenn keiner da ist) und manuelles Sofort-Sperren.
# Ausloggen geht weiterhin ueber das erneute Auflegen des eingeloggten Chips.
PAGE_SUBMENUS = {
    "models": [],
    "network": [],
    "operator": [
        ("register_chip", "Chip Regis."),
        ("lock_now", "Jetzt Sperren"),
    ],
    "patient": [
        ("record_toggle", "Aufnahme"),
        ("analyze_pending", "Analysieren"),
        ("send_backend", "Melden"),
        ("card_write", "RFID schreiben"),
        ("patient_delete", "Loeschen"),
    ],
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
        # 2-Level-Menü-State: submenu_open=True zeigt die Untermenü-Liste
        # des aktuellen Screens statt der normalen Content-Ansicht.
        self.submenu_open = False
        self.submenu_index = 0
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
        # Phase 11: Security-Lock. Wenn True, zeigt render() den Lock-Screen
        # statt der normalen Seiten. Wird von app.py via set_locked()
        # toggled.
        self.locked = False

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

    # ---- Navigation (2-Level-Menü) ----
    # Belegung:
    #   A short → nächste Screen-Seite (nur im Hauptmenü)
    #   A long  → Untermenü öffnen oder schließen (Toggle)
    #   B short → im Untermenü: nächster Eintrag
    #   B long  → im Untermenü: Eintrag ausführen → returns action dict
    #
    # Die alten Methoden button_up/button_down/button_ok bleiben als dünne
    # Kompatibilitäts-Wrapper, damit Altaufrufer (z. B. aus hardware.py
    # Fallback-Paths) nichts crashen.

    def button_a_short(self):
        """A kurz: Im Hauptmenü naechste Seite. Im Untermenue keine Aktion.
        Phase 11: Im Sperrzustand bleibt die Navigation auf der operator-
        Seite — Page-Wechsel wird ignoriert."""
        self._wake()
        if self.locked:
            return
        if not self.submenu_open:
            self.current_page = (self.current_page + 1) % len(PAGES)

    def button_a_long(self):
        """A lang: Untermenü toggle (rein wenn Einträge da sind, raus sonst)."""
        self._wake()
        if self.submenu_open:
            self.submenu_open = False
            self.submenu_index = 0
            return
        page = PAGES[self.current_page]
        if PAGE_SUBMENUS.get(page):
            self.submenu_open = True
            self.submenu_index = 0

    def button_b_short(self):
        """B kurz: Im Untermenü nächster Eintrag. Im Hauptmenü nichts."""
        self._wake()
        if not self.submenu_open:
            return
        page = PAGES[self.current_page]
        items = PAGE_SUBMENUS.get(page, [])
        if items:
            self.submenu_index = (self.submenu_index + 1) % len(items)

    def button_b_long(self):
        """B lang: Im Untermenü Eintrag ausführen → returns {'page': ..., 'action': ...}.
        Das Untermenü bleibt nach dem Fire offen, damit mehrere Aktionen
        ohne Re-Navigation möglich sind."""
        self._wake()
        if not self.submenu_open:
            print(f"[OLED] button_b_long: submenu geschlossen (page={PAGES[self.current_page]}) — ignoriert", flush=True)
            return None
        page = PAGES[self.current_page]
        items = PAGE_SUBMENUS.get(page, [])
        if items and 0 <= self.submenu_index < len(items):
            action_id, label = items[self.submenu_index]
            print(f"[OLED] button_b_long: FIRE page={page} idx={self.submenu_index} action={action_id} label={label!r}", flush=True)
            return {"page": page, "action": action_id, "label": label}
        print(f"[OLED] button_b_long: leeres submenu (page={page})", flush=True)
        return None

    # Kompatibilitäts-Wrapper — nicht in neuer Logik verwenden
    def button_up(self):
        self.button_a_short()

    def button_down(self):
        self.button_a_short()

    def button_ok(self):
        return self.button_b_long()

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
        # Im Status-Modus: Vollbild-Status anzeigen (auch im Sperrzustand,
        # damit Login/Logout-Bestaetigungen sichtbar sind)
        if self._status_mode:
            return self._render_fullscreen_status()

        img = Image.new("1", (WIDTH, HEIGHT), 0)  # Monochrom, schwarz
        draw = ImageDraw.Draw(img)

        # Phase 11: Im Sperrzustand zeigt das OLED nur den Sperr-Screen
        # (SAFIR / GESPERRT / Chip auflegen). Menue-Navigation ist in
        # button_a_short() blockiert solange gesperrt, der Screensaver
        # greift wie auf normalen Seiten (check_screensaver + _display_off).
        if self.locked:
            self._render_locked(draw)
            self._display_image(img)
            return img

        page = PAGES[self.current_page]

        # Untermenue hat Vorrang: zeigt Action-Liste statt Content
        if self.submenu_open:
            self._render_submenu(draw, page)
        elif page == "models":
            self._render_models_status(draw)
        elif page == "network":
            self._render_network(draw)
        elif page == "operator":
            self._render_operator(draw)
        elif page == "patient":
            self._render_patient(draw)

        # Auf Hardware-Display schreiben (falls vorhanden)
        self._display_image(img)

        return img

    def set_locked(self, locked: bool):
        """Phase 11: Lock-Screen aktivieren/deaktivieren.
        Untermenue wird beim Sperren zugeklappt + Seite auf operator
        gesetzt, damit nach dem Entsperren sofort das LOGIN-Menue
        sichtbar ist (und nicht eine random Page von vorher)."""
        self.locked = bool(locked)
        if self.locked:
            self.submenu_open = False
            self.submenu_index = 0
            try:
                self.current_page = PAGES.index("operator")
            except ValueError:
                pass

    # ---- Seite: GESPERRT (Security-Lock) ----
    def _render_locked(self, draw: ImageDraw):
        """Zeigt 'SAFIR / GESPERRT / Chip auflegen' als Vollbild-Sperr-Screen.
        Wird bei state.locked = True von render() anstelle der normalen
        Seiten angezeigt."""
        draw.text((2, 2),  "SAFIR",         font=FONT_XL, fill=1)
        draw.text((2, 26), "GESPERRT",      font=FONT_XL, fill=1)
        draw.text((2, 50), "Chip auflegen", font=FONT_MD, fill=1)

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

    # ---- Seite: VERBINDUNG ----
    def _render_network(self, draw: ImageDraw):
        """Vier Zeilen, nichts anderes. Keine Uhr, keine Page-Dots.
          Z1: VERBINDUNG (Screen-Titel)
          Z2: Verbindungstyp (ETHERNET / WLAN-SSID / OHNE NETZ)
          Z3: Lokale IP (IP 192.168.x.y) oder 'IP --'
          Z4: Tailscale-IP (T:100.126.179.27) oder 'T: --'
        """
        n = self.network_info or {}
        wifi_state = n.get("wifi_state", "")
        wifi_ssid = n.get("wifi_ssid", "")
        wifi_ip = n.get("wifi_ip", "")
        eth_ip = n.get("eth_ip", "")
        ts_state = n.get("tailscale", "")
        ts_ip = n.get("tailscale_ip", "")

        # Z1 (y=2): Screen-Titel
        draw.text((2, 2), "VERBINDUNG", font=FONT_MD, fill=1)

        # Z2 (y=18): Verbindungstyp
        if wifi_state == "connected" and wifi_ssid:
            draw.text((2, 18), wifi_ssid[:14], font=FONT_LG, fill=1)
            primary_ip = wifi_ip
        elif wifi_state == "connected":
            draw.text((2, 18), "WLAN", font=FONT_LG, fill=1)
            primary_ip = wifi_ip
        elif eth_ip:
            draw.text((2, 18), "ETHERNET", font=FONT_LG, fill=1)
            primary_ip = eth_ip
        elif wifi_state == "connecting":
            draw.text((2, 18), "WLAN ?", font=FONT_LG, fill=1)
            primary_ip = ""
        else:
            draw.text((2, 18), "OHNE NETZ", font=FONT_LG, fill=1)
            primary_ip = ""

        # Z3 (y=36): Lokale IP
        if primary_ip:
            draw.text((2, 36), f"IP {primary_ip}", font=FONT_MD, fill=1)
        else:
            draw.text((2, 36), "IP --", font=FONT_MD, fill=1)

        # Z4 (y=50): Tailscale-IP
        if ts_state == "online" and ts_ip:
            ts_text = f"T:{ts_ip}"
        elif ts_state == "online":
            ts_text = "T: online"
        elif ts_state == "offline":
            ts_text = "T: offline"
        else:
            ts_text = "T: --"
        draw.text((2, 50), ts_text, font=FONT_MD, fill=1)

    # ---- Seite: LOGIN / VERWALTUNG ----
    # Layout (User-Spec): zwei XL-Zeilen "LOGIN" + "VERWALTUNG",
    # darunter optional eine Info-Zeile "[USER 1]" wenn eingeloggt.
    # Kein Footer-Hinweis, keine Rollen-Zeile, keine Seit-Zeile —
    # alles bewusst kurz gehalten.
    def _render_operator(self, draw: ImageDraw):
        draw.text((2, 2),  "LOGIN",      font=FONT_XL, fill=1)
        draw.text((2, 24), "VERWALTUNG", font=FONT_XL, fill=1)

        op = self.operator_info
        if op.get("logged_in", False):
            # Label in eckigen Klammern (z.B. '[OP1]' oder '[OFA]'),
            # FONT_MD damit es unter den XL-Zeilen lesbar Platz findet.
            label = op.get("label", "?")
            draw.text((2, 50), f"[{label}]", font=FONT_MD, fill=1)

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

    # ---- Untermenü-Liste (2-Level-Menü) ----
    def _render_submenu(self, draw: ImageDraw, page: str):
        """Zeichnet die Action-Liste des aktuellen Screens. Selektiertes
        Item ist invertiert (weißer Balken, schwarze Schrift). Nutzt FONT_MD
        (11 px) mit 12-px-Zeilen — 5 Items passen in 64 px Höhe bei guter
        Lesbarkeit."""
        items = PAGE_SUBMENUS.get(page, [])
        if not items:
            draw.text((2, 20), "KEIN UNTERMENU", font=FONT_MD, fill=1)
            draw.text((2, 40), "A lang = zurueck", font=FONT_SM, fill=1)
            return

        y = 2
        for i, (_, label) in enumerate(items):
            if i == self.submenu_index:
                draw.rectangle([0, y - 1, WIDTH - 1, y + 11], fill=1)
                draw.text((3, y), f"> {label}", font=FONT_MD, fill=0)
            else:
                draw.text((3, y), f"  {label}", font=FONT_MD, fill=1)
            y += 12


# Singleton für globalen Zugriff
oled_menu = OledMenu()
