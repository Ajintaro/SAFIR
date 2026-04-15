"""
SAFIR — Text-to-Speech Feedback via Piper TTS.
Kurze, militärisch-knappe Ansagen für den Feldeinsatz.
Modell wird einmal geladen und bleibt im Speicher.
"""

import io
import threading
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

PIPER_MODEL = Path(__file__).parent.parent / "models" / "piper" / "de_DE-thorsten-medium.onnx"
PIPER_CONFIG = PIPER_MODEL.with_suffix(".onnx.json")

_voice = None
_lock = threading.Lock()
_enabled = True
# Liste von Output-Devices (PortAudio-Device-IDs). Wenn mehrere Speaker-
# Devices da sind (z.B. USB-Headset + integrierter HDA-Lautsprecher),
# wird TTS auf ALLEN gleichzeitig ausgegeben — der Messebesucher mit
# Headset hoert die Antwort genauso wie die Umstehenden ueber den
# Lautsprecher. _output_device (singular, alt) bleibt fuer Rueckwarts-
# kompatibilitaet als Alias auf _output_devices[0].
_output_devices: list[int] = []
_output_device = None


def _is_speaker_device(name: str) -> bool:
    """Filter fuer 'echte' Speaker-Devices. Schliesst Loopback, HDMI,
    pulse virtuelle Devices, Modem etc. aus."""
    n = name.lower()
    skip_keywords = ("hdmi", "loopback", "modem", "pulse", "default",
                     "sysdefault", "front", "surround", "iec958", "spdif",
                     "samplerate", "speexrate", "upmix", "vdownmix",
                     "dmix", "dsnoop")
    if any(kw in n for kw in skip_keywords):
        return False
    speaker_keywords = ("usb", "headset", "speaker", "jabra", "logitech",
                        "plantronics", "creative", "razer", "audio", "hda",
                        "tegra")
    return any(kw in n for kw in speaker_keywords)


def rescan_devices() -> int:
    """Scannt alle Speaker-Output-Devices neu und befuellt _output_devices.
    Wird beim init_tts und vom Hot-Plug-Watcher (app.py) aufgerufen.
    Gibt die Anzahl der gefundenen Devices zurueck."""
    global _output_devices, _output_device
    _output_devices.clear()
    try:
        devs = sd.query_devices()
        seen_names = set()  # Duplikate (z.B. mehrere ALSA-Aliase) ausschliessen
        for i, d in enumerate(devs):
            if d["max_output_channels"] <= 0:
                continue
            name = d["name"]
            if not _is_speaker_device(name):
                continue
            base = name.split("(")[0].strip()
            if base in seen_names:
                continue
            seen_names.add(base)
            _output_devices.append(i)
            print(f"TTS Audio-Output [{i}] {name}")
    except Exception as e:
        print(f"TTS Device-Scan Fehler: {e}")
    if _output_devices:
        _output_device = _output_devices[0]
    else:
        _output_device = None
    n = len(_output_devices)
    print(f"TTS: {n} Speaker-Device(s) — {'Multi-Output' if n > 1 else 'Single-Output' if n == 1 else 'KEIN Output'}")
    return n


def get_output_device_count() -> int:
    """Aktuelle Anzahl der Speaker-Output-Devices."""
    return len(_output_devices)


def init_tts() -> bool:
    """Laedt Piper TTS Modell (einmalig, ~2s) und scannt alle Output-
    Devices. Mehrere Speaker werden parallel bespielt."""
    global _voice
    if _voice is not None:
        return True
    try:
        from piper import PiperVoice
        _voice = PiperVoice.load(str(PIPER_MODEL), config_path=str(PIPER_CONFIG))
        rescan_devices()
        print(f"Piper TTS geladen ({PIPER_MODEL.name}, {_voice.config.sample_rate}Hz)")
        return True
    except Exception as e:
        print(f"Piper TTS Fehler: {e}")
        return False


def set_enabled(enabled: bool):
    """TTS ein/ausschalten."""
    global _enabled
    _enabled = enabled


def is_enabled() -> bool:
    return _enabled and _voice is not None


def speak(text: str, blocking: bool = False):
    """Spricht Text aus. Non-blocking per Default (eigener Thread)."""
    if not _enabled or _voice is None:
        return
    if blocking:
        _speak_internal(text)
    else:
        t = threading.Thread(target=_speak_internal, args=(text,), daemon=True)
        t.start()


def _pick_output_rate(device, piper_rate: int) -> int:
    """Wählt eine sample rate die das Output-Device wirklich annimmt.

    Wir probieren in dieser Reihenfolge:
    1. Piper native (22050 Hz) — wenn das Device das direkt schluckt, kein
       Resample nötig und bestmögliche Qualität.
    2. 44100 Hz — Standard für C-Media/Ugreen-USB-Dongles.
    3. 48000 Hz — Standard für Jabra, Conference-Speaker, modernes USB-Audio.

    Wir verlassen uns bewusst NICHT mehr auf ``default_samplerate`` aus
    query_devices(). Das Jabra SPEAK 510 meldet dort 16000 Hz (Telefonie-
    Default), intern läuft die Hardware aber mit 48000 Hz — beim Abspielen
    interpretiert der Driver 16000 Sample-Stream als 48000 und das Audio
    klingt 3x zu schnell. check_output_settings() prüft die tatsächliche
    ALSA-Route und filtert solche Fehlmeldungen aus.
    """
    candidates = [piper_rate, 44100, 48000]
    for rate in candidates:
        try:
            sd.check_output_settings(
                device=device, samplerate=rate, channels=1, dtype="float32"
            )
            return rate
        except Exception:
            continue
    return piper_rate  # letzte Rettung


def _resample_for_device(audio_float: np.ndarray, piper_rate: int, target_rate: int) -> np.ndarray:
    """Resample (per linearer Interpolation) wenn target != piper."""
    if target_rate == piper_rate:
        return audio_float
    ratio = target_rate / piper_rate
    new_len = int(len(audio_float) * ratio)
    indices = np.linspace(0, len(audio_float) - 1, new_len)
    return np.interp(indices, np.arange(len(audio_float)), audio_float).astype(np.float32)


def _play_one(device_id: int, audio_float: np.ndarray, piper_rate: int):
    """Spielt das Sample auf einem Device ab — pro Device eigenes Resample,
    weil USB-Headset (48 kHz) und HDA-Lautsprecher (44.1 kHz) verschieden
    sein koennen."""
    try:
        target_rate = _pick_output_rate(device_id, piper_rate)
        sample = _resample_for_device(audio_float, piper_rate, target_rate)
        sd.play(sample, samplerate=target_rate, device=device_id, blocking=True)
    except Exception as e:
        print(f"TTS Ausgabe Fehler [device {device_id}]: {e}")


def _speak_internal(text: str):
    """Synthese + parallel auf alle Speaker-Devices ausgeben.
    Pro Device wird in einem eigenen Thread resampled und gespielt — so
    laufen Headset und Lautsprecher synchron, jeder mit seiner nativen
    Sample-Rate. Wenn nur ein Device da ist, ist der Overhead minimal
    (ein einziger Thread)."""
    with _lock:
        try:
            chunks = list(_voice.synthesize(text))
            if not chunks:
                return
            audio = np.concatenate([c.audio_int16_array for c in chunks])
            piper_rate = _voice.config.sample_rate
            audio_float = audio.astype(np.float32) / 32768.0

            devices = _output_devices or [_output_device] if _output_device is not None else []
            if not devices:
                # Letzte Rettung: PortAudio-Default
                sd.play(audio_float, samplerate=piper_rate, blocking=True)
                return

            # Pro Device einen Thread starten, dann auf alle warten.
            # blocking=True in sd.play() blockiert nur den jeweiligen Thread,
            # nicht den Haupt-Lock — die Threads laufen wirklich parallel.
            threads = []
            for dev_id in devices:
                t = threading.Thread(
                    target=_play_one,
                    args=(dev_id, audio_float, piper_rate),
                    daemon=True,
                )
                t.start()
                threads.append(t)
            for t in threads:
                t.join()
        except Exception as e:
            print(f"TTS Ausgabe Fehler: {e}")


# --- Vordefinierte Ansagen ---

def announce_patient_created():
    speak("Patient angelegt")

def announce_triage(level: str):
    labels = {"T1": "Triage rot", "T2": "Triage gelb", "T3": "Triage grün", "T4": "Triage blau"}
    speak(labels.get(level, f"Triage {level}"))

def announce_recording_start():
    speak("Aufnahme")

def announce_recording_stop():
    speak("Aufnahme beendet")

def announce_transcription_done():
    speak("Transkription fertig")

def announce_patient_ready():
    speak("Patient fertig. Scan vorbereiten.")

def announce_rfid_linked():
    speak("Scan erfolgreich")

def announce_patient_count(count: int):
    speak(f"{count} Patienten angelegt")

def announce_sent():
    speak("Daten gesendet")

def announce_entry_deleted():
    speak("Eintrag gelöscht")

def announce_patient_switch(number: int):
    speak(f"Patient {number} aktiv")

def announce_error():
    speak("Fehler")

def announce_confirmed():
    speak("Verstanden")

def announce_batch_analysis(count: int):
    speak(f"{count} Patienten werden analysiert")

def announce_batch_analysis_done(count: int):
    speak(f"{count} Patienten analysiert")
