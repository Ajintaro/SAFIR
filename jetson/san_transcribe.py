#!/usr/bin/env python3
"""
CGI AFCEA San-Feldeinsatz Prototyp
Echtzeit-Spracherkennung für medizinische Dokumentation im Feldeinsatz.
Nutzt whisper.cpp mit CUDA auf NVIDIA Jetson Orin Nano.

Eingabe-Modi:
  - GPIO-Button (Pin 15): Drücken = Aufnahme, Loslassen = Stop
  - Tastatur (Fallback): Enter = Start, Enter = Stop
  - Voice-Trigger (optional): Keyword "Sanitäter" startet Aufnahme
"""

import subprocess
import sounddevice as sd
import soundfile as sf
import numpy as np
import tempfile
import sys
import os
import time
import argparse
import threading
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
WHISPER_CLI = PROJECT_DIR / "whisper.cpp" / "build" / "bin" / "whisper-cli"
MODEL_PATH = PROJECT_DIR / "models" / "ggml-medium.bin"

SAMPLE_RATE = 16000
CHANNELS = 1

# GPIO-Konfiguration (40-Pin Header)
GPIO_BUTTON_RECORD = "PBB.01"  # Pin 16 - Aufnahme
GPIO_CHIP = "gpiochip0"

# LED-Feedback (optional, Pin 18 = GPIO35/PH.00)
GPIO_LED = "PH.00"


class GpioButton:
    """Hardware-Button über gpiod (libgpiod)."""

    def __init__(self, chip_name="gpiochip0", line_name="PBB.01"):
        self.available = False
        self.chip_name = chip_name
        self.line_name = line_name
        self._request = None
        try:
            import gpiod
            from gpiod.line import Bias, Direction, Edge
            self.gpiod = gpiod
            self.Bias = Bias
            self.Direction = Direction
            self.Edge = Edge
            self._setup()
        except Exception as e:
            print(f"  GPIO nicht verfügbar ({e}) - Tastatur-Modus aktiv")

    def _setup(self):
        # Finde den richtigen Chip für den AON-GPIO
        for chip_path in ["/dev/gpiochip0", "/dev/gpiochip1"]:
            try:
                chip = self.gpiod.Chip(chip_path)
                info = chip.get_info()
                for i in range(info.num_lines):
                    line_info = chip.get_line_info(i)
                    if line_info.name == self.line_name:
                        self._request = chip.request_lines(
                            consumer="san-feldprototyp",
                            config={
                                i: self.gpiod.LineSettings(
                                    direction=self.Direction.INPUT,
                                    bias=self.Bias.PULL_UP,
                                    edge_detection=self.Edge.BOTH,
                                )
                            },
                        )
                        self.available = True
                        print(f"  GPIO Button aktiv: {self.line_name} auf {chip_path}")
                        return
                chip.close()
            except Exception:
                continue

        if not self.available:
            print(f"  GPIO-Line {self.line_name} nicht gefunden - Tastatur-Modus")

    def wait_for_press(self, timeout=None):
        """Wartet auf Button-Druck. Gibt True zurück bei Druck, False bei Timeout."""
        if not self.available:
            return False
        if self._request.wait_edge_events(timeout):
            events = self._request.read_edge_events()
            for ev in events:
                if ev.event_type == ev.Type.FALLING_EDGE:
                    return True
        return False

    def wait_for_release(self, timeout=None):
        """Wartet auf Button-Loslassen."""
        if not self.available:
            return False
        if self._request.wait_edge_events(timeout):
            events = self._request.read_edge_events()
            for ev in events:
                if ev.event_type == ev.Type.RISING_EDGE:
                    return True
        return False

    def is_pressed(self):
        """Prüft ob Button gerade gedrückt ist (LOW = gedrückt)."""
        if not self.available:
            return False
        values = self._request.get_values()
        return list(values.values())[0] == self.gpiod.line.Value.ACTIVE

    def close(self):
        if self._request:
            self._request.release()


class AudioRecorder:
    """Nimmt Audio auf, gesteuert durch Button oder Stille-Erkennung."""

    def __init__(self, device=None):
        self.device = device
        self.chunks = []
        self.recording = False
        self._stream = None

    def _callback(self, indata, frames, time_info, status):
        if self.recording:
            self.chunks.append(indata.copy())

    def start(self):
        """Startet die Aufnahme."""
        self.chunks = []
        self.recording = True
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=CHANNELS,
            dtype="float32", blocksize=int(SAMPLE_RATE * 0.1),
            device=self.device, callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> np.ndarray:
        """Stoppt die Aufnahme und gibt Audio zurück."""
        self.recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        if not self.chunks:
            return np.array([], dtype="float32")

        audio = np.concatenate(self.chunks, axis=0)
        return audio

    def record_until_silence(self, silence_thresh=0.01, silence_duration=2.0,
                             max_duration=30.0) -> np.ndarray:
        """Nimmt auf bis Stille erkannt wird."""
        self.start()
        silent_count = 0
        silence_blocks = int(silence_duration / 0.1)
        max_blocks = int(max_duration / 0.1)

        while silent_count < silence_blocks and len(self.chunks) < max_blocks:
            sd.sleep(100)
            if self.chunks:
                rms = np.sqrt(np.mean(self.chunks[-1] ** 2))
                if rms < silence_thresh:
                    silent_count += 1
                else:
                    silent_count = 0

        return self.stop()


def list_audio_devices():
    """Zeigt verfügbare Audio-Eingabegeräte."""
    print("\nVerfügbare Audio-Eingabegeräte:")
    print("-" * 50)
    devices = sd.query_devices()
    for i, dev in enumerate(devices):
        if dev["max_input_channels"] > 0:
            marker = " <-- DEFAULT" if i == sd.default.device[0] else ""
            print(f"  [{i}] {dev['name']} (Kanäle: {dev['max_input_channels']}){marker}")
    print()


def transcribe(audio: np.ndarray, language: str = "de") -> str:
    """Transkribiert Audio mit whisper.cpp (CUDA)."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = f.name
        sf.write(wav_path, audio, SAMPLE_RATE)

    try:
        cmd = [
            str(WHISPER_CLI),
            "-m", str(MODEL_PATH),
            "-f", wav_path,
            "-l", language,
            "--no-timestamps",
            "-t", "4",
            "-np",
        ]

        env = os.environ.copy()
        env["PATH"] = "/usr/local/cuda/bin:" + env.get("PATH", "")

        start = time.time()
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        elapsed = time.time() - start

        if result.returncode != 0:
            print(f"  FEHLER: {result.stderr[:500]}")
            return ""

        text = result.stdout.strip()
        audio_duration = len(audio) / SAMPLE_RATE
        rtf = elapsed / audio_duration if audio_duration > 0 else 0
        print(f"  [{elapsed:.1f}s, RTF {rtf:.2f}x]")
        return text
    finally:
        os.unlink(wav_path)


def run_gpio_mode(recorder, button, language):
    """Hauptschleife mit GPIO-Button: Drücken=Aufnahme, Loslassen=Stop."""
    records = []
    print("\n  Modus: GPIO-Button (gedrückt halten = Aufnahme)")
    print("  Ctrl+C zum Beenden\n")

    try:
        while True:
            print("  Warte auf Button-Druck...", end="", flush=True)
            button.wait_for_press()
            print(" AUFNAHME", flush=True)

            recorder.start()

            # Warte auf Loslassen oder max 60s
            button.wait_for_release(timeout=60)

            audio = recorder.stop()
            duration = len(audio) / SAMPLE_RATE
            print(f"  ({duration:.1f}s aufgenommen)")

            if len(audio) < SAMPLE_RATE * 0.5:
                print("  Zu kurz, übersprungen.")
                continue

            text = transcribe(audio, language=language)
            if text:
                print(f"\n  >> {text}\n")
                records.append({"time": time.strftime("%H:%M:%S"), "text": text})

    except KeyboardInterrupt:
        print("\n")

    return records


def run_keyboard_mode(recorder, language, use_silence=True):
    """Hauptschleife mit Tastatur-Steuerung."""
    records = []

    try:
        while True:
            user_input = input("\n  [Enter] Aufnahme | [q] Beenden: ").strip()
            if user_input.lower() == "q":
                break

            if use_silence:
                print("  Sprechen... (stoppt bei 2s Stille)")
                audio = recorder.record_until_silence()
            else:
                recorder.start()
                input("  AUFNAHME... [Enter] zum Stoppen ")
                audio = recorder.stop()

            duration = len(audio) / SAMPLE_RATE
            print(f"  ({duration:.1f}s aufgenommen)")

            if len(audio) < SAMPLE_RATE * 0.5:
                print("  Zu kurz, übersprungen.")
                continue

            text = transcribe(audio, language=language)
            if text:
                print(f"\n  >> {text}\n")
                records.append({"time": time.strftime("%H:%M:%S"), "text": text})

    except KeyboardInterrupt:
        print("\n")

    return records


def run_push_to_talk_keyboard(recorder, language):
    """Push-to-talk mit Leertaste (Terminal-Fallback ohne GPIO)."""
    records = []
    print("\n  Modus: Push-to-Talk (Tastatur)")
    print("  [Enter] = Aufnahme starten, [Enter] = Aufnahme stoppen")
    print("  [q + Enter] = Beenden\n")

    try:
        while True:
            user_input = input("  >> Bereit. [Enter] fuer Aufnahme: ").strip()
            if user_input.lower() == "q":
                break

            print("  ** AUFNAHME **", flush=True)
            recorder.start()
            input("  ** [Enter] zum Stoppen ** ")
            audio = recorder.stop()

            duration = len(audio) / SAMPLE_RATE
            print(f"  ({duration:.1f}s aufgenommen)")

            if len(audio) < SAMPLE_RATE * 0.5:
                print("  Zu kurz, uebersprungen.")
                continue

            text = transcribe(audio, language=language)
            if text:
                print(f"\n  >> {text}\n")
                records.append({"time": time.strftime("%H:%M:%S"), "text": text})

    except KeyboardInterrupt:
        print("\n")

    return records


def save_protocol(records):
    """Speichert das Protokoll als Textdatei."""
    if not records:
        return

    log_path = PROJECT_DIR / f"san_protokoll_{time.strftime('%Y%m%d_%H%M%S')}.txt"
    with open(log_path, "w") as f:
        f.write("San-Feldeinsatz Protokoll\n")
        f.write(f"Datum: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 50 + "\n\n")
        for i, r in enumerate(records, 1):
            f.write(f"[{i}] {r['time']} - {r['text']}\n\n")

    print(f"\n  Protokoll gespeichert: {log_path}")

    print("\n" + "=" * 60)
    print("  Gesamte Aufzeichnung:")
    print("=" * 60)
    for i, r in enumerate(records, 1):
        print(f"  [{i}] {r['time']} - {r['text']}")


def main():
    parser = argparse.ArgumentParser(
        description="CGI San-Feldeinsatz Sprach-Dokumentation"
    )
    parser.add_argument("-d", "--device", type=int, default=None,
                        help="Audio-Device ID")
    parser.add_argument("-l", "--language", default="de",
                        help="Sprache (default: de)")
    parser.add_argument("--model", type=str, default=None,
                        help="Pfad zum GGML-Modell")
    parser.add_argument("--list-devices", action="store_true",
                        help="Audio-Geraete auflisten")
    parser.add_argument("--no-gpio", action="store_true",
                        help="GPIO deaktivieren (nur Tastatur)")
    parser.add_argument("--push-to-talk", action="store_true",
                        help="Push-to-talk Modus (manuell start/stop)")
    parser.add_argument("--gpio-line", type=str, default=GPIO_BUTTON_RECORD,
                        help=f"GPIO-Line Name (default: {GPIO_BUTTON_RECORD})")
    args = parser.parse_args()

    if args.list_devices:
        list_audio_devices()
        return

    global MODEL_PATH
    if args.model:
        MODEL_PATH = Path(args.model)

    if not WHISPER_CLI.exists():
        print(f"FEHLER: whisper-cli nicht gefunden: {WHISPER_CLI}")
        sys.exit(1)
    if not MODEL_PATH.exists():
        print(f"FEHLER: Modell nicht gefunden: {MODEL_PATH}")
        sys.exit(1)

    list_audio_devices()

    print("=" * 60)
    print("  CGI San-Feldeinsatz - Sprach-Dokumentation")
    print("  Sprache: Deutsch | Modell: medium | CUDA: aktiv")
    print("=" * 60)

    recorder = AudioRecorder(device=args.device)

    # GPIO-Button initialisieren
    button = None
    if not args.no_gpio:
        button = GpioButton(line_name=args.gpio_line)

    # Modus wählen
    if button and button.available:
        records = run_gpio_mode(recorder, button, args.language)
        button.close()
    elif args.push_to_talk:
        records = run_push_to_talk_keyboard(recorder, args.language)
    else:
        records = run_keyboard_mode(recorder, args.language)

    save_protocol(records)


if __name__ == "__main__":
    main()
