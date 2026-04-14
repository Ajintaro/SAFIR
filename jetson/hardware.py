#!/usr/bin/env python3
"""
SAFIR Hardware-Service — zentrale Integration für Jetson-Feldgerät

Bündelt:
  - 2 Metzler Drucktaster (Pin 11 = Taster A/rot, Pin 26 = Taster B/grün)
  - 2 LEDs über BC547 (Pin 15 = rot, Pin 13 = grün)
  - OLED SSD1306 (via jetson/oled.py, wird injiziert)
  - Shutdown-Geste (beide Taster 3 s gleichzeitig)
  - Statusampel-Logik (Systemzustand → LED-Muster)

Läuft als async Service, wird in app.py Startup gestartet und im Shutdown
sauber gestoppt. Geht bewusst direkt auf Jetson.GPIO (BOARD-Modus) statt
einer High-Level-Bibliothek, weil der RC522-Bit-Bang-Treiber in shared/rfid.py
denselben Backend nutzt — beide teilen sich GPIO.setmode(BOARD).
"""

import asyncio
import logging
import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

log = logging.getLogger("safir.hardware")


# ---------------------------------------------------------------------------
# Enums & Datentypen
# ---------------------------------------------------------------------------
class LedPattern(Enum):
    """Ansteuerungs-Muster für eine einzelne LED."""
    OFF = "off"
    ON = "on"
    BLINK_SLOW = "blink_slow"   # 1 Hz Rechteck
    BLINK_FAST = "blink_fast"   # 5 Hz Rechteck
    PULSE = "pulse"             # 0.5 Hz Breathing via Software-PWM


class SystemState(Enum):
    """Grob-Zustand des Gesamtsystems — steuert die Status-LEDs."""
    BOOT = "boot"                              # grün aus, rot aus
    IDLE = "idle"                              # grün PULSE, rot aus
    ACTIVE = "active"                          # grün ON, rot aus (Aufnahme/LLM)
    WARNING = "warning"                        # grün PULSE, rot BLINK_SLOW
    SHUTDOWN_COUNTDOWN = "shutdown_countdown"  # grün ON, rot BLINK_FAST
    ERROR = "error"                            # grün OFF, rot ON


@dataclass
class ButtonEvent:
    """Event das der ButtonDriver über den Callback liefert."""
    kind: str                     # "short", "long", "combo_start",
                                  # "combo_progress", "combo_cancel", "combo_fire"
    button: Optional[str] = None  # "A" oder "B" (None bei combo_*)
    hold_seconds: float = 0.0     # nur bei combo_progress/fire


# ---------------------------------------------------------------------------
# LED-Controller
# ---------------------------------------------------------------------------
class LedController:
    """
    Steuert beide LEDs (rot + grün) asynchron über Pattern-Tick.

    HIGH auf dem GPIO schaltet den BC547-NPN durch, LED leuchtet.
    Software-PWM für PULSE: Duty-Cycle wird in 20 ms Ticks moduliert.
    """

    TICK_MS = 20  # 50 Hz Tick-Rate

    def __init__(self, gpio, red_pin: int, green_pin: int):
        self._gpio = gpio
        self._red_pin = red_pin
        self._green_pin = green_pin
        self._red = LedPattern.OFF
        self._green = LedPattern.OFF
        self._running = False
        self._task: Optional[asyncio.Task] = None

        gpio.setup(red_pin, gpio.OUT, initial=gpio.LOW)
        gpio.setup(green_pin, gpio.OUT, initial=gpio.LOW)

    def set(self, red: Optional[LedPattern] = None,
            green: Optional[LedPattern] = None):
        """Setzt ein oder beide LED-Muster."""
        if red is not None:
            self._red = red
        if green is not None:
            self._green = green

    def get(self) -> tuple[LedPattern, LedPattern]:
        return self._red, self._green

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # LEDs aus
        try:
            self._gpio.output(self._red_pin, self._gpio.LOW)
            self._gpio.output(self._green_pin, self._gpio.LOW)
        except Exception:
            pass

    async def _run(self):
        """Tick-Loop der beide LEDs entsprechend dem aktuellen Pattern ansteuert."""
        t0 = time.monotonic()
        try:
            while self._running:
                now = time.monotonic() - t0
                self._apply(self._red_pin, self._red, now)
                self._apply(self._green_pin, self._green, now)
                await asyncio.sleep(self.TICK_MS / 1000)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error(f"LedController loop crashed: {e}")

    def _apply(self, pin: int, pattern: LedPattern, t: float):
        """Berechnet den Pin-Zustand für Zeitpunkt t (Sekunden seit Start)."""
        if pattern == LedPattern.OFF:
            self._gpio.output(pin, self._gpio.LOW)
        elif pattern == LedPattern.ON:
            self._gpio.output(pin, self._gpio.HIGH)
        elif pattern == LedPattern.BLINK_SLOW:
            # 1 Hz: 500 ms an, 500 ms aus
            on = (t % 1.0) < 0.5
            self._gpio.output(pin, self._gpio.HIGH if on else self._gpio.LOW)
        elif pattern == LedPattern.BLINK_FAST:
            # 5 Hz: 100 ms an, 100 ms aus
            on = (t % 0.2) < 0.1
            self._gpio.output(pin, self._gpio.HIGH if on else self._gpio.LOW)
        elif pattern == LedPattern.PULSE:
            # 0.5 Hz Rechteck — 1 s an, 1 s aus. Ersetzt das vorherige
            # Software-PWM-Breathing, das wegen Tick-Jitter gezappelt hat.
            # Ohne Hardware-PWM ist ein stabiles Blink besser als flackerndes "Atmen".
            on = (t % 2.0) < 1.0
            self._gpio.output(pin, self._gpio.HIGH if on else self._gpio.LOW)


# ---------------------------------------------------------------------------
# Button-Driver
# ---------------------------------------------------------------------------
class ButtonDriver:
    """
    Liest beide Taster per Polling, erkennt Short-Press, Long-Press und
    Combo-Geste (beide gleichzeitig für N Sekunden).

    Taster sind Active-LOW (Pin LOW = gedrückt) über externen 150 Ω Pull-Up zu 3.3 V.
    Interner Pull-Up von Jetson.GPIO funktioniert nicht — externe Widerstände
    sind zwingend verdrahtet (siehe Memory hardware_buttons_pinout).
    """

    POLL_MS = 20

    def __init__(
        self,
        gpio,
        pin_a: int,
        pin_b: int,
        debounce_ms: int = 30,
        long_press_s: float = 2.0,
        combo_s: float = 3.0,
        on_event: Optional[Callable[[ButtonEvent], None]] = None,
    ):
        self._gpio = gpio
        self._pin_a = pin_a
        self._pin_b = pin_b
        self._debounce = debounce_ms / 1000
        self._long_press = long_press_s
        self._combo = combo_s
        self._on_event = on_event

        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Zustand pro Taster
        self._state_a = {"pressed": False, "since": 0.0, "consumed": False}
        self._state_b = {"pressed": False, "since": 0.0, "consumed": False}
        # Combo-Zustand
        self._combo_active = False
        self._combo_since = 0.0
        self._combo_last_progress = -1.0
        # Latch: nach combo_fire True, bis beide Taster losgelassen sind.
        # Verhindert dass der Countdown nach Ablauf erneut startet wenn die
        # Taster noch gehalten werden (Dauerschleifen-Bug).
        self._combo_latched = False

        gpio.setup(pin_a, gpio.IN)
        gpio.setup(pin_b, gpio.IN)

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def _emit(self, event: ButtonEvent):
        if self._on_event is None:
            return
        try:
            self._on_event(event)
        except Exception as e:
            log.error(f"Button event callback crashed: {e}")

    async def _run(self):
        last_a_raw = False
        last_b_raw = False
        last_a_change = 0.0
        last_b_change = 0.0
        try:
            while self._running:
                now = time.monotonic()
                a_raw = self._gpio.input(self._pin_a) == self._gpio.LOW
                b_raw = self._gpio.input(self._pin_b) == self._gpio.LOW

                # Debounce-Flanken-Erkennung
                if a_raw != last_a_raw:
                    last_a_change = now
                    last_a_raw = a_raw
                if b_raw != last_b_raw:
                    last_b_change = now
                    last_b_raw = b_raw

                a_stable = (now - last_a_change) >= self._debounce
                b_stable = (now - last_b_change) >= self._debounce

                if a_stable:
                    self._update_single("A", a_raw, now)
                if b_stable:
                    self._update_single("B", b_raw, now)

                self._update_combo(a_raw, b_raw, now)

                await asyncio.sleep(self.POLL_MS / 1000)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error(f"ButtonDriver loop crashed: {e}")

    def _update_single(self, name: str, pressed: bool, now: float):
        """Flankenerkennung + Short/Long-Emission für einen einzelnen Taster.

        Wichtig: wenn gerade eine Combo läuft, werden Single-Events unterdrückt
        damit nicht gleichzeitig combo_fire UND long_press emittiert wird.
        """
        state = self._state_a if name == "A" else self._state_b
        if pressed and not state["pressed"]:
            # Flanke runter → Press-Start, consumed-Flag zurücksetzen
            state["pressed"] = True
            state["since"] = now
            state["consumed"] = False
        elif not pressed and state["pressed"]:
            # Flanke hoch → Release. consumed bleibt bis zum NÄCHSTEN Press
            # stehen, damit ein Combo-Abbruch nicht nachträglich doch noch
            # Single-Presses emittiert (Bug bei Combo-Cancel-Nachläufer).
            state["pressed"] = False
            held = now - state["since"]
            if state["consumed"] or self._combo_active:
                return
            if held >= self._long_press:
                self._emit(ButtonEvent(kind="long", button=name, hold_seconds=held))
            else:
                self._emit(ButtonEvent(kind="short", button=name, hold_seconds=held))

    def _update_combo(self, a_pressed: bool, b_pressed: bool, now: float):
        """Erkennt dass beide Taster gleichzeitig gehalten werden (Shutdown-Geste)."""
        both = a_pressed and b_pressed
        # Latch freigeben sobald beide Taster losgelassen sind
        if self._combo_latched and not a_pressed and not b_pressed:
            self._combo_latched = False
        if both and not self._combo_active and not self._combo_latched:
            # Combo startet
            self._combo_active = True
            self._combo_since = now
            self._combo_last_progress = -1.0
            # Single-Press-Emissions für diese Taster unterdrücken
            self._state_a["consumed"] = True
            self._state_b["consumed"] = True
            self._emit(ButtonEvent(kind="combo_start"))
        elif self._combo_active:
            elapsed = now - self._combo_since
            if both:
                # Progress-Event alle 100 ms
                if elapsed - self._combo_last_progress >= 0.1:
                    self._combo_last_progress = elapsed
                    self._emit(ButtonEvent(kind="combo_progress", hold_seconds=elapsed))
                # Fire bei Erreichen der Combo-Schwelle
                if elapsed >= self._combo:
                    self._combo_active = False
                    self._combo_latched = True
                    self._emit(ButtonEvent(kind="combo_fire", hold_seconds=elapsed))
            else:
                # Einer (oder beide) losgelassen bevor Schwelle erreicht
                self._combo_active = False
                self._emit(ButtonEvent(kind="combo_cancel", hold_seconds=elapsed))


# ---------------------------------------------------------------------------
# RFID-Service — kontinuierliches Polling des RC522 in einem Executor-Thread
# ---------------------------------------------------------------------------
class RfidService:
    """
    Hintergrund-Task der den RC522 kontinuierlich nach Karten pollt.

    Das eigentliche rc522_read_uid() aus shared/rfid.py ist blockierend und
    nutzt Bit-Bang-SPI. Wir rufen es deshalb über loop.run_in_executor auf,
    damit der Event-Loop nicht blockiert. Gleiche UIDs werden 2 s lang
    gedebounced (sonst feuert bei aufgelegter Karte jeder Poll).
    """

    POLL_TIMEOUT = 0.3      # Sekunden pro Blocking-Read
    DEBOUNCE_SECONDS = 2.0  # gleiche UID nicht öfter als alle 2 s

    def __init__(self, on_scan: Optional[Callable[[str], None]] = None):
        self._on_scan = on_scan
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_uid: Optional[str] = None
        self._last_uid_ts: float = 0.0
        self._pending_scan: Optional[asyncio.Future] = None  # für await_next_scan()

    async def start(self):
        from shared import rfid as _rfid
        if not _rfid.is_rc522_available():
            ok = _rfid.rc522_init()
            if not ok:
                log.warning("RfidService: RC522 nicht erkannt — Service inaktiv")
                return
        self._running = True
        self._task = asyncio.create_task(self._run())
        log.info("RfidService gestartet (Poll-Loop aktiv)")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self):
        """Endlosschleife: pollt RC522, emittiert Scan-Events."""
        from shared import rfid as _rfid
        loop = asyncio.get_event_loop()
        try:
            while self._running:
                try:
                    uid = await loop.run_in_executor(
                        None, _rfid.rc522_read_uid, self.POLL_TIMEOUT
                    )
                except Exception as e:
                    log.error(f"RfidService poll error: {e}")
                    await asyncio.sleep(0.5)
                    continue

                if uid is None:
                    # Kein Scan in diesem Intervall — Debounce zurücksetzen
                    # wenn Karte gerade entfernt wurde
                    if self._last_uid is not None and \
                            (time.monotonic() - self._last_uid_ts) > self.DEBOUNCE_SECONDS:
                        self._last_uid = None
                    continue

                now = time.monotonic()
                if uid == self._last_uid and (now - self._last_uid_ts) < self.DEBOUNCE_SECONDS:
                    # Gleiche Karte noch im Debounce-Fenster — ignorieren
                    continue

                self._last_uid = uid
                self._last_uid_ts = now
                self._emit(uid)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error(f"RfidService loop crashed: {e}")

    def _emit(self, uid: str):
        # Pending await_next_scan() auflösen
        if self._pending_scan is not None and not self._pending_scan.done():
            self._pending_scan.set_result(uid)
            return  # nicht doppelt emittieren — die pending action verbraucht den Scan

        if self._on_scan:
            try:
                self._on_scan(uid)
            except Exception as e:
                log.error(f"RFID on_scan callback crashed: {e}")

    async def await_next_scan(self, timeout: float = 10.0) -> Optional[str]:
        """Wartet auf den nächsten RFID-Scan (für Voice-Command-Flows wie 'karte schreiben').

        Während ein await_next_scan() läuft, wird der normale on_scan-Callback
        übergangen — der Scan geht exklusiv an den Waiter.
        """
        loop = asyncio.get_event_loop()
        self._pending_scan = loop.create_future()
        try:
            return await asyncio.wait_for(self._pending_scan, timeout=timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self._pending_scan = None


# ---------------------------------------------------------------------------
# Hardware-Service
# ---------------------------------------------------------------------------
class HardwareService:
    """
    Hauptklasse die alle Subsysteme bündelt und in app.py angedockt wird.

    Lifecycle:
        hw = HardwareService(config, oled_menu, on_rfid_scan)
        await hw.start()   # im FastAPI Startup
        ...
        await hw.stop()    # im FastAPI Shutdown
    """

    def __init__(
        self,
        config: dict,
        oled_menu,
        on_rfid_scan: Optional[Callable[[str], None]] = None,
        on_oled_action: Optional[Callable[[dict], None]] = None,
    ):
        self._config = config
        self._oled = oled_menu
        self._on_rfid_scan_cb = on_rfid_scan
        self._on_oled_action_cb = on_oled_action

        hw = config.get("hardware", {})
        self._btn_a_pin = hw.get("button_a", {}).get("gpio_pin", 11)
        self._btn_b_pin = hw.get("button_b", {}).get("gpio_pin", 26)
        self._led_a_pin = hw.get("button_a", {}).get("led_pin", 15)  # Taster A = rot
        self._led_b_pin = hw.get("button_b", {}).get("led_pin", 13)  # Taster B = grün
        self._long_press_s = hw.get("long_press_seconds", 2.0)
        self._combo_s = hw.get("shutdown_combo_seconds", 3.0)
        self._debounce_ms = hw.get("debounce_ms", 30)

        # Bei uns: rot = LED an Taster A (Pin 15), grün = LED an Taster B (Pin 13)
        self._red_pin = self._led_a_pin
        self._green_pin = self._led_b_pin

        self._gpio = None
        self._buttons: Optional[ButtonDriver] = None
        self._leds: Optional[LedController] = None
        self._rfid: Optional[RfidService] = None
        self._system_state = SystemState.BOOT
        self._started = False
        self._shutdown_in_progress = False
        self._button_counts = {"A_short": 0, "A_long": 0, "B_short": 0, "B_long": 0}

        # Zustand vor Shutdown-Countdown (um LEDs wiederherzustellen bei Abbruch)
        self._pre_shutdown_state: Optional[SystemState] = None

    def set_rfid_callback(self, cb: Callable[[str], None]):
        """Erlaubt nachträgliches Setzen des RFID-Callbacks (z.B. wenn Service
        vor der Scan-Routing-Funktion instanziert wurde)."""
        self._on_rfid_scan_cb = cb

    def set_oled_action_callback(self, cb: Callable[[dict], None]):
        """Setzt den Callback der nach einem Button-B-OK-Druck gerufen wird.

        Der Callback bekommt das Dict das OledMenu.button_ok() zurückgibt
        (z.B. {'page': 'cardwrite', 'action': 'ok'}) und kann daraus
        seitenspezifische Aktionen ableiten. Wenn der Callback eine Coroutine
        zurückgibt, wird diese automatisch als asyncio-Task gescheduled.
        """
        self._on_oled_action_cb = cb

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------
    async def start(self):
        if self._started:
            return
        try:
            import Jetson.GPIO as GPIO
            self._gpio = GPIO
            GPIO.setmode(GPIO.BOARD)
            GPIO.setwarnings(False)
        except Exception as e:
            log.error(f"Jetson.GPIO nicht verfügbar — Hardware-Service inaktiv: {e}")
            return

        self._leds = LedController(self._gpio, self._red_pin, self._green_pin)
        self._buttons = ButtonDriver(
            self._gpio,
            self._btn_a_pin,
            self._btn_b_pin,
            debounce_ms=self._debounce_ms,
            long_press_s=self._long_press_s,
            combo_s=self._combo_s,
            on_event=self._handle_button_event,
        )

        await self._leds.start()
        await self._buttons.start()

        # RFID-Service starten (pollt RC522 in Executor-Thread)
        self._rfid = RfidService(on_scan=self._on_rfid_scan)
        await self._rfid.start()

        self.set_system_state(SystemState.IDLE)
        self._started = True
        msg = (
            f"HardwareService gestartet — Taster A=Pin{self._btn_a_pin}(rot), "
            f"Taster B=Pin{self._btn_b_pin}(grün), "
            f"Long-Press={self._long_press_s}s, Combo={self._combo_s}s"
        )
        log.info(msg)
        print(f"[HW] {msg}", flush=True)

    async def stop(self):
        if not self._started:
            return
        try:
            if self._rfid:
                await self._rfid.stop()
            if self._buttons:
                await self._buttons.stop()
            if self._leds:
                await self._leds.stop()
        finally:
            self._started = False
            # GPIO.cleanup() NICHT hier — shared/rfid.py nutzt dieselben GPIOs
            # und könnte danach noch aktiv sein. app.py Shutdown macht das global.

    # -----------------------------------------------------------------------
    # RFID-Routing
    # -----------------------------------------------------------------------
    def _on_rfid_scan(self, uid: str):
        """Wird vom RfidService bei jedem neuen Scan synchron gerufen."""
        log.info(f"RFID-Scan: UID {uid}")
        if self._on_rfid_scan_cb:
            try:
                self._on_rfid_scan_cb(uid)
            except Exception as e:
                log.error(f"RFID app callback crashed: {e}")

    async def await_rfid_scan(self, timeout: float = 10.0) -> Optional[str]:
        """Für Phase 7: wartet exklusiv auf den nächsten Scan (z.B. 'karte schreiben')."""
        if not self._rfid:
            return None
        return await self._rfid.await_next_scan(timeout)

    # -----------------------------------------------------------------------
    # System-Zustand → LED-Mapping
    # -----------------------------------------------------------------------
    def set_system_state(self, new_state: SystemState):
        """Wird von app.py / anderen Komponenten gerufen um den LED-Zustand zu aktualisieren.

        Prinzip: LEDs sind **dunkel im Normalzustand** — sie reagieren nur auf
        Ereignisse und Warnungen. Das OLED übernimmt die kontinuierliche
        Statusanzeige. Das spart Strom und ist weniger ablenkend.
        """
        if not self._leds:
            return
        self._system_state = new_state
        if new_state == SystemState.BOOT:
            self._leds.set(red=LedPattern.OFF, green=LedPattern.OFF)
        elif new_state == SystemState.IDLE:
            # Idle = beide aus. Keine Heartbeat-Anzeige — OLED zeigt den Status.
            self._leds.set(red=LedPattern.OFF, green=LedPattern.OFF)
        elif new_state == SystemState.ACTIVE:
            # Aktive Aufnahme / LLM-Verarbeitung: grün steady an
            self._leds.set(red=LedPattern.OFF, green=LedPattern.ON)
        elif new_state == SystemState.WARNING:
            # Warnung: nur rot langsam blinken, grün aus
            self._leds.set(red=LedPattern.BLINK_SLOW, green=LedPattern.OFF)
        elif new_state == SystemState.SHUTDOWN_COUNTDOWN:
            # Shutdown-Countdown: rot schnell blinken, grün aus
            self._leds.set(red=LedPattern.BLINK_FAST, green=LedPattern.OFF)
        elif new_state == SystemState.ERROR:
            # Kritischer Fehler: rot steady
            self._leds.set(red=LedPattern.ON, green=LedPattern.OFF)

    def get_system_state(self) -> SystemState:
        return self._system_state

    def get_button_counts(self) -> dict:
        """Zählt gedrückte Taster seit Service-Start (für HARDWARE-OLED-Seite)."""
        return dict(self._button_counts)

    async def flash_success(self, duration: float = 1.0):
        """3× schnelles Grün-Blinken als Erfolgsbestätigung, dann zurück zum vorigen Zustand."""
        if not self._leds:
            return
        prev_red, prev_green = self._leds.get()
        self._leds.set(green=LedPattern.BLINK_FAST)
        await asyncio.sleep(duration)
        self._leds.set(red=prev_red, green=prev_green)

    async def flash_error(self, duration: float = 1.5):
        """Rot schnell blinken als Fehlerhinweis."""
        if not self._leds:
            return
        prev_red, prev_green = self._leds.get()
        self._leds.set(red=LedPattern.BLINK_FAST)
        await asyncio.sleep(duration)
        self._leds.set(red=prev_red, green=prev_green)

    # -----------------------------------------------------------------------
    # Button-Handler
    # -----------------------------------------------------------------------
    def _handle_button_event(self, event: ButtonEvent):
        """Wird synchron aus dem ButtonDriver-Task gerufen. Muss schnell sein.

        Für länger laufende Reaktionen (Combo-Countdown, Shutdown) schedulen
        wir asyncio-Tasks. Einfache OLED-Navigation erfolgt direkt.
        """
        print(f"[HW] Button event: kind={event.kind} btn={event.button} held={event.hold_seconds:.2f}", flush=True)

        if event.kind == "combo_start":
            asyncio.create_task(self._on_combo_start())
            return
        if event.kind == "combo_progress":
            # progress-Events werden durch _on_combo_start() selbst gepollt —
            # wir verwerfen sie hier und nutzen nur start/cancel/fire als Triggers.
            return
        if event.kind == "combo_cancel":
            asyncio.create_task(self._on_combo_cancel())
            return
        if event.kind == "combo_fire":
            asyncio.create_task(self._on_combo_fire())
            return

        # Single-Press: Wake-Gate — wenn OLED im Standby war, nur wecken.
        was_sleeping = getattr(self._oled, "is_sleeping", False)
        try:
            self._oled.wake()
        except AttributeError:
            # Fallback für ältere OLED-API ohne public wake()
            if hasattr(self._oled, "_wake"):
                self._oled._wake()

        if was_sleeping:
            log.info(f"OLED wake-only: {event.kind} {event.button}")
            return

        # Counter hochzählen
        key = f"{event.button}_{event.kind}"
        if key in self._button_counts:
            self._button_counts[key] += 1

        # Action-Routing (nur wenn OLED schon wach war)
        if event.button == "A" and event.kind == "short":
            self._oled.button_down()  # A kurz → nächste Seite
        elif event.button == "A" and event.kind == "long":
            self._oled.button_up()    # A lang → vorherige Seite
        elif event.button == "B" and event.kind == "short":
            result = self._oled.button_ok()  # B kurz → Seiten-Aktion
            if result and self._on_oled_action_cb:
                try:
                    ret = self._on_oled_action_cb(result)
                    if asyncio.iscoroutine(ret):
                        asyncio.create_task(ret)
                except Exception as e:
                    log.error(f"OLED action callback crashed: {e}")
        elif event.button == "B" and event.kind == "long":
            # Reserviert für spätere Funktion
            log.info("Button B long-press (noch nicht belegt)")

    # -----------------------------------------------------------------------
    # Shutdown-Geste
    # -----------------------------------------------------------------------
    async def _on_combo_start(self):
        """Beide Taster gedrückt — Countdown starten."""
        if self._shutdown_in_progress:
            return
        log.info("Shutdown-Geste erkannt — Countdown läuft")
        self._pre_shutdown_state = self._system_state
        self.set_system_state(SystemState.SHUTDOWN_COUNTDOWN)
        try:
            self._oled.wake()
        except Exception:
            pass

    async def _on_combo_cancel(self):
        """Ein Taster losgelassen bevor 3 s erreicht — abbrechen."""
        log.info("Shutdown-Geste abgebrochen")
        if self._pre_shutdown_state is not None:
            self.set_system_state(self._pre_shutdown_state)
        self._pre_shutdown_state = None
        try:
            self._oled.show_status("ABGEBROCHEN", "Shutdown verworfen")
            await asyncio.sleep(1.0)
            self._oled.clear_status()
        except Exception:
            pass

    async def _on_combo_fire(self):
        """3 s erreicht — Shutdown ausführen."""
        if self._shutdown_in_progress:
            return
        self._shutdown_in_progress = True
        log.warning("Shutdown-Geste bestätigt — System wird heruntergefahren")
        try:
            self._oled.show_status("SHUTDOWN", "SAFIR stoppt")
        except Exception:
            pass
        self.set_system_state(SystemState.ERROR)  # rot steady, grün aus
        await asyncio.sleep(1.0)

        # sudo shutdown -h now — setzt voraus dass /etc/sudoers.d/safir konfiguriert ist
        try:
            subprocess.Popen(
                ["sudo", "-n", "shutdown", "-h", "now"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            log.error(f"shutdown-Aufruf fehlgeschlagen: {e}")
            try:
                self._oled.show_status("FEHLER", "sudo shutdown fehlt")
            except Exception:
                pass
            self._shutdown_in_progress = False
            self.set_system_state(self._pre_shutdown_state or SystemState.IDLE)

    # -----------------------------------------------------------------------
    # Countdown-Rendering (wird periodisch aus dem OLED-Update-Loop gerufen)
    # -----------------------------------------------------------------------
    def render_shutdown_countdown_if_active(self) -> bool:
        """
        Gibt True zurück wenn gerade ein Countdown läuft und das OLED diesen
        anstelle des normalen Menüs anzeigen soll. Wird aus _oled_update_loop
        aufgerufen — die Combo-Progress-Events kommen zu schnell (alle 100 ms)
        um jeweils eigene OLED-Renders auszulösen.
        """
        if not self._buttons or not self._buttons._combo_active:
            return False
        elapsed = time.monotonic() - self._buttons._combo_since
        remaining = max(0.0, self._combo_s - elapsed)
        try:
            self._oled.show_status(
                f"SHUTDOWN {remaining:.1f}s",
                "Beide Taster halten",
                progress=int(min(100, (elapsed / self._combo_s) * 100)),
            )
        except Exception:
            pass
        return True
