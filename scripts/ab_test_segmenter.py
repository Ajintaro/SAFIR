#!/usr/bin/env python3
"""A/B-Test fuer den BOUNDARY-Segmenter: Vergleicht zwei Ollama-Modelle
auf demselben Diktat mit den exakt gleichen Optionen wie SAFIR's
_call_ollama. Schreibt keinen State, beruehrt den safir.service nicht.

Usage (auf dem Jetson):
    python3 scripts/ab_test_segmenter.py

Erwartung fuer Schmidt/Meyer-Diktat:
    - 1.5b (Baseline): starts=[1,3,5,6,7]   -> 5 Boundaries (falsch)
    - 3b   (Test):     starts=[3]           -> 1 Boundary  (richtig)
"""

import json
import re
import time
import urllib.error
import urllib.request

OLLAMA_URL = "http://127.0.0.1:11434"

# 1:1 aus app.py uebernommen (Stand: 15.04.2026)
BOUNDARY_PROMPT = """Zerlege Sanitäts-Transkripte in Patienten. Gib die Satzindizes zurück an denen ein NEUER Patient startet.

WICHTIGSTE REGEL: Ein Satz der "Der nächste Patient ist ..." oder "Zweiter Patient ..." oder "Weiter mit ..." enthält, IST SELBST der Start des neuen Patienten. Er gehört NICHT zum vorherigen.

WEITERE REGELN:
- Patient-Start-Signale: "erster/zweiter/dritter Patient", "nächster Verwundeter/Patient", "weiter mit dem nächsten", "jetzt zum anderen", "dann noch ein", "jetzt eine Frau", "es folgt", "als nächstes ist", "eine weitere Verletzte".
- KEIN Start-Signal: Sätze die nur Verletzungen, Vitals oder Behandlung eines bereits genannten Patienten beschreiben ("Er hat...", "Sie hat...", "Puls...", "Atmung...", "Maßnahmen...").
- KEIN Start-Signal: Einleitungssätze ohne Patient-Info ("Hier spricht...", "Ich bin am Ort", "Ich habe drei Verwundete") — sie gehören zum ersten echten Patient-Satz.
- "und", "außerdem", "zusätzlich", "auch" = SELBER Patient.

Antwort: JSON {"starts":[liste]} — sonst NICHTS.

BEISPIEL 1 — 3 Patienten mit Arzt-Einleitung:
[0] Ich bin am Unfallort und habe drei Verwundete
[1] Der erste ist Soldat Weber 25 Schussverletzung Bauch
[2] Weiter mit dem nächsten Patienten
[3] Zweiter eine Soldatin Becker 30 Platzwunde Kopf
[4] Dann noch ein dritter Patient Fischer 22 Splitter Oberschenkel
{"starts":[1,3,4]}

BEISPIEL 2 — "Der nächste Patient ist X" startet neuen Patient (GENAU DIESER Satz, nicht der folgende):
[0] Hier spricht Oberfeldarzt Mueller
[1] Ich untersuche die Hauptgefreite Erika Schmidt
[2] Sie hat Oberschenkelfraktur und Blutung
[3] SpO2 91 Puls 110
[4] Der nächste Patient ist der Stabsunteroffizier Marius Müller
[5] Er hat eine leichte Kopfverletzung mit Aspirin behandelt
{"starts":[1,4]}

BEISPIEL 3 — 1 Patient mit mehreren Sätzen (KEIN Split):
[0] Patient männlich 30 Schusswunde Bein
[1] Auch Schnittwunde Hand beides blutet
[2] Puls 130 Atmung normal
[3] Bewusstsein klar
{"starts":[0]}

BEISPIEL 4 — 2 Patienten, zweiter mit "Wir haben noch":
[0] Hier spricht Oberfeldarzt Meier
[1] Die Hauptgefreite Schmidt hat eine Beinverletzung Puls 110
[2] Wir haben noch eine weitere Verletzte die Oberst Meier-Lai
[3] Sie hat nur leichten Husten
{"starts":[1,2]}

Sätze:
"""


# Test-Diktat 1:1 vom User
TRANSCRIPT = (
    "Hier spricht Oberfeldarzt Hugen-Dubel. "
    "Wir untersuchen gerade die Frau Hauptgefreite Erika Schmidt. "
    "Sie hat eine leichte Kopfverletzung und einen Sauerstoffgehalt von 91 Prozent. "
    "Als nächstes haben wir einen Verwundeten mit dem Namen Erik Meyer. "
    "Er hat eine Schussverletzung und blutet sehr stark. "
    "Wir müssten dort Blutkonserten der Blutgruppe B positiv bereithalten. "
    "Er ist für den Rücktransport aber stabil genug. "
    "Aufnahme"
)


def split_sentences(text: str) -> list[str]:
    """1:1 aus app.py uebernommen."""
    raw = re.split(r"(?<=[.!?])\s+", text.strip())
    merged: list[str] = []
    for seg in raw:
        seg = seg.strip()
        if not seg:
            continue
        if merged and len(merged[-1]) < 30:
            merged[-1] = merged[-1] + " " + seg
        else:
            merged.append(seg)
    return merged


def _post(payload: dict, timeout: int = 180) -> tuple[int, str]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")[:500]
    except urllib.error.URLError as e:
        return 0, f"URLError: {e}"


def unload_model(model: str) -> None:
    """Entlaedt ein Modell aus dem VRAM (keep_alive=0)."""
    status, _ = _post({"model": model, "prompt": "", "keep_alive": 0}, timeout=30)
    print(f"  [unload] {model}: HTTP {status}")


def reload_keepalive(model: str) -> None:
    """Laedt ein Modell wieder permanent (keep_alive=-1) wie SAFIR es will."""
    status, _ = _post({"model": model, "prompt": "", "keep_alive": -1}, timeout=120)
    print(f"  [reload] {model} keep_alive=-1: HTTP {status}")


def list_loaded_models() -> str:
    """Liest /api/ps der Ollama-API."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/ps", timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = data.get("models", [])
            if not models:
                return "(keine)"
            return ", ".join(f"{m.get('name')} ({m.get('size_vram', 0) // (1024*1024)}MB VRAM)" for m in models)
    except Exception as e:
        return f"(Fehler: {e})"


def call_ollama(model: str, prompt: str, keep_alive: int = 0, num_ctx: int | None = None) -> tuple[dict, float, str]:
    """Ruft Ollama mit den exakt gleichen Optionen wie SAFIR auf.
    keep_alive: 0 = nach Idle wieder entladen, -1 = permanent halten.
    num_ctx: optional Context-Fenster (default Ollama 4096). Kleinere Werte
        sparen massiv VRAM beim KV-Cache.
    Returns: (parsed_json, elapsed_seconds, raw_response)."""
    options: dict = {
        "num_gpu": 20,
        "temperature": 0.0,
        "num_predict": 400,
        "top_k": 1,
    }
    if num_ctx is not None:
        options["num_ctx"] = num_ctx
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": options,
        "keep_alive": keep_alive,
    }
    t0 = time.monotonic()
    status, raw_resp = _post(payload, timeout=180)
    elapsed = time.monotonic() - t0
    if status != 200:
        return {}, elapsed, f"HTTP {status}: {raw_resp[:200]}"
    raw = json.loads(raw_resp).get("response", "{}")
    try:
        return json.loads(raw), elapsed, raw
    except json.JSONDecodeError:
        return {}, elapsed, raw


def main() -> None:
    sentences = split_sentences(TRANSCRIPT)
    numbered = "\n".join(f"[{i}] {s}" for i, s in enumerate(sentences))
    prompt = BOUNDARY_PROMPT + numbered + "\n\nAntwort:"

    print("=" * 72)
    print(f"INPUT: {len(sentences)} Sätze, {len(TRANSCRIPT)} chars")
    print("=" * 72)
    for i, s in enumerate(sentences):
        print(f"  [{i}] ({len(s):>3}c) {s}")
    print()
    print(f"VRAM vorher: {list_loaded_models()}")
    print()

    results: list[tuple[str, dict, float, str]] = []

    # --- Test 1: 1.5b (sollte schon im VRAM sein, wir nutzen es 1:1) ---
    print("=== TEST 1: qwen2.5:1.5b (Baseline) ===")
    parsed, elapsed, raw = call_ollama("qwen2.5:1.5b", prompt, keep_alive=-1)
    results.append(("qwen2.5:1.5b", parsed, elapsed, raw))
    starts = parsed.get("starts") if isinstance(parsed, dict) else None
    print(f"  Latenz: {elapsed:.2f} s")
    print(f"  Roh:    {raw[:300]}")
    print(f"  starts: {starts}")
    print()

    # --- 1.5b entladen, damit 3b geladen werden kann ---
    print("=== VRAM-Swap: 1.5b raus, 3b rein ===")
    unload_model("qwen2.5:1.5b")
    time.sleep(2)
    print(f"  Nach unload: {list_loaded_models()}")
    print()

    # --- Test 2: 3b mit reduziertem Context (2048 statt 4096), spart KV-Cache ---
    print("=== TEST 2: qwen2.5:3b (num_ctx=2048) ===")
    parsed, elapsed, raw = call_ollama("qwen2.5:3b", prompt, keep_alive=0, num_ctx=2048)
    results.append(("qwen2.5:3b", parsed, elapsed, raw))
    starts = parsed.get("starts") if isinstance(parsed, dict) else None
    print(f"  Latenz: {elapsed:.2f} s")
    print(f"  Roh:    {raw[:300]}")
    print(f"  starts: {starts}")
    print()

    # --- 3b entladen, 1.5b wieder permanent laden (Production-Zustand) ---
    print("=== Production wiederherstellen ===")
    unload_model("qwen2.5:3b")
    time.sleep(2)
    reload_keepalive("qwen2.5:1.5b")
    time.sleep(1)
    print(f"  VRAM nachher: {list_loaded_models()}")
    print()

    # --- Vergleich ---
    print("=" * 72)
    print("VERGLEICH")
    print("=" * 72)
    print(f"{'Modell':<14} {'Latenz':<10} {'starts':<30} {'# Patienten':<12}")
    print("-" * 72)
    for model, parsed, elapsed, _raw in results:
        starts = parsed.get("starts") if isinstance(parsed, dict) else None
        n_patients = len(starts) if isinstance(starts, list) else "?"
        print(f"{model:<14} {elapsed:>5.2f} s    {str(starts):<30} {n_patients}")
    print()
    print("Erwartung (richtig segmentiert): starts=[3]  -> 1 Boundary -> 2 Patienten")
    print("(Satz 0-2 = Schmidt, Satz 3-7 = Meyer mit Blutkonserve+Rücktransport)")


if __name__ == "__main__":
    main()
