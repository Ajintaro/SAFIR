#!/usr/bin/env python3
"""
Generiert die drei SAFIR-Status-Sounds als 44.1 kHz Mono WAV.
Einmalig ausführen — die .wav-Dateien werden unter ``sounds/`` abgelegt
und danach von systemd/aplay bzw. vom shutdown-Watcher gespielt.

    boot.wav         — Ubuntu ist hochgefahren (Dreiklang C4-E4-G4)
    safir-ready.wav  — Whisper+Qwen geladen, SAFIR antwortet (A4-E5-A5)
    shutdown.wav     — System fährt runter (Dreiklang G4-E4-C4 absteigend)
"""
import wave
from pathlib import Path

import numpy as np

SAMPLE_RATE = 44100


def tone(freq: float, duration: float, amplitude: float = 0.3, fade: float = 0.01) -> np.ndarray:
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    wave_data = amplitude * np.sin(2 * np.pi * freq * t)
    # kurzer fade-in/out verhindert Klick-Artefakte
    fade_samples = int(SAMPLE_RATE * fade)
    if fade_samples > 0 and len(wave_data) > 2 * fade_samples:
        wave_data[:fade_samples] *= np.linspace(0, 1, fade_samples)
        wave_data[-fade_samples:] *= np.linspace(1, 0, fade_samples)
    return wave_data


def silence(duration: float) -> np.ndarray:
    return np.zeros(int(SAMPLE_RATE * duration))


def write_wav(path: Path, audio: np.ndarray) -> None:
    audio_int16 = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(audio_int16.tobytes())


def main() -> None:
    out = Path(__file__).parent.parent / "sounds"
    out.mkdir(exist_ok=True)

    # Ubuntu Boot: aufsteigender Dreiklang C4-E4-G4
    boot = np.concatenate([
        tone(261.63, 0.15), silence(0.03),
        tone(329.63, 0.15), silence(0.03),
        tone(392.00, 0.35),
    ])
    write_wav(out / "boot.wav", boot)

    # SAFIR bereit: Radio-Signal A4-E5-A5 (hell, aufmerksam)
    safir = np.concatenate([
        tone(440.00, 0.10), silence(0.04),
        tone(659.25, 0.10), silence(0.04),
        tone(880.00, 0.30),
    ])
    write_wav(out / "safir-ready.wav", safir)

    # Shutdown: absteigender Dreiklang G4-E4-C4
    shutdown = np.concatenate([
        tone(392.00, 0.15), silence(0.03),
        tone(329.63, 0.15), silence(0.03),
        tone(261.63, 0.40),
    ])
    write_wav(out / "shutdown.wav", shutdown)

    for name in ("boot.wav", "safir-ready.wav", "shutdown.wav"):
        p = out / name
        print(f"  {p} ({p.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
