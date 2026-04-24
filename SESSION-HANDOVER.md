# SAFIR — Session-Handover (Account-Wechsel)

> **Erstellt:** 23.04.2026
> **Grund:** Wechsel auf Firmen-Anthropic-Account (5h-Limit umgangen)
> **Repo-State:** alles committed auf Branch `main`, gepusht zu `origin`

Dieses Dokument ist DIE Anweisung für die nächste Claude-Code-Session,
nachdem du auf den neuen Account gewechselt bist. Lies zuerst hier,
dann `CLAUDE.md`, dann `docs/PROGRESS.md`.

---

## Wie du fortfährst (neue Session)

1. Im neuen Account: `claude` im Verzeichnis `C:\Users\the_s\Documents\SAFIR`
   starten (Windows — NICHT WSL, weil die Surface-Prozesse als Windows-
   Prozesse laufen).
2. Erste Prompt-Empfehlung an Claude: *„Lies SESSION-HANDOVER.md und
   CLAUDE.md und sag mir wo wir stehen."*
3. Claude soll dann `git log --oneline -20` und `git status` prüfen.
4. Danach Surface-Status checken (siehe unten).

## Was zuletzt gemacht wurde (Stand 23.04.2026, 22:15 UTC+2)

### In Arbeit / gerade fertig
- **Dokumente-Seite komplett neu**: Statt Placeholder jetzt echter
  Export-Bereich im UI. Zugänglich über Sidebar → „Dokumente".
  * Abschnitt **Alle Patienten**: 4 Buttons DOCX / PDF / JSON / XML
  * Abschnitt **Einzelpatient**: Dropdown + DOCX/PDF-Buttons
  * Abschnitt **Export-Historie**: Tabelle mit Datum/Typ/Größe +
    Download-/Löschen-Buttons
- **Settings → System**: Doppelte Export-Card entfernt, ersetzt durch
  Hinweis-Karte mit Link zur Dokumente-Seite
- **Backend-Endpoints** (alle `/api/export/...`):
  * `POST /api/export/docx/all` + `/pdf/all` + `/json/all` + `/xml/all`
  * `POST /api/export/docx/patient/{pid}` + `/pdf/patient/{pid}`
  * `GET /api/export/list` — listet Dateien in `PROTOCOLS_DIR_EXPORT`
  * `GET /api/export/download/{filename}` (mit Path-Traversal-Schutz)
  * `DELETE /api/export/delete/{filename}`
- **KI-Review mit 3 Checks** (Surface Gemma 4 prüft Jetson):
  * `missing` (Patient fehlt komplett)
  * `missing_fields` (Feld nicht extrahiert obwohl im Transkript)
  * `wrong_assignment` (Daten beim falschen Patient)
  * Few-Shot-Examples im Prompt gegen False-Positives
  * Loading-Spinner während Analyse
- **Bugfixes**:
  * Export produzierte ungültige Dateien → `python-docx` + `reportlab`
    waren nicht installiert; außerdem HTTP 200 bei Fehler → jetzt 500/503
  * Ghost-Popups bei Page-Reload → init-Handler triggert keine Toasts
    mehr für historische Events
  * Worker-Kill durch `--reload` → aus `start-surface.cmd` raus
  * Doppel-registrierter `/api/sessions` Endpoint (alter Stub) → weg

### Committed (alle auf origin/main)
```
ebfa617 Export DOCX/PDF: Libraries installieren + HTTP-Status fixen
40d2f90 KI-Review: 3 Checks + Loading-Indikator + Few-Shot-Prompt
aa5c7d4 Reload-Toasts: Keine Geister-Popups mehr fuer historische Events
25547f9 Session-Review E2E funktioniert: Gemma 4 findet fehlende Patienten
8a80686 Session-Review: Gemma 4 auf Surface prueft Jetson-Extraktion
d41de7b Segmenter: Trigger-Phrasen systematisch erweitert
a4734b8 Segmenter: Post-Merge 5 Forced-Split + Konfidenz-Legende weg
```

---

## System-Check nach Session-Start

### 1. Surface-Backend läuft? (Port 8080)
```powershell
curl -s http://localhost:8080/api/export/list | head -c 200
```
Soll JSON mit `files[]` zurückgeben. Falls nein → starten:
```cmd
cmd /c "C:\Users\the_s\Documents\SAFIR\backend\start-surface.cmd"
```
Alternativ als Background-Task mit `run_in_background=true`.

**WICHTIG**: `start-surface.cmd` hat KEIN `--reload`. Das war Absicht,
weil uvicorn den Worker sonst killt sobald `save_patient()` JSON-Files
in `backend/data/` schreibt → In-Memory-State (`state.sessions` etc.)
geht verloren.

### 2. Ollama läuft? (Port 11434)
```powershell
curl -s http://localhost:11434/api/tags
```
Soll Liste mit installierten Modellen zeigen. Mindestens muss
`gemma4:e4b` (oder `gemma4:latest`) drin sein (~9.6 GB, für
Session-Review auf Surface).

### 3. Jetson erreichbar? (Tailscale)
```powershell
curl -s -m 3 http://100.126.179.27:8080/api/status
```
Falls nicht erreichbar: Jetson ist aus oder Tailscale-Tunnel tot.
Für pure Surface-Arbeit nicht kritisch.

---

## Kritische Gotchas (bitte NICHT vergessen)

### `start-surface.cmd` darf kein `--reload` haben
Grund: uvicorn mit `--reload` watcht per Default auch `backend/data/`
(wo Patient-JSONs geschrieben werden). Sobald `save_patient()` ein
File schreibt → uvicorn killt Worker → `state.sessions`,
`state.pending_transcripts` etc. sind weg.

Das hat uns in der letzten Session ~1h gekostet.

Für Code-Updates: Fenster mit Ctrl+C stoppen, `start-surface.cmd`
wieder starten. Patient-Daten bleiben durch `save_patient()` persistent.

### Gemma-Versionen (nicht verwechseln!)
| Gerät | Modell | Zweck | RAM |
|---|---|---|---|
| Surface | `gemma4:e4b` | Session-Review (Jetson-Check) | 9.6 GB |
| Jetson | `gemma3:4b` | Segmenter + Enrichment | 3.3 GB |

Surface kann Gemma 4 problemlos laden (viel RAM). Jetson hat nur
7.4 GB shared CPU/GPU RAM — da ist Gemma 4 NICHT möglich neben Whisper.

### Gemma 4 Reasoning-Tokens
Gemma 4 denkt per Default — das frisst alle `num_predict` Tokens auf,
bevor er irgendwas ausgibt. Der Review-Endpoint setzt deshalb hart:
```python
"think": False,
"num_predict": 2048,
"format": "json",
```
Niemals `think: True` für den Review. Immer JSON-Format-Constraint,
sonst bekommen wir Markdown-Code-Fences im Response.

### Few-Shot-Examples in f-String
Der Prompt enthält JSON-Beispiele. Diese MÜSSEN mit Plain-Text
geschrieben sein, NICHT als JSON-Literal mit `{` `}`, weil der
Python f-String das als Format-Slot interpretiert. Aktuelle Lösung:
Beispiele als Text, z.B.:
```
Beispiel 1: Transkript erwähnt 3 Patienten, aber nur 2 erkannt.
Antwort: missing=[name des dritten], wrong_assignment=[], ...
```

### Windows-Prozesse stoppen
`Stop-Process -Name python -Force` killt ALLE Python-Prozesse auf
Surface — auch Claude Code selbst. Bitte vorher prüfen ob
nur der uvicorn-Prozess gestoppt werden soll:
```powershell
Get-Process python | Where-Object { $_.MainWindowTitle -like "*uvicorn*" }
```
Oder via Port-Lookup:
```powershell
$pid = (Get-NetTCPConnection -LocalPort 8080 -ErrorAction SilentlyContinue).OwningProcess | Select-Object -First 1
if ($pid) { Stop-Process -Id $pid -Force }
```

---

## Bekannte offene Punkte

### Jetson-Segmenter: „Puls Niveau" Split-Bug
**Symptom**: User diktierte 3 Patienten. Bei der Analyse wurde der
Text „Puls Niveau. bei 140 Sauerstoffsättigung bei 90" beim FALSCHEN
Patient einsortiert (Fragment von Patient 2 landete bei Patient 3).

**Status**: Post-Merge 5 (Forced-Split bei starken Markern) wurde
implementiert (`d41de7b`, `a4734b8`), aber der Fall „Puls Niveau.
bei 140" zeigt, dass ein End-Fragment („Puls Niveau.") als
eigenständiges Stück behandelt wurde und dann beim nächsten
Patient landete.

**Vermutung**: `_split_sentences` im Jetson-`app.py` merget Fragmente
< 30 chars nach dem vorherigen, aber „Puls Niveau." ist 12 chars
und landet trotzdem separat wenn `merged[-1]` gerade leer ist oder
direkt nach Segmentgrenze.

**Reproduzierbarkeit**: War in User's Live-Test, nicht in den
Test-Skripten reproduziert. Nächste Session: `/api/test/segment`
mit dem Original-Transkript füttern und sehen wo es splittet.

### Session-Review macht False-Negatives
KI fand bei einem echten Test **nichts**, obwohl ein Text
abgeschnitten wurde. Prompt arbeitet noch nicht 100% zuverlässig.
Mögliche Verbesserungen:
- Transkript auch mit Time-Stamps im Prompt, falls verfügbar
- Check „Ist die letzte Zeile des Transkripts im letzten Patient?"
- Fuzzy-Match zwischen Transkript-Tokens und Patient-Notes-Tokens

### RFID-Operator OP2 in config.json
Ein neuer RFID-Operator `OP2 (Jaimy Reuter, Arzt, UID 6C472E06)`
wurde in `backend/config.json` ergänzt. Das ist ein echter RFID-
Ausweis, der beim letzten Setup eingelesen wurde. Bitte im neuen
Account NICHT versehentlich entfernen.

---

## Tech-Stack-Cheat-Sheet

| Komponente | Wo | Port | Kommentar |
|---|---|---|---|
| Surface-Backend (FastAPI) | Windows | 8080 | Kein --reload! |
| Surface-Ollama | Windows | 11434 | Gemma 4 E4B |
| Jetson-Backend (FastAPI) | Jetson | 8080 | via Tailscale |
| Jetson-Ollama | Jetson | 11434 | Gemma 3 4B, keep_alive=-1 |
| Jetson-Whisper (whisper.cpp) | Jetson | intern | large-v3-turbo |
| Jetson-Vosk | Jetson | intern | CPU, Sprachbefehle |
| Jetson-Piper TTS | Jetson | intern | Thorsten-high |

## Repo-Struktur (Kurz)
```
SAFIR/
├── app.py                    # Jetson-Hauptcode (165 KB)
├── backend/
│   ├── app.py                # Surface-Backend (Session-Review, Export)
│   ├── config.json           # Surface-Config (Ollama-URL, Operators)
│   ├── requirements.txt      # python-docx, reportlab drin
│   ├── start-surface.cmd     # OHNE --reload
│   └── data/                 # Patient-JSONs (persistent)
├── templates/
│   └── index.html            # Gemeinsames UI (Surface + Jetson nutzen dasselbe)
├── shared/                   # models, rfid, tts
├── jetson/                   # oled, hardware
├── docs/
│   ├── PROGRESS.md           # Master-Progress-Datei
│   ├── messe-hardening-plan.md
│   └── ...
├── CLAUDE.md                 # Projekt-Kontext für Claude
└── SESSION-HANDOVER.md       # DIESE Datei
```

---

## Nächste sinnvolle Schritte

Priorisiert nach AFCEA-Relevanz (Messe in ~2 Wochen):

1. **„Puls Niveau" Split-Bug reproduzieren & fixen** (Jetson-Segmenter)
   * File: `app.py` Funktion `_split_sentences`
   * Test: `/api/test/segment` mit Original-Transkript

2. **Session-Review verbessern** (False-Negatives reduzieren)
   * File: `backend/app.py` `SESSION_REVIEW_PROMPT`
   * Evtl. zweistufiger Check: erst Patient-Count, dann Felder

3. **Phase-B-Plan starten** (Confidence-Badges pro Feld)
   * Siehe `docs/messe-hardening-plan.md` Abschnitt B1
   * 2h Aufwand geschätzt

4. **Export-Layout verfeinern** (falls Zeit)
   * PDF: aktuell basic reportlab-Layout, Messe-tauglich?
   * DOCX: Header mit SAFIR-Logo + Datum

---

## Git-Ops beim Fortsetzen

```bash
cd C:\Users\the_s\Documents\SAFIR
git pull origin main
git status   # sollte clean sein
git log --oneline -5
```

Bei Problemen mit Push (weil anderer Account):
```bash
git config user.email "deine@firmen-email"
git config user.name "Dein Name"
# oder global:
git config --global user.email "..."
```

Co-Author-Trailer in Commits: war bisher
`Claude Sonnet 4.5` — kann mit neuem Account auch so bleiben oder
auf das neue Claude-Modell geändert werden.

---

*Ende Session-Handover. Viel Erfolg im neuen Account! Bei
Unklarheiten: `CLAUDE.md` und `docs/PROGRESS.md` lesen.*
