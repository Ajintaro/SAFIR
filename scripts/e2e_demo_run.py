#!/usr/bin/env python3
"""E2E Demo-Run fuer SAFIR — Phase 9.1.

Faehrt die komplette Daten-Pipeline gegen einen laufenden Jetson + Surface
und misst Latenzen an jedem Schritt. Ausgabe: JSON-Report mit Pass/Fail
pro Stufe und gesammelten Timing-Daten.

Nutzbar von Surface oder Jetson aus. SSH-Verbindung wird NICHT gebraucht
— alles ueber HTTP + Tailscale.

Beispiel:
    python scripts/e2e_demo_run.py --jetson http://jetson-orin:8080 --surface http://ai-station:8080

Bei Aufruf ohne Args: nutzt Defaults aus config.json / sys.argv.
"""
import argparse
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime


# --- Test-Daten ---

SAMPLE_MULTI_PATIENT_TRANSCRIPT = (
    "Erster Patient: Hauptgefreiter Erika Schmidt, weiblich, zweiunddreissig Jahre, "
    "mit einer leichten Kopfverletzung durch einen Splitter. Sauerstoffsaettigung "
    "einundneunzig Prozent, bei Bewusstsein, stabil. Als naechstes haben wir "
    "Oberstabsgefreiter Erik Meyer, maennlich, achtundzwanzig, Schussverletzung "
    "am rechten Oberschenkel mit starker Blutung. Druckverband gelegt, "
    "Blutdruck einhundert zu sechzig, Herzfrequenz einhundertzehn. Dringend."
)

SAMPLE_NINE_LINER_TRANSCRIPT = (
    "Neun Liner Anfrage. Landezone Grid Mike Golf Romeo 32 Uniform "
    "vier fuenf sechs sieben acht neun null, Funkfrequenz Echo bei "
    "zwei sieben Komma drei fuenf Megahertz, Rufzeichen Rettungs Sanitaet null eins. "
    "Zwei Patienten, Prioritaet Alpha, ein Patient liegend, ein Patient gehfaehig. "
    "Sonderausstattung Bravo, Blut wird benoetigt. Sicherheitslage November, keine "
    "feindliche Aktivitaet. Markierung Charlie, Stroboskop. Patienten deutsche "
    "Nationalitaet, militaerisch. ABC Gelaende November, keine Kontamination."
)


# --- Helpers ---

class TestResult:
    def __init__(self, name, passed, duration_s, detail=""):
        self.name = name
        self.passed = passed
        self.duration_s = duration_s
        self.detail = detail

    def __str__(self):
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {self.name} ({self.duration_s:.2f}s) — {self.detail}"


def http_get(url, timeout=10):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.headers, resp.read()


def http_post(url, payload=None, timeout=60):
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.headers, resp.read()


def json_body(body_bytes):
    try:
        return json.loads(body_bytes.decode("utf-8"))
    except Exception:
        return None


# --- Tests ---

def test_jetson_alive(jetson_url):
    t0 = time.time()
    try:
        status, _, body = http_get(f"{jetson_url}/api/status", timeout=5)
        d = time.time() - t0
        if status != 200:
            return TestResult("jetson_alive", False, d, f"HTTP {status}")
        data = json_body(body)
        if not data:
            return TestResult("jetson_alive", False, d, "invalid JSON")
        ready = data.get("model_loaded", False)
        ram = data.get("system", {}).get("ram_percent", 0)
        return TestResult(
            "jetson_alive", ready, d,
            f"model_loaded={ready} ram={ram}%"
        )
    except Exception as e:
        return TestResult("jetson_alive", False, time.time() - t0, str(e))


def test_surface_alive(surface_url):
    t0 = time.time()
    try:
        status, _, body = http_get(f"{surface_url}/api/status", timeout=5)
        d = time.time() - t0
        if status != 200:
            return TestResult("surface_alive", False, d, f"HTTP {status}")
        data = json_body(body)
        if not data:
            return TestResult("surface_alive", False, d, "invalid JSON")
        return TestResult(
            "surface_alive", True, d,
            f"role={data.get('role')} patients={data.get('patients_total')}"
        )
    except Exception as e:
        return TestResult("surface_alive", False, time.time() - t0, str(e))


def test_jetson_segment(jetson_url):
    t0 = time.time()
    try:
        status, _, body = http_post(
            f"{jetson_url}/api/test/segment",
            {"transcript": SAMPLE_MULTI_PATIENT_TRANSCRIPT},
            timeout=30
        )
        d = time.time() - t0
        if status != 200:
            return TestResult("segment_multi_patient", False, d, f"HTTP {status}")
        data = json_body(body)
        if not data:
            return TestResult("segment_multi_patient", False, d, "invalid JSON")
        patients = data.get("patients", [])
        count = len(patients)
        passed = count == 2
        return TestResult(
            "segment_multi_patient", passed, d,
            f"{count} Patient(en) erkannt, erwartet 2"
        )
    except Exception as e:
        return TestResult("segment_multi_patient", False, time.time() - t0, str(e))


def test_jetson_nine_liner(jetson_url):
    t0 = time.time()
    try:
        status, _, body = http_post(
            f"{jetson_url}/api/test/nine-liner",
            {"transcript": SAMPLE_NINE_LINER_TRANSCRIPT},
            timeout=30
        )
        d = time.time() - t0
        if status != 200:
            return TestResult("nine_liner_extract", False, d, f"HTTP {status}")
        data = json_body(body)
        if not data:
            return TestResult("nine_liner_extract", False, d, "invalid JSON")
        nl = data.get("nine_liner", {})
        filled = sum(1 for k in ["line1", "line2", "line3", "line4", "line5",
                                  "line6", "line7", "line8", "line9"]
                     if nl.get(k, "").strip())
        passed = filled >= 6  # toleriert wenn LLM 1-2 Felder weglaesst
        return TestResult(
            "nine_liner_extract", passed, d,
            f"{filled}/9 Felder gefuellt"
        )
    except Exception as e:
        return TestResult("nine_liner_extract", False, time.time() - t0, str(e))


def test_jetson_testdata_gen(jetson_url):
    t0 = time.time()
    try:
        status, _, body = http_post(f"{jetson_url}/api/data/test-generate", timeout=15)
        d = time.time() - t0
        if status != 200:
            return TestResult("testdata_generate", False, d, f"HTTP {status}")
        data = json_body(body)
        count = (data.get("created", 0) if data else 0) or (data.get("count", 0) if data else 0)
        passed = count >= 4
        return TestResult(
            "testdata_generate", passed, d,
            f"{count} Test-Patienten erzeugt"
        )
    except Exception as e:
        return TestResult("testdata_generate", False, time.time() - t0, str(e))


def test_jetson_patients_list(jetson_url):
    t0 = time.time()
    try:
        status, _, body = http_get(f"{jetson_url}/api/patients", timeout=5)
        d = time.time() - t0
        if status != 200:
            return TestResult("patients_list", False, d, f"HTTP {status}")
        data = json_body(body)
        count = len(data.get("patients", [])) if data else 0
        return TestResult(
            "patients_list", count > 0, d,
            f"{count} Patienten im State"
        )
    except Exception as e:
        return TestResult("patients_list", False, time.time() - t0, str(e))


def test_export(jetson_url, fmt, content_type_contains, min_size=500):
    t0 = time.time()
    method = "POST" if fmt in ("docx", "pdf") else "GET"
    url = f"{jetson_url}/api/export/{fmt}/all"
    try:
        if method == "POST":
            status, headers, body = http_post(url, timeout=60)
        else:
            status, headers, body = http_get(url, timeout=30)
        d = time.time() - t0
        if status != 200:
            return TestResult(f"export_{fmt}", False, d, f"HTTP {status}")
        ct = headers.get("content-type", "")
        size = len(body)
        passed = (content_type_contains in ct.lower()) and (size >= min_size)
        return TestResult(
            f"export_{fmt}", passed, d,
            f"{size} bytes, {ct}"
        )
    except Exception as e:
        return TestResult(f"export_{fmt}", False, time.time() - t0, str(e))


def test_jetson_reset(jetson_url):
    t0 = time.time()
    try:
        status, _, body = http_post(f"{jetson_url}/api/data/reset", timeout=5)
        d = time.time() - t0
        return TestResult("data_reset", status == 200, d, f"HTTP {status}")
    except Exception as e:
        return TestResult("data_reset", False, time.time() - t0, str(e))


def test_surface_patient_count(surface_url, expected_min):
    """Surface sollte nach einem Sync die Patienten gesynced haben."""
    t0 = time.time()
    try:
        status, _, body = http_get(f"{surface_url}/api/patients", timeout=5)
        d = time.time() - t0
        data = json_body(body)
        count = len(data.get("patients", [])) if data else 0
        return TestResult(
            "surface_patient_count", count >= expected_min, d,
            f"{count} Patienten auf Surface"
        )
    except Exception as e:
        return TestResult("surface_patient_count", False, time.time() - t0, str(e))


# --- Main ---

def main():
    parser = argparse.ArgumentParser(description="SAFIR E2E Demo-Run")
    parser.add_argument("--jetson", default="http://localhost:8080",
                        help="Jetson URL (default: http://localhost:8080)")
    parser.add_argument("--surface", default="http://100.101.80.64:8080",
                        help="Surface URL (default: http://100.101.80.64:8080)")
    parser.add_argument("--json-out", help="Schreibe Report als JSON in die Datei")
    parser.add_argument("--skip-surface", action="store_true",
                        help="Surface-Tests ueberspringen (z.B. wenn offline)")
    parser.add_argument("--skip-reset", action="store_true",
                        help="Nicht am Ende Daten loeschen (fuer manuelle Inspektion)")
    args = parser.parse_args()

    print(f"=== SAFIR E2E Demo-Run ===")
    print(f"Jetson:  {args.jetson}")
    print(f"Surface: {args.surface}")
    print(f"Start:   {datetime.now().isoformat(timespec='seconds')}")
    print()

    results = []

    # --- Phase 0: Liveness ---
    print("--- Phase 0: Liveness ---")
    r = test_jetson_alive(args.jetson)
    print(r)
    results.append(r)
    if not r.passed:
        print("Jetson nicht erreichbar — Abbruch.")
        return _finish(results, args)

    if not args.skip_surface:
        r = test_surface_alive(args.surface)
        print(r)
        results.append(r)

    # --- Phase 1: Segmenter ---
    print("\n--- Phase 1: Segmentierung (qwen2.5:1.5b + Post-Merge 3) ---")
    r = test_jetson_segment(args.jetson)
    print(r)
    results.append(r)

    # --- Phase 2: 9-Liner ---
    print("\n--- Phase 2: 9-Liner MEDEVAC-Extraktion ---")
    r = test_jetson_nine_liner(args.jetson)
    print(r)
    results.append(r)

    # --- Phase 3: Testdaten + Patientenliste ---
    print("\n--- Phase 3: Testdaten-Generator + State ---")
    r = test_jetson_testdata_gen(args.jetson)
    print(r)
    results.append(r)
    time.sleep(0.5)
    r = test_jetson_patients_list(args.jetson)
    print(r)
    results.append(r)

    # --- Phase 4: Export-Formate ---
    print("\n--- Phase 4: Export (DOCX / PDF / JSON / XML) ---")
    r = test_export(args.jetson, "json", "application/json", 500)
    print(r)
    results.append(r)
    r = test_export(args.jetson, "xml", "application/xml", 500)
    print(r)
    results.append(r)
    r = test_export(args.jetson, "docx", "wordprocessingml", 5000)
    print(r)
    results.append(r)
    r = test_export(args.jetson, "pdf", "pdf", 3000)
    print(r)
    results.append(r)

    # --- Phase 5: Cleanup ---
    if not args.skip_reset:
        print("\n--- Phase 5: Cleanup (Daten-Reset) ---")
        r = test_jetson_reset(args.jetson)
        print(r)
        results.append(r)

    return _finish(results, args)


def _finish(results, args):
    print()
    print("=" * 60)
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    total_duration = sum(r.duration_s for r in results)
    print(f"Ergebnis: {passed}/{total} Tests PASS, Dauer {total_duration:.2f}s")
    print("=" * 60)

    report = {
        "timestamp": datetime.now().isoformat(),
        "jetson": args.jetson,
        "surface": args.surface,
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "total_duration_s": round(total_duration, 2),
        },
        "tests": [
            {
                "name": r.name,
                "passed": r.passed,
                "duration_s": round(r.duration_s, 3),
                "detail": r.detail,
            }
            for r in results
        ],
    }

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(f"\nReport: {args.json_out}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
