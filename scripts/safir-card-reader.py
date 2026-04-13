#!/usr/bin/env python3
"""
SAFIR Card Reader — Desktop-Tool für den Notfallzentrums-PC (Surface).

Liest SAFIR-Patientenkarten (MIFARE Classic 1K) über einen PC/SC-Reader
(z.B. ReinerSCT cyberJack RFID, ACR122U) und zeigt die Daten in einem
kleinen Tk-Fenster an.

Voraussetzungen:
  - Windows/Linux/macOS mit installiertem PC/SC-Daemon und -Treiber
  - pyscard (pip install pyscard)
  - Ein kontaktloser Reader der MIFARE Classic 1K pseudo-APDUs unterstützt

Installation:
  python -m venv venv
  venv\\Scripts\\activate       (Windows)  oder  source venv/bin/activate (Linux/macOS)
  pip install pyscard

Start:
  python safir-card-reader.py

Optional: SAFIR-Backend-URL als Umgebungsvariable
  set SAFIR_BACKEND=http://192.168.1.100:8080
  Das Tool versucht dann beim erfolgreichen Lesen einer Karte den
  vollständigen Patientendatensatz unter /api/patients/{id} zu holen.
"""
import os
import struct
import sys
import tkinter as tk
from tkinter import ttk, messagebox

try:
    from smartcard.System import readers
    from smartcard.util import toHexString
    from smartcard.Exceptions import NoCardException, CardConnectionException
except ImportError:
    print("FEHLER: pyscard nicht installiert. Bitte ausführen: pip install pyscard")
    sys.exit(1)

try:
    import urllib.request
    import json as _json
    _urllib_ok = True
except Exception:
    _urllib_ok = False


SAFIR_MAGIC = b"SAFIR\0\0\0"
DEFAULT_KEY = [0xFF] * 6
BACKEND_URL = os.environ.get("SAFIR_BACKEND", "").rstrip("/")


# ---------------------------------------------------------------------------
# PC/SC Low-Level
# ---------------------------------------------------------------------------
def _send_apdu(conn, apdu, expected_sw=(0x90, 0x00)):
    resp, sw1, sw2 = conn.transmit(apdu)
    ok = (sw1, sw2) == expected_sw
    return ok, resp, sw1, sw2


def _load_key(conn):
    apdu = [0xFF, 0x82, 0x00, 0x00, 0x06] + DEFAULT_KEY
    ok, _, sw1, sw2 = _send_apdu(conn, apdu)
    if not ok:
        raise RuntimeError(f"Load Key fehlgeschlagen (SW {sw1:02X}{sw2:02X})")


def _auth(conn, block, key_slot=0x00, key_type=0x60):
    """General Authenticate auf einen Block mit Key A aus key_slot."""
    apdu = [0xFF, 0x86, 0x00, 0x00, 0x05, 0x01, 0x00, block, key_type, key_slot]
    ok, _, sw1, sw2 = _send_apdu(conn, apdu)
    if not ok:
        raise RuntimeError(f"Auth Block {block} fehlgeschlagen (SW {sw1:02X}{sw2:02X})")


def _read_block(conn, block):
    apdu = [0xFF, 0xB0, 0x00, block, 0x10]
    ok, resp, sw1, sw2 = _send_apdu(conn, apdu)
    if not ok:
        raise RuntimeError(f"Read Block {block} fehlgeschlagen (SW {sw1:02X}{sw2:02X})")
    return bytes(resp)


def _get_uid(conn):
    apdu = [0xFF, 0xCA, 0x00, 0x00, 0x00]
    ok, resp, sw1, sw2 = _send_apdu(conn, apdu)
    if not ok:
        return None
    return "".join(f"{b:02X}" for b in resp)


# ---------------------------------------------------------------------------
# Parsing der SAFIR-Blöcke
# ---------------------------------------------------------------------------
def parse_safir_card(blocks: dict) -> dict | None:
    b4 = blocks.get(4)
    if not b4 or b4[:8] != SAFIR_MAGIC:
        return None
    version = b4[8]
    written_ts = struct.unpack_from("<I", b4, 12)[0]

    b5 = blocks.get(5, b"\x00" * 16)
    patient_id = b5.rstrip(b"\x00").decode("ascii", errors="ignore")

    b6 = blocks.get(6, b"\x00" * 16)
    triage_map = {1: "T1 Sofort (Rot)", 2: "T2 Dringend (Gelb)",
                  3: "T3 Leicht (Grün)", 4: "T4 Abwartend (Blau)"}
    triage = triage_map.get(b6[0], "Unbekannt")
    age = b6[1]
    gender_byte = b6[2]
    gender = chr(gender_byte) if gender_byte else "?"
    rr_sys, rr_dia, puls, af, spo2, gcs = b6[4], b6[5], b6[6], b6[7], b6[8], b6[9]

    b8 = blocks.get(8, b"")
    b9 = blocks.get(9, b"")
    name = (b8 + b9).rstrip(b"\x00").decode("utf-8", errors="ignore")

    b10 = blocks.get(10, b"")
    mechanism = b10.rstrip(b"\x00").decode("utf-8", errors="ignore")

    return {
        "version": version,
        "written_unix": written_ts,
        "patient_id": patient_id,
        "name": name,
        "triage": triage,
        "age": age,
        "gender": gender,
        "rr_sys": rr_sys,
        "rr_dia": rr_dia,
        "puls": puls,
        "af": af,
        "spo2": spo2,
        "gcs": gcs,
        "mechanism": mechanism,
    }


def read_safir_card(reader_name: str) -> tuple[dict | None, str]:
    """Komplett-Flow: verbinden, lesen, parsen. Gibt (daten, uid_oder_fehler)."""
    r_list = readers()
    r = next((x for x in r_list if reader_name in str(x)), None)
    if r is None:
        return (None, f"Reader '{reader_name}' nicht gefunden")
    conn = r.createConnection()
    try:
        conn.connect()
    except NoCardException:
        return (None, "Keine Karte auf dem Reader")
    except CardConnectionException as e:
        return (None, f"Verbindung fehlgeschlagen: {e}")

    try:
        uid = _get_uid(conn)
        _load_key(conn)
        blocks = {}
        # Sektor 1: Blöcke 4, 5, 6 — Auth einmal auf Block 4
        _auth(conn, 4)
        for blk in (4, 5, 6):
            blocks[blk] = _read_block(conn, blk)
        # Sektor 2: Blöcke 8, 9, 10 — Auth auf Block 8
        _auth(conn, 8)
        for blk in (8, 9, 10):
            blocks[blk] = _read_block(conn, blk)
    except Exception as e:
        return (None, f"Fehler beim Lesen: {e}")
    finally:
        try:
            conn.disconnect()
        except Exception:
            pass

    data = parse_safir_card(blocks)
    if data is None:
        return (None, f"Keine SAFIR-Karte (UID {uid})")
    data["uid"] = uid
    return (data, uid)


def fetch_full_patient(patient_id: str) -> dict | None:
    """Optional: vollständigen Patient vom SAFIR-Backend nachladen."""
    if not BACKEND_URL or not _urllib_ok or not patient_id:
        return None
    try:
        with urllib.request.urlopen(f"{BACKEND_URL}/api/patients/{patient_id}", timeout=3) as r:
            return _json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Tk-UI
# ---------------------------------------------------------------------------
class CardReaderApp:
    def __init__(self, root):
        self.root = root
        root.title("SAFIR Card Reader")
        root.geometry("600x500")

        top = ttk.Frame(root, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="Reader:").pack(side="left")
        self.reader_var = tk.StringVar()
        self.reader_combo = ttk.Combobox(top, textvariable=self.reader_var, width=50)
        self.reader_combo.pack(side="left", padx=5)
        self._refresh_readers()

        ttk.Button(top, text="Aktualisieren", command=self._refresh_readers).pack(side="left", padx=3)
        ttk.Button(top, text="Karte lesen", command=self._read_card).pack(side="left", padx=3)

        # Info-Bereich
        self.info_frame = ttk.LabelFrame(root, text="Patientendaten", padding=10)
        self.info_frame.pack(fill="both", expand=True, padx=10, pady=5)

        self.text = tk.Text(self.info_frame, wrap="word", font=("Consolas", 11))
        self.text.pack(fill="both", expand=True)
        self.text.insert("1.0", "Karte auflegen und 'Karte lesen' drücken...")
        self.text.config(state="disabled")

        # Statusleiste
        self.status = ttk.Label(root, text="Bereit", anchor="w", relief="sunken")
        self.status.pack(fill="x", side="bottom")

    def _refresh_readers(self):
        try:
            names = [str(r) for r in readers()]
        except Exception as e:
            names = []
            messagebox.showerror("Fehler", f"PC/SC nicht verfügbar: {e}")
        self.reader_combo["values"] = names
        if names:
            self.reader_combo.current(0)

    def _read_card(self):
        reader_name = self.reader_var.get()
        if not reader_name:
            messagebox.showwarning("Fehler", "Kein Reader ausgewählt.")
            return
        self.status.config(text=f"Lese Karte von {reader_name}...")
        self.root.update_idletasks()

        data, err = read_safir_card(reader_name)
        if data is None:
            self.status.config(text=f"Fehler: {err}")
            self._set_text(f"FEHLER: {err}")
            return

        full = fetch_full_patient(data["patient_id"])
        out = self._format(data, full)
        self._set_text(out)
        self.status.config(text=f"OK — UID {data.get('uid', '?')}")

    def _set_text(self, content: str):
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", content)
        self.text.config(state="disabled")

    def _format(self, data: dict, full: dict | None) -> str:
        import datetime as _dt
        ts = _dt.datetime.fromtimestamp(data["written_unix"]).strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            f"═══ SAFIR Patient (Karten-UID {data.get('uid', '?')}) ═══",
            "",
            f"Patient-ID:   {data['patient_id']}",
            f"Name:         {data.get('name') or '---'}",
            f"Triage:       {data['triage']}",
            f"Alter:        {data['age']}",
            f"Geschlecht:   {data['gender']}",
            "",
            "── Vitalzeichen (beim Schreiben) ──",
            f"Blutdruck:    {data['rr_sys']}/{data['rr_dia']} mmHg",
            f"Puls:         {data['puls']}/min",
            f"Atemfreq.:    {data['af']}/min",
            f"SpO2:         {data['spo2']}%",
            f"GCS:          {data['gcs']}",
            "",
            f"Mechanismus:  {data.get('mechanism') or '---'}",
            "",
            f"Geschrieben:  {ts}   (Karten-Version {data['version']})",
        ]
        if full:
            lines.append("")
            lines.append("── Zusatzdaten vom SAFIR-Backend ──")
            lines.append(f"Flow-Status:  {full.get('flow_status', '?')}")
            lines.append(f"Aktuelle Role: {full.get('current_role', '?')}")
            transcripts = full.get("transcripts") or []
            if transcripts:
                lines.append("")
                lines.append("── Transkripte ──")
                for t in transcripts[-3:]:
                    lines.append(f"  {t[:80]}")
        elif BACKEND_URL:
            lines.append("")
            lines.append(f"(Backend {BACKEND_URL} nicht erreichbar — nur On-Card-Daten)")
        return "\n".join(lines)


def main():
    root = tk.Tk()
    app = CardReaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
