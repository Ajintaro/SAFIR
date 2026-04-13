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
_output_device = None


def init_tts() -> bool:
    """Lädt Piper TTS Modell (einmalig, ~2s)."""
    global _voice
    if _voice is not None:
        return True
    try:
        from piper import PiperVoice
        _voice = PiperVoice.load(str(PIPER_MODEL), config_path=str(PIPER_CONFIG))
        # Audio-Output: USB-Headset bevorzugen
        global _output_device
        try:
            devs = sd.query_devices()
            for i, d in enumerate(devs):
                if d["max_output_channels"] > 0 and ("USB" in d["name"] or "Logitech" in d["name"]):
                    _output_device = i
                    print(f"TTS Audio-Output: [{i}] {d['name']}")
                    break
        except Exception:
            pass
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


def _speak_internal(text: str):
    """Synthese + Ausgabe über Lautsprecher."""
    with _lock:
        try:
            chunks = list(_voice.synthesize(text))
            if not chunks:
                return
            audio = np.concatenate([c.audio_int16_array for c in chunks])
            sr = _voice.config.sample_rate
            # int16 -> float32 für sounddevice
            audio_float = audio.astype(np.float32) / 32768.0
            sd.play(audio_float, samplerate=sr, device=_output_device)
            sd.wait()
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
