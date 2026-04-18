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

_PIPER_DIR = Path(__file__).parent.parent / "models" / "piper"

# Verfuegbare Stimmen. Gender "m"/"w" fuer UI-Dropdown. Thorsten
# ist der urspruengliche Default, Kerstin die weibliche Alternative.
AVAILABLE_VOICES: dict[str, dict] = {
    "de_DE-thorsten-high":   {"gender": "m", "label": "Thorsten (maennlich, high-quality)"},
    "de_DE-thorsten-medium": {"gender": "m", "label": "Thorsten (maennlich, medium)"},
    "de_DE-thorsten-low":    {"gender": "m", "label": "Thorsten (maennlich, schnell)"},
    "de_DE-kerstin-low":     {"gender": "w", "label": "Kerstin (weiblich, schnell)"},
}
DEFAULT_VOICE = "de_DE-thorsten-high"

# Wird zur Laufzeit auf den gewaehlten Voice-Path gesetzt.
PIPER_MODEL = _PIPER_DIR / f"{DEFAULT_VOICE}.onnx"
PIPER_CONFIG = PIPER_MODEL.with_suffix(".onnx.json")

_current_voice_name = DEFAULT_VOICE
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


def _rescan_once() -> int:
    """Ein einzelner rescan-Versuch — siehe rescan_devices fuer die
    Retry-Wrapper-Variante."""
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
    return len(_output_devices)


def rescan_devices(max_retries: int = 5, retry_delay: float = 1.0) -> int:
    """Scannt alle Speaker-Output-Devices neu und befuellt _output_devices.
    Mit Retry-Loop: wenn beim ersten Versuch 0 Devices gefunden werden
    (typischer Boot-Race — Service startet bevor PortAudio USB-Enumeration
    abgeschlossen hat), werden max_retries weitere Versuche mit
    retry_delay Sekunden Abstand durchgefuehrt. Zwischen den Versuchen
    wird PortAudio komplett re-initialisiert (sd._terminate + reimport),
    da ein blosses query_devices() sonst den alten leeren Cache liefert."""
    import time as _t
    import importlib as _il
    global sd  # noqa: F824  — global alias darf ausgetauscht werden

    n = _rescan_once()
    if n > 0 or max_retries <= 0:
        print(f"TTS: {n} Speaker-Device(s) — "
              f"{'Multi-Output' if n > 1 else 'Single-Output' if n == 1 else 'KEIN Output'}")
        return n

    # Retry-Schleife: PortAudio hard-reinit und nochmal probieren
    for attempt in range(1, max_retries + 1):
        print(f"TTS: 0 Devices gefunden, retry {attempt}/{max_retries} "
              f"nach {retry_delay:.1f}s (PortAudio-Reinit) ...")
        _t.sleep(retry_delay)
        try:
            sd._terminate()
        except Exception:
            pass
        try:
            import sounddevice as _sd_module
            _il.reload(_sd_module)
            globals()["sd"] = _sd_module
        except Exception as e:
            print(f"TTS sounddevice-reload Fehler: {e}")
        _t.sleep(0.3)
        n = _rescan_once()
        if n > 0:
            break
    print(f"TTS: {n} Speaker-Device(s) — "
          f"{'Multi-Output' if n > 1 else 'Single-Output' if n == 1 else 'KEIN Output'}")
    return n


def get_output_device_count() -> int:
    """Aktuelle Anzahl der Speaker-Output-Devices."""
    return len(_output_devices)


def init_tts(voice_name: str | None = None) -> bool:
    """Laedt Piper TTS Modell (einmalig, ~2s) und scannt alle Output-
    Devices. Mehrere Speaker werden parallel bespielt.

    voice_name kann aus config.tts.voice kommen (AVAILABLE_VOICES keys),
    sonst wird DEFAULT_VOICE genutzt.
    """
    global _voice, _current_voice_name, PIPER_MODEL, PIPER_CONFIG
    name = voice_name if voice_name in AVAILABLE_VOICES else DEFAULT_VOICE
    model_path = _PIPER_DIR / f"{name}.onnx"
    config_path = model_path.with_suffix(".onnx.json")
    if not model_path.exists():
        print(f"TTS-Stimme '{name}' nicht gefunden, Fallback auf {DEFAULT_VOICE}")
        name = DEFAULT_VOICE
        model_path = _PIPER_DIR / f"{name}.onnx"
        config_path = model_path.with_suffix(".onnx.json")
    if _voice is not None and _current_voice_name == name:
        return True
    try:
        from piper import PiperVoice
        _voice = PiperVoice.load(str(model_path), config_path=str(config_path))
        _current_voice_name = name
        PIPER_MODEL = model_path
        PIPER_CONFIG = config_path
        rescan_devices()
        print(f"Piper TTS geladen ({name}, {_voice.config.sample_rate}Hz)")
        return True
    except Exception as e:
        print(f"Piper TTS Fehler: {e}")
        return False


def switch_voice(voice_name: str) -> bool:
    """Wechselt zur Laufzeit die Piper-Stimme. Gibt True zurueck wenn
    erfolgreich geladen. Wird von /api/tts/voice aufgerufen wenn der
    User im Settings-UI die Stimme aendert."""
    global _voice, _current_voice_name
    if voice_name == _current_voice_name:
        return True
    # Voice-Instanz zuruecksetzen damit init_tts wirklich neu laedt
    with _lock:
        _voice = None
    return init_tts(voice_name)


def get_current_voice() -> str:
    return _current_voice_name


def list_available_voices() -> list[dict]:
    """Gibt die AVAILABLE_VOICES-Liste zurueck, aber nur die tatsaechlich
    auf diesem Geraet vorhandenen .onnx-Dateien. So kann das UI genau
    die Stimmen anzeigen, die auch wirklich wechselbar sind."""
    out = []
    for name, info in AVAILABLE_VOICES.items():
        if (_PIPER_DIR / f"{name}.onnx").exists():
            out.append({
                "name": name,
                "gender": info["gender"],
                "label": info["label"],
                "active": name == _current_voice_name,
            })
    return out


def set_enabled(enabled: bool):
    """TTS ein/ausschalten."""
    global _enabled
    _enabled = enabled


def is_enabled() -> bool:
    return _enabled and _voice is not None


import queue as _queue
_tts_queue: _queue.Queue = _queue.Queue()
_tts_worker_thread: threading.Thread | None = None
_tts_worker_lock = threading.Lock()


def _tts_worker():
    """Einziger Worker-Thread der TTS-Messages sequentiell abarbeitet.
    Verhindert double-free im Piper-/ALSA-Code-Pfad wenn mehrere
    tts.speak()-Aufrufe sich zeitlich ueberlappen."""
    print("[TTS-WORKER] started", flush=True)
    while True:
        try:
            text = _tts_queue.get(timeout=30)
        except Exception:
            # Timeout oder andere Queue-Fehler — weiter warten, Worker nicht sterben
            continue
        if text is None:
            print("[TTS-WORKER] received stop signal", flush=True)
            break
        try:
            preview = (text[:60] + "...") if len(text) > 60 else text
            print(f"[TTS-WORKER] speaking: {preview!r}", flush=True)
            _speak_internal(text)
        except Exception as e:
            print(f"[TTS-WORKER] Fehler: {e}", flush=True)
        finally:
            try:
                _tts_queue.task_done()
            except Exception:
                pass


def _ensure_worker():
    global _tts_worker_thread
    with _tts_worker_lock:
        if _tts_worker_thread is None or not _tts_worker_thread.is_alive():
            if _tts_worker_thread is not None:
                print(f"[TTS-WORKER] thread tot, starte neu (queue={_tts_queue.qsize()})", flush=True)
            _tts_worker_thread = threading.Thread(
                target=_tts_worker, daemon=True, name="tts-worker")
            _tts_worker_thread.start()


def speak(text: str, blocking: bool = False):
    """Spricht Text aus. Non-blocking per Default (queue-basiert).

    Einzelner Worker-Thread serialisiert alle Ausgaben — kein
    paralleler Piper-Zugriff mehr moeglich. Bei blocking=True wird
    _speak_internal direkt aufgerufen (z.B. fuer kritische Fehler-
    meldungen die synchron raus muessen).
    """
    if not _enabled or _voice is None:
        print(f"[TTS] dropped (enabled={_enabled}, voice-loaded={_voice is not None}): {text[:60]!r}", flush=True)
        return
    if blocking:
        _speak_internal(text)
    else:
        _ensure_worker()
        qsize_before = _tts_queue.qsize()
        _tts_queue.put(text)
        if qsize_before > 2:
            print(f"[TTS] queue-backlog {qsize_before}, enqueue: {text[:40]!r}", flush=True)


def _pick_output_rate(device, piper_rate: int) -> int:
    """Wählt eine sample rate die das Output-Device wirklich annimmt.

    WICHTIG: Piper-Stimmen im "low"-Quality-Mode (z.B. Kerstin-low,
    Thorsten-low) haben native 16000 Hz. Das meldet das Jabra SPEAK 510
    als "akzeptiert" (Telefonie-Modus), die Hardware laeuft intern aber
    bei 48000 Hz — der Driver interpretiert den 16000-Stream als 48000
    und das Audio klingt 3x zu schnell (Mickey-Mouse-Effekt).

    Deshalb: fuer piper_rate < 22050 UEBERSPRINGEN wir die native Rate
    komplett und gehen direkt auf 44100 oder 48000. Das zwingt uns zum
    Resample via _resample_for_device, aber das Ergebnis klingt korrekt.
    Fuer 22050+ (medium/high Modelle) darf die native Rate weiterhin
    probiert werden — da ist sie normalerweise zuverlaessig.
    """
    # Ab 22050 Hz gilt die native Piper-Rate als sicher probierbar;
    # darunter (low-Modelle) immer auf zwei Mainstream-Rates gehen.
    if piper_rate >= 22050:
        candidates = [piper_rate, 44100, 48000]
    else:
        candidates = [48000, 44100]
    for rate in candidates:
        try:
            sd.check_output_settings(
                device=device, samplerate=rate, channels=1, dtype="float32"
            )
            return rate
        except Exception:
            continue
    return 48000  # letzte Rettung — fast jedes Device akzeptiert 48kHz


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
