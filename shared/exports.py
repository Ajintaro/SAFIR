"""Export-Funktionen für die Patientendatenbank (DOCX/PDF/JSON/XML).

Generisch parametrisiert — nimmt `patients` als Liste, `device_id` und
`unit_name` als Strings, `output_dir` als Path. Wird sowohl vom Jetson-
Backend (`app.py`) als auch vom Surface-Backend (`backend/app.py`)
importiert, damit die Export-Logik an EINER Stelle lebt.

Die 4 Haupt-Funktionen:
    generate_json(patients, device_id, unit_name) -> bytes
    generate_xml(patients, device_id, unit_name) -> bytes
    generate_docx(patients, device_id, unit_name, output_dir) -> Path
    generate_pdf(patients, device_id, unit_name, output_dir) -> Path

JSON + XML geben Bytes zurück (direkt streamen), DOCX + PDF schreiben
in Dateien im output_dir und geben den Pfad zurück.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------
def generate_json(patients: list, device_id: str, unit_name: str) -> bytes:
    """Komplette Patientendatenbank als JSON-Bytes. Schema-versioniert."""
    payload = {
        "schema_version": "1.0",
        "exported_at": datetime.now().isoformat(),
        "device_id": device_id,
        "unit_name": unit_name,
        "patient_count": len(patients),
        "patients": list(patients),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")


# ---------------------------------------------------------------------------
# XML
# ---------------------------------------------------------------------------
def _xml_escape(val) -> str:
    """Minimaler XML-Text-Escape — & < > nur. Werte landen in Element-
    Text, nicht in Attribut-Werten."""
    if val is None:
        return ""
    s = str(val)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _build_patient_xml(patient: dict) -> str:
    """Konvertiert einen Patient-Dict in einen XML-Block. Rekursiv für
    Dicts (verschachtelt) und Listen (`<item>`-Wrapper)."""
    def _emit(key: str, value, indent: int) -> str:
        pad = "  " * indent
        if isinstance(value, dict):
            if not value:
                return f'{pad}<{key}/>\n'
            inner = "".join(_emit(k, v, indent + 1) for k, v in value.items())
            return f'{pad}<{key}>\n{inner}{pad}</{key}>\n'
        if isinstance(value, (list, tuple)):
            if not value:
                return f'{pad}<{key}/>\n'
            inner = "".join(_emit("item", v, indent + 1) for v in value)
            return f'{pad}<{key}>\n{inner}{pad}</{key}>\n'
        return f'{pad}<{key}>{_xml_escape(value)}</{key}>\n'

    pid = patient.get("patient_id", "unknown")
    status = patient.get("flow_status", "")
    out = [f'  <patient id="{_xml_escape(pid)}" status="{_xml_escape(status)}">\n']
    for k, v in patient.items():
        if k in ("patient_id", "flow_status"):
            continue  # schon als Attribut
        out.append(_emit(k, v, 2))
    out.append("  </patient>\n")
    return "".join(out)


def generate_xml(patients: list, device_id: str, unit_name: str) -> bytes:
    """Komplette Patientendatenbank als XML-Bytes. Format:
    <safir-export schema="1.0" device-id="..." unit-name="..." ...>
      <patients>
        <patient id="..." status="..."><name>...</name>...</patient>
      </patients>
    </safir-export>"""
    now_iso = datetime.now().isoformat()
    parts = ['<?xml version="1.0" encoding="UTF-8"?>\n']
    parts.append(
        f'<safir-export schema="1.0" device-id="{_xml_escape(device_id)}" '
        f'unit-name="{_xml_escape(unit_name)}" exported="{now_iso}" '
        f'patient-count="{len(patients)}">\n'
    )
    parts.append("  <patients>\n")
    for patient in patients:
        parts.append(_build_patient_xml(patient))
    parts.append("  </patients>\n")
    parts.append("</safir-export>\n")
    return "".join(parts).encode("utf-8")


# ---------------------------------------------------------------------------
# DOCX (via python-docx)
# ---------------------------------------------------------------------------
def generate_docx(patients: list, device_id: str, unit_name: str,
                  output_dir: Path) -> Path:
    """Eine DOCX-Datei mit Übersichtstabelle + Detail-Block pro Patient.
    Schreibt nach output_dir/safir-patients-<timestamp>.docx.

    Raises ImportError wenn python-docx nicht installiert ist."""
    from docx import Document
    from docx.shared import Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    # Header
    header_para = doc.add_paragraph()
    header_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = header_para.add_run("SAFIR — Patientendatenbank Export")
    run.bold = True
    run.font.size = Pt(16)

    meta_para = doc.add_paragraph()
    meta_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta_run = meta_para.add_run(
        f"Exportiert am {datetime.now().strftime('%d.%m.%Y %H:%M')}  ·  "
        f"Geraet {device_id or '?'}  ·  "
        f"Einheit {unit_name or '?'}  ·  "
        f"{len(patients)} Patient(en)"
    )
    meta_run.font.size = Pt(9)
    meta_run.italic = True
    doc.add_paragraph()

    if not patients:
        doc.add_paragraph("(Keine Patienten in der Datenbank)")
    else:
        # Uebersichtstabelle
        doc.add_heading("Uebersicht", level=2)
        headers = ["Patient-ID", "Name", "Dienstgrad", "Triage", "Status", "Sync"]
        table = doc.add_table(rows=1, cols=len(headers))
        table.style = "Table Grid"
        hdr_row = table.rows[0].cells
        for i, h in enumerate(headers):
            hdr_row[i].text = h
            for p in hdr_row[i].paragraphs:
                for r in p.runs:
                    r.bold = True
        for p in patients:
            row = table.add_row().cells
            row[0].text = p.get("patient_id", "")
            row[1].text = p.get("name", "Unbekannt") or "Unbekannt"
            row[2].text = p.get("rank", "") or "—"
            row[3].text = p.get("triage", "") or "—"
            row[4].text = p.get("flow_status", "") or p.get("status", "")
            row[5].text = "✓" if p.get("synced") else "—"
        doc.add_paragraph()

        # Detail-Sektion pro Patient
        for idx, p in enumerate(patients):
            doc.add_page_break()
            heading = doc.add_heading(
                f"Patient {idx + 1} — {p.get('name', 'Unbekannt')}", level=1
            )
            heading.alignment = WD_ALIGN_PARAGRAPH.LEFT

            # Stammdaten
            stamm = [
                ("Patient-ID", p.get("patient_id", "")),
                ("Dienstgrad", p.get("rank", "") or "—"),
                ("Einheit", p.get("unit", "") or "—"),
                ("Nationalitaet", p.get("nationality", "") or "—"),
                ("Blutgruppe", p.get("blood_type", "") or "—"),
                ("Allergien", p.get("allergies", "") or "—"),
                ("Triage", p.get("triage", "") or "—"),
                ("Status", p.get("status", "") or "—"),
                ("Flow-Status", p.get("flow_status", "") or "—"),
                ("Aktuelle Rolle", p.get("current_role", "") or "—"),
                ("RFID-UID", p.get("rfid_tag_id", "") or "—"),
                ("Erfasst von", p.get("created_by", "") or "—"),
                ("Erfasst am", p.get("timestamp_created", "") or "—"),
                ("An Leitstelle gemeldet", "Ja" if p.get("synced") else "Nein"),
            ]
            t = doc.add_table(rows=len(stamm), cols=2)
            t.style = "Table Grid"
            for i, (label, value) in enumerate(stamm):
                c0 = t.rows[i].cells[0]
                c0.text = label
                for pr in c0.paragraphs:
                    for r in pr.runs:
                        r.bold = True
                t.rows[i].cells[1].text = str(value)
            doc.add_paragraph()

            # 9-Liner MEDEVAC
            nl = p.get("nine_liner") or {}
            filled = [k for k in [f"line{i}" for i in range(1, 10)] if nl.get(k)]
            if p.get("template_type") == "9liner" or filled:
                doc.add_heading(f"9-Liner MEDEVAC ({len(filled)}/9 Felder)", level=2)
                nl_labels = {
                    "line1": "Koordinaten Landezone",
                    "line2": "Funkfrequenz / Rufzeichen",
                    "line3": "Patienten / Dringlichkeit",
                    "line4": "Sonderausstattung",
                    "line5": "Liegend / Gehfaehig",
                    "line6": "Sicherheitslage",
                    "line7": "Markierung Landeplatz",
                    "line8": "Nationalitaet / Status",
                    "line9": "ABC / Gelaende",
                }
                nt = doc.add_table(rows=9, cols=2)
                nt.style = "Table Grid"
                for i in range(1, 10):
                    key = f"line{i}"
                    c0 = nt.rows[i - 1].cells[0]
                    c0.text = f"L{i} {nl_labels[key]}"
                    for pr in c0.paragraphs:
                        for r in pr.runs:
                            r.bold = True
                    nt.rows[i - 1].cells[1].text = str(nl.get(key, "") or "—")
                doc.add_paragraph()

            # Vitals
            vitals = p.get("vitals") or {}
            if any(vitals.values()):
                doc.add_heading("Vitalwerte", level=2)
                vt = doc.add_table(rows=0, cols=2)
                vt.style = "Table Grid"
                vital_labels = {
                    "pulse": "Puls (bpm)",
                    "bp": "Blutdruck",
                    "resp_rate": "Atemfrequenz",
                    "spo2": "SpO2 (%)",
                    "temp": "Temperatur (°C)",
                    "gcs": "GCS",
                }
                for key, label in vital_labels.items():
                    val = vitals.get(key)
                    if val:
                        row = vt.add_row().cells
                        row[0].text = label
                        for pr in row[0].paragraphs:
                            for r in pr.runs:
                                r.bold = True
                        row[1].text = str(val)
                doc.add_paragraph()

            # Verletzungen
            injuries = p.get("injuries") or []
            if injuries:
                doc.add_heading("Verletzungen", level=2)
                for inj in injuries:
                    doc.add_paragraph(f"• {inj}")
                doc.add_paragraph()

            # Behandlungen / Medikamente
            treatments = p.get("treatments") or []
            medications = p.get("medications") or []
            if treatments or medications:
                doc.add_heading("Behandlungen / Medikamente", level=2)
                for item in treatments:
                    val = item if isinstance(item, str) else (
                        item.get("description") or json.dumps(item, ensure_ascii=False)
                    )
                    doc.add_paragraph(f"• {val}")
                for item in medications:
                    val = item if isinstance(item, str) else (
                        item.get("name") or json.dumps(item, ensure_ascii=False)
                    )
                    doc.add_paragraph(f"• {val}")
                doc.add_paragraph()

            # Transkripte
            transcripts = p.get("transcripts") or []
            if transcripts:
                doc.add_heading("Transkripte", level=2)
                for tr in transcripts:
                    if isinstance(tr, dict):
                        time_str = tr.get("time", "")
                        text = tr.get("text", "")
                    else:
                        time_str = ""
                        text = str(tr)
                    para = doc.add_paragraph()
                    if time_str:
                        rt = para.add_run(f"[{time_str}] ")
                        rt.bold = True
                        rt.font.size = Pt(9)
                    para.add_run(text)
                doc.add_paragraph()

            # Timeline (letzte 10)
            timeline = p.get("timeline") or []
            if timeline:
                doc.add_heading("Timeline", level=2)
                for ev in timeline[-10:]:
                    if isinstance(ev, dict):
                        line = (
                            f"{ev.get('time', '')}  ·  [{ev.get('role', '')}]  "
                            f"{ev.get('event', '')}  —  {ev.get('details', '')}"
                        )
                    else:
                        line = str(ev)
                    para = doc.add_paragraph(line)
                    for r in para.runs:
                        r.font.size = Pt(9)

    # Footer
    doc.add_paragraph()
    doc.add_heading("Unterschrift", level=2)
    doc.add_paragraph("_" * 30)

    output_dir.mkdir(exist_ok=True, parents=True)
    filename = f"safir-patients-{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
    filepath = output_dir / filename
    doc.save(str(filepath))
    return filepath


# ---------------------------------------------------------------------------
# PDF (via reportlab)
# ---------------------------------------------------------------------------
def generate_pdf(patients: list, device_id: str, unit_name: str,
                 output_dir: Path) -> Path:
    """Eine PDF-Datei mit Übersicht + Detail pro Patient. Design in
    Bundeswehr-Olive für Brand-Konsistenz. Schreibt nach
    output_dir/safir-patients-<timestamp>.pdf.

    Raises ImportError wenn reportlab nicht installiert ist."""
    from reportlab.lib import colors as _rl_colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        PageBreak,
    )

    # Bundeswehr-Olive-Akzent
    BW_TAN = _rl_colors.HexColor("#c8b878")
    BW_DARK = _rl_colors.HexColor("#3a4a2e")
    BW_BG = _rl_colors.HexColor("#f4f1e3")

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="SAFIRTitle", parent=styles["Title"],
        fontSize=18, textColor=BW_DARK, spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        name="SAFIRMeta", parent=styles["Normal"],
        fontSize=9, textColor=_rl_colors.grey, spaceAfter=16, alignment=1,
    ))
    styles.add(ParagraphStyle(
        name="SAFIRH1", parent=styles["Heading1"],
        fontSize=14, textColor=BW_DARK, spaceBefore=8, spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        name="SAFIRH2", parent=styles["Heading2"],
        fontSize=11, textColor=BW_DARK, spaceBefore=8, spaceAfter=4,
    ))

    def _kv_table(rows: list, col_widths=(55 * mm, 105 * mm)):
        tbl = Table(rows, colWidths=col_widths, hAlign="LEFT")
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), BW_BG),
            ("TEXTCOLOR", (0, 0), (0, -1), BW_DARK),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("LINEBELOW", (0, 0), (-1, -1), 0.3, _rl_colors.lightgrey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        return tbl

    def _esc(v):
        if v is None:
            return ""
        s = str(v)
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    story = []
    story.append(Paragraph("SAFIR — Patientendatenbank Export", styles["SAFIRTitle"]))
    meta = (
        f"Exportiert am {datetime.now().strftime('%d.%m.%Y %H:%M')}  ·  "
        f"Gerät {_esc(device_id or '?')}  ·  "
        f"Einheit {_esc(unit_name or '?')}  ·  "
        f"{len(patients)} Patient(en)"
    )
    story.append(Paragraph(meta, styles["SAFIRMeta"]))

    if not patients:
        story.append(Paragraph("(Keine Patienten in der Datenbank)", styles["Normal"]))
    else:
        # Uebersichtstabelle
        story.append(Paragraph("Übersicht", styles["SAFIRH1"]))
        overview_rows = [["Patient-ID", "Name", "Dienstgrad", "Triage", "Status", "Sync"]]
        for p in patients:
            overview_rows.append([
                _esc(p.get("patient_id", "")),
                _esc(p.get("name", "Unbekannt") or "Unbekannt"),
                _esc(p.get("rank", "") or "—"),
                _esc(p.get("triage", "") or "—"),
                _esc(p.get("flow_status", "") or p.get("status", "")),
                "✓" if p.get("synced") else "—",
            ])
        ov_tbl = Table(overview_rows, hAlign="LEFT",
                       colWidths=(28 * mm, 40 * mm, 30 * mm, 18 * mm, 28 * mm, 14 * mm))
        ov_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BW_DARK),
            ("TEXTCOLOR", (0, 0), (-1, 0), _rl_colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [_rl_colors.white, BW_BG]),
            ("GRID", (0, 0), (-1, -1), 0.3, _rl_colors.lightgrey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(ov_tbl)

        # Detail-Sektion pro Patient
        for idx, p in enumerate(patients):
            story.append(PageBreak())
            story.append(Paragraph(
                f"Patient {idx + 1} — {_esc(p.get('name', 'Unbekannt'))}",
                styles["SAFIRH1"],
            ))

            stamm_rows = [
                ["Patient-ID", _esc(p.get("patient_id", ""))],
                ["Dienstgrad", _esc(p.get("rank", "") or "—")],
                ["Einheit", _esc(p.get("unit", "") or "—")],
                ["Nationalität", _esc(p.get("nationality", "") or "—")],
                ["Blutgruppe", _esc(p.get("blood_type", "") or "—")],
                ["Allergien", _esc(p.get("allergies", "") or "—")],
                ["Triage", _esc(p.get("triage", "") or "—")],
                ["Status", _esc(p.get("status", "") or "—")],
                ["Flow-Status", _esc(p.get("flow_status", "") or "—")],
                ["Aktuelle Rolle", _esc(p.get("current_role", "") or "—")],
                ["RFID-UID", _esc(p.get("rfid_tag_id", "") or "—")],
                ["Erfasst von", _esc(p.get("created_by", "") or "—")],
                ["Erfasst am", _esc(p.get("timestamp_created", "") or "—")],
                ["Gemeldet", "Ja" if p.get("synced") else "Nein"],
            ]
            story.append(_kv_table(stamm_rows))
            story.append(Spacer(1, 6))

            nl = p.get("nine_liner") or {}
            filled = [k for k in [f"line{i}" for i in range(1, 10)] if nl.get(k)]
            if p.get("template_type") == "9liner" or filled:
                story.append(Paragraph(
                    f"9-Liner MEDEVAC ({len(filled)}/9 Felder)",
                    styles["SAFIRH2"],
                ))
                nl_labels = {
                    "line1": "L1 Koordinaten Landezone",
                    "line2": "L2 Funkfrequenz / Rufzeichen",
                    "line3": "L3 Patienten / Dringlichkeit",
                    "line4": "L4 Sonderausstattung",
                    "line5": "L5 Liegend / Gehfähig",
                    "line6": "L6 Sicherheitslage",
                    "line7": "L7 Markierung Landeplatz",
                    "line8": "L8 Nationalität / Status",
                    "line9": "L9 ABC / Gelände",
                }
                nl_rows = []
                for i in range(1, 10):
                    key = f"line{i}"
                    nl_rows.append([nl_labels[key], _esc(nl.get(key, "") or "—")])
                story.append(_kv_table(nl_rows))
                story.append(Spacer(1, 6))

            vitals = p.get("vitals") or {}
            if any(vitals.values()):
                story.append(Paragraph("Vitalwerte", styles["SAFIRH2"]))
                vital_labels = {
                    "pulse": "Puls (bpm)",
                    "bp": "Blutdruck",
                    "resp_rate": "Atemfrequenz",
                    "spo2": "SpO2 (%)",
                    "temp": "Temperatur (°C)",
                    "gcs": "GCS",
                }
                vrows = []
                for key, label in vital_labels.items():
                    if vitals.get(key):
                        vrows.append([label, _esc(vitals[key])])
                if vrows:
                    story.append(_kv_table(vrows))
                story.append(Spacer(1, 6))

            injuries = p.get("injuries") or []
            if injuries:
                story.append(Paragraph("Verletzungen", styles["SAFIRH2"]))
                for inj in injuries:
                    story.append(Paragraph(f"• {_esc(inj)}", styles["Normal"]))
                story.append(Spacer(1, 6))

            treatments = p.get("treatments") or []
            medications = p.get("medications") or []
            if treatments or medications:
                story.append(Paragraph("Behandlungen / Medikamente", styles["SAFIRH2"]))
                for item in treatments:
                    val = item if isinstance(item, str) else (
                        item.get("description") or json.dumps(item, ensure_ascii=False)
                    )
                    story.append(Paragraph(f"• {_esc(val)}", styles["Normal"]))
                for item in medications:
                    val = item if isinstance(item, str) else (
                        item.get("name") or json.dumps(item, ensure_ascii=False)
                    )
                    story.append(Paragraph(f"• {_esc(val)}", styles["Normal"]))
                story.append(Spacer(1, 6))

            transcripts = p.get("transcripts") or []
            if transcripts:
                story.append(Paragraph("Transkripte", styles["SAFIRH2"]))
                for tr in transcripts:
                    if isinstance(tr, dict):
                        time_str = tr.get("time", "")
                        text = tr.get("text", "")
                    else:
                        time_str = ""
                        text = str(tr)
                    pf = (f"<b>[{_esc(time_str)}]</b> " if time_str else "") + _esc(text)
                    story.append(Paragraph(pf, styles["Normal"]))
                story.append(Spacer(1, 6))

            timeline = p.get("timeline") or []
            if timeline:
                story.append(Paragraph("Timeline", styles["SAFIRH2"]))
                for ev in timeline[-10:]:
                    if isinstance(ev, dict):
                        line = (
                            f"{_esc(ev.get('time',''))}  ·  [{_esc(ev.get('role',''))}]  "
                            f"{_esc(ev.get('event',''))}  —  {_esc(ev.get('details',''))}"
                        )
                    else:
                        line = _esc(ev)
                    story.append(Paragraph(line, styles["Normal"]))

    output_dir.mkdir(exist_ok=True, parents=True)
    filename = f"safir-patients-{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    filepath = output_dir / filename
    doc_pdf = SimpleDocTemplate(
        str(filepath),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title="SAFIR Patientendatenbank",
        author="SAFIR / CGI Deutschland",
    )
    doc_pdf.build(story)
    return filepath
