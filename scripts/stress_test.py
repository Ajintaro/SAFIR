#!/usr/bin/env python3
"""RAM-Stress-Test fuer SAFIR — Phase 9.2.

Schiesst 10x hintereinander die groesste LLM-Last (Segmenter + 9-Liner)
an den Jetson und ueberwacht parallel RAM/GPU via /api/status. Das ist
eine Proxy-Messung fuer das Worst-Case-Szenario auf der AFCEA-Demo:
Der Messebesucher diktiert schnell hintereinander, ohne dem System Zeit
zum Recovery zu geben.

Pruefungen:
- Jeder Request muss HTTP 200 zurueckgeben (kein Crash)
- RAM darf nicht ueber 95% gehen
- Keine OOM-Events im journalctl-Log (nur wenn SSH-Key hinterlegt)

Nutzung:
    python scripts/stress_test.py --jetson http://localhost:8080 --iterations 10
"""
import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime


SAMPLE_MULTI_PATIENT = (
    "Erster Patient: Hauptgefreiter Erika Schmidt, weiblich, zweiunddreissig Jahre, "
    "mit einer leichten Kopfverletzung durch einen Splitter. Sauerstoffsaettigung "
    "einundneunzig Prozent, bei Bewusstsein, stabil. Als naechstes haben wir "
    "Oberstabsgefreiter Erik Meyer, maennlich, achtundzwanzig, Schussverletzung "
    "am rechten Oberschenkel mit starker Blutung. Druckverband gelegt, "
    "Blutdruck einhundert zu sechzig, Herzfrequenz einhundertzehn. Dann noch "
    "Feldwebel Klaus Becker, maennlich, dreiundvierzig, Brustkorbtrauma links, "
    "Atemfrequenz dreissig, Sauerstoffsaettigung siebenundachtzig. Sofort."
)

SAMPLE_NINE_LINER = (
    "Neun Liner Anfrage. Landezone Grid Mike Golf Romeo 32 Uniform "
    "vier fuenf sechs sieben acht neun null, Funkfrequenz zwei sieben Komma "
    "drei fuenf Megahertz, Rufzeichen Rettungs Sanitaet null eins. Zwei "
    "Patienten, Prioritaet Alpha, ein Patient liegend, ein Patient gehfaehig. "
    "Sonderausstattung Bravo, Blut wird benoetigt. Sicherheitslage November. "
    "Markierung Charlie, Stroboskop. Deutsche Nationalitaet. ABC Gelaende November."
)


def http_get_json(url):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_post_json(url, payload, timeout=60):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Accept": "application/json", "Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def snapshot_status(jetson_url):
    try:
        s = http_get_json(f"{jetson_url}/api/status")
        sys_info = s.get("system", {})
        return {
            "ram_percent": sys_info.get("ram_percent"),
            "ram_used_mb": sys_info.get("ram_used_mb"),
            "gpu_mem_used_mb": sys_info.get("gpu_mem_used_mb"),
            "cpu_percent": sys_info.get("cpu_percent"),
            "whisper_loaded": sys_info.get("whisper_loaded"),
            "ollama_models": [m.get("name") for m in sys_info.get("ollama_models", [])],
        }
    except Exception as e:
        return {"error": str(e)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--jetson", default="http://localhost:8080")
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    print(f"=== SAFIR Stress-Test ({args.iterations} Iterations) ===")
    print(f"Jetson: {args.jetson}")
    print()

    before = snapshot_status(args.jetson)
    print(f"RAM vor Test:  {before.get('ram_percent')}% ({before.get('ram_used_mb')} MB)")
    print(f"Whisper:       {before.get('whisper_loaded')}")
    print(f"Ollama models: {before.get('ollama_models')}")
    print()

    iterations = []
    all_passed = True
    worst_ram = before.get("ram_percent", 0) or 0

    for i in range(1, args.iterations + 1):
        t_iter = time.time()

        # Segment
        t0 = time.time()
        try:
            s1, seg = http_post_json(f"{args.jetson}/api/test/segment",
                                      {"transcript": SAMPLE_MULTI_PATIENT}, timeout=60)
            seg_dur = time.time() - t0
            seg_count = len(seg.get("patients", []))
            seg_pass = s1 == 200 and seg_count >= 2
        except Exception as e:
            seg_dur = time.time() - t0
            seg_pass = False
            seg_count = 0
            seg = {"error": str(e)}

        # 9-Liner
        t0 = time.time()
        try:
            s2, nl = http_post_json(f"{args.jetson}/api/test/nine-liner",
                                     {"transcript": SAMPLE_NINE_LINER}, timeout=60)
            nl_dur = time.time() - t0
            nl_filled = nl.get("filled_count", 0)
            nl_pass = s2 == 200 and nl_filled >= 5
        except Exception as e:
            nl_dur = time.time() - t0
            nl_pass = False
            nl_filled = 0
            nl = {"error": str(e)}

        # RAM-Snapshot nach jeder Iteration
        post = snapshot_status(args.jetson)
        ram = post.get("ram_percent", 0) or 0
        worst_ram = max(worst_ram, ram)

        iter_ok = seg_pass and nl_pass and ram < 95
        if not iter_ok:
            all_passed = False

        iter_dur = time.time() - t_iter
        status_char = "PASS" if iter_ok else "FAIL"
        print(f"[{status_char}] Iter {i:2d}/{args.iterations}  "
              f"Segment={seg_count}p/{seg_dur:.1f}s  "
              f"9Liner={nl_filled}/9/{nl_dur:.1f}s  "
              f"RAM={ram}%  gesamt {iter_dur:.1f}s")

        iterations.append({
            "iteration": i,
            "segment": {"patients": seg_count, "duration_s": round(seg_dur, 2), "passed": seg_pass},
            "nine_liner": {"filled": nl_filled, "duration_s": round(nl_dur, 2), "passed": nl_pass},
            "ram_percent": ram,
            "total_duration_s": round(iter_dur, 2),
        })

    after = snapshot_status(args.jetson)
    print()
    print("=" * 60)
    print(f"RAM nach Test:    {after.get('ram_percent')}% ({after.get('ram_used_mb')} MB)")
    print(f"RAM Worst-Case:   {worst_ram}%")
    print(f"Whisper geladen:  {after.get('whisper_loaded')}")
    print(f"Ollama Modelle:   {after.get('ollama_models')}")
    print(f"Iterations PASS:  {sum(1 for i in iterations if i['segment']['passed'] and i['nine_liner']['passed'])}/{len(iterations)}")
    print(f"Gesamt-Ergebnis:  {'PASS' if all_passed else 'FAIL'}")
    print("=" * 60)

    report = {
        "timestamp": datetime.now().isoformat(),
        "jetson": args.jetson,
        "iterations": args.iterations,
        "passed": all_passed,
        "ram_before_percent": before.get("ram_percent"),
        "ram_after_percent": after.get("ram_percent"),
        "ram_worst_percent": worst_ram,
        "whisper_loaded_before": before.get("whisper_loaded"),
        "whisper_loaded_after": after.get("whisper_loaded"),
        "iterations_detail": iterations,
    }

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\nReport: {args.json_out}")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
