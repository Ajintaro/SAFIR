# SAFIR — Disaster-Recovery-Plan für die AFCEA-Messe

> **Für Demo-Tag.** Wenn während der Demo etwas schiefgeht — Service
> crasht, Jetson reagiert nicht mehr, RFID liest nicht, usw. — diese
> Anleitung gibt Schritt-für-Schritt-Rezepte. Darf vom User am Messe-
> Stand gelesen werden ohne Claude.

---

## 1. Vor der Messe — Backup-Snapshot anlegen

### 1.1 Git-Tag setzen

Auf dem Surface (`C:\Users\the_s\Documents\SAFIR`):

```bash
git tag -a pre-demo -m "Snapshot vor AFCEA-Messe 2026 — Phase 9.4 Backup"
git push origin pre-demo
```

Damit ist der aktuelle Stand als Tag `pre-demo` im GitHub-Repo
versioniert. Rollback bei Problemen:

```bash
git checkout pre-demo
```

### 1.2 USB-Stick mit kompletter Repo-Kopie

Auf dem Surface:

```powershell
# Angenommen E: ist der USB-Stick
robocopy C:\Users\the_s\Documents\SAFIR E:\SAFIR-Backup /MIR /XD .git node_modules __pycache__
cd C:\Users\the_s\Documents\SAFIR
git bundle create E:\SAFIR-Backup\safir-repo.bundle --all
```

Zusätzlich auf den USB-Stick:
- `scripts/setup-multi-audio.sh` (Audio-Setup)
- `docs/security-architecture.md` (Talking Points als Fallback-Ausdruck)
- `docs/nine-liner-template.md` (Laminiert als A5 mitnehmen)

### 1.3 Jetson-Backup

SSH auf den Jetson:

```bash
ssh jetson@jetson-orin
cd /home/jetson/cgi-afcea-san
git tag -a pre-demo-jetson -m "Jetson-Snapshot vor AFCEA 2026"
git push origin pre-demo-jetson
# Zusätzlich lokale Kopie:
sudo tar czf /home/jetson/safir-backup-$(date +%F).tar.gz --exclude='.git' .
```

---

## 2. Während der Messe — Häufige Probleme + Rezepte

### Problem 1: Service antwortet nicht auf HTTP (curl timeout)

**Symptom**: `http://jetson-orin:8080/` lädt nicht, `curl -s http://localhost:8080/api/status` hängt.

**Diagnose am Jetson**:
```bash
ssh jetson@jetson-orin
sudo systemctl status safir
# Erwartete Ausgabe: "active (running)"
```

**Rezept**:
```bash
sudo systemctl restart safir
# Warten ca. 30 s auf Modell-Load
curl -s http://localhost:8080/api/status | python3 -m json.tool | head
```

Wenn `whisper_loaded: true` → OK. Dauer bis zum OK: ~25 s.

### Problem 2: Aufnahme startet nicht / kein Audio

**Symptom**: Taster gedrückt, aber keine TTS-Ansage, LED nicht rot.

**Diagnose**:
```bash
ssh jetson@jetson-orin
sudo journalctl -u safir -n 50 --no-pager | grep -iE "audio|mikro|stream|cudaMalloc"
```

**Rezept A** (Audio-Device weg):
```bash
# Alle USB-Audio-Devices anzeigen
python3 /home/jetson/cgi-afcea-san/scripts/list_audio_devices.py
# Service neu starten lädt die Device-Liste
sudo systemctl restart safir
```

**Rezept B** (Stream hängt):
```bash
# Stream-Reset via HTTP
curl -s -X POST http://localhost:8080/api/audio/refresh
# Wenn das nicht hilft:
sudo systemctl restart safir
```

### Problem 3: LLM hallusiniert / Segmenter bricht Patienten falsch auf

**Symptom**: 1 Patient diktiert → 3 Patienten im Dashboard. Oder umgekehrt.

**Rezept**:
- **Daten-Reset** via Dashboard → Einstellungen → System → "Alle Daten löschen"
- Oder CLI: `curl -X POST http://localhost:8080/api/data/reset`
- Demo neu starten mit klareren Phrasen:
  - Zwischen Patienten pausieren
  - Satz "Als nächstes haben wir..." explizit sprechen
  - Bei Einzelpatient: Nur 1 Satz-Thema, keine parallelen Details

### Problem 4: RFID-Karte schreibt nicht

**Symptom**: OLED zeigt „Karte auflegen", Karte liegt drauf, aber kein Erfolg.

**Diagnose**:
```bash
ssh jetson@jetson-orin
sudo /home/jetson/cgi-afcea-san/venv/bin/python /home/jetson/cgi-afcea-san/scripts/rfid_write_diag.py
# Führt einen Test-Write mit Verify-Read aus, mit TTS-Prompts
```

**Rezept**:
1. Karte fest auf Reader drücken (MIFARE Classic, ca. 1-2 Sekunden)
2. Reader-Abstand zum Metall prüfen (kann Antenne stören)
3. Wenn mehrfach fehlschlägt: Service neu starten
   ```bash
   sudo systemctl restart safir
   ```

### Problem 5: Surface-Lagekarte leer / Live-Sync fehlt

**Symptom**: Jetson hat Patienten, Surface zeigt 0.

**Diagnose am Surface**:
```powershell
# Prüfen ob Surface-Backend läuft
curl http://localhost:8080/api/status
# Prüfen ob Tailscale-Verbindung steht
ping 100.126.179.27   # Jetson-IP
```

**Rezept A** (Surface neu starten):
```powershell
# Surface-Backend im Terminal oder via Task Manager neu starten
cd C:\Users\the_s\Documents\SAFIR\backend
python app.py
```

**Rezept B** (Jetson pullt nicht):
```bash
ssh jetson@jetson-orin
curl -s http://localhost:8080/api/status | grep backend_reachable
# Wenn false: Tailscale prüfen
tailscale status
# Und Backend-URL in config.json prüfen
grep -A 2 backend /home/jetson/cgi-afcea-san/config.json
```

**Rezept C** (manueller Sync auslösen):
Auf dem Jetson-Dashboard: Sprachbefehl „Patienten melden" oder Button
im OLED-Menü. Oder via API:
```bash
curl -X POST http://localhost:8080/api/sync/all
```

### Problem 6: OLED-Display friert

**Symptom**: OLED zeigt alte Info, reagiert nicht auf Taster.

**Rezept**:
```bash
ssh jetson@jetson-orin
sudo systemctl restart safir
# Falls I2C-Bus tot:
sudo i2cdetect -y 7
# Sollte Device 3c zeigen (SSD1306)
```

### Problem 7: Komplett-Ausfall — nichts geht mehr

**Rollback zum letzten stabilen Stand**:
```bash
ssh jetson@jetson-orin
cd /home/jetson/cgi-afcea-san
git fetch origin
git checkout pre-demo-jetson
sudo systemctl restart safir
```

Auf dem Surface:
```powershell
cd C:\Users\the_s\Documents\SAFIR
git checkout pre-demo
cd backend
python app.py
```

---

## 3. Health-Check vor jedem Demo-Durchlauf

### 3.1 Quick-Check (30 Sekunden)

Am Jetson:
```bash
ssh jetson@jetson-orin
curl -s http://localhost:8080/api/status | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f\"whisper: {d['system']['whisper_loaded']}\")
print(f\"ollama:  {[m['name'] for m in d['system']['ollama_models']]}\")
print(f\"ram:     {d['system']['ram_percent']}%\")
print(f\"backend: {d['backend_reachable']}\")
"
```

**Alles OK wenn**:
- whisper: True
- ollama: ['qwen2.5:1.5b']
- ram < 70%
- backend: True

### 3.2 E2E-Test (30 Sekunden)

```bash
cd /home/jetson/cgi-afcea-san
python3 scripts/e2e_demo_run.py
```

**Alles OK wenn**: „Ergebnis: 11/11 Tests PASS"

### 3.3 Stress-Test (3 Minuten, nur bei Verdacht)

```bash
cd /home/jetson/cgi-afcea-san
python3 scripts/stress_test.py --iterations 5
```

**Alles OK wenn**: „10/10 Iterations PASS" und RAM-Drift < 5%

---

## 4. Notfallnummern / Fallback-Strategien

### Wenn der Jetson komplett ausfällt

**Fallback**: Surface alleine zeigen (Lagekarte + Export-Funktionen).
Erklären: „Das ist die Leitstellen-Ansicht. In der Vollausstattung
spricht der Sanitäter ins Jetson-Feldgerät, hier eingespeiste Daten
erscheinen automatisch."

Vorbereitete Testdaten injecten:
```powershell
curl -X POST http://localhost:8080/api/data/test-generate
```

### Wenn beide Geräte ausfallen

**Fallback**: Ausgedruckte Screenshots + das laminierte 9-Liner-
Template verwenden. Persönlich durch die Features navigieren.

Wichtige Ausdrucke auf USB-Stick:
- 9-Liner-Template (`docs/nine-liner-template.md` als PDF)
- Security-Diagramm (`docs/security-architecture.md` als PDF)
- Screenshots der wichtigsten Pages (Lagekarte, Patient-Detail, Vision-Page)

---

## 5. Demo-Skript (Talking-Points-Reihenfolge)

Empfohlene Reihenfolge für 5-10-min-Demo:

1. **Hero-Einstieg** (30s): Home-Page zeigen, Rettungskette erklären
   („Phase 0 → Role 1-4, Goldene Stunde")
2. **Phase 0 am Jetson** (2 min):
   - Aufnahme starten mit Taster B lang
   - Multi-Patient-Diktat (Schmidt + Meyer)
   - Whisper-Transkript erscheint
   - Analyse starten → 2 Patienten angelegt
3. **Live-Sync zur Surface-Leitstelle** (30s):
   - Surface-Lagekarte zeigen → 2 Patienten-Marker erscheinen
   - Triage in Role 1 setzen → Farb-Update
4. **9-Liner-Demo** (2 min):
   - Voice-Command "9-Liner" oder Button
   - MEDEVAC-Template diktieren
   - 9/9 Felder auto-extrahiert
5. **Export** (1 min):
   - Einstellungen → Export als PDF → öffnen
6. **Sicherheit** (1 min):
   - Einstellungen → Sicherheit → ASCII-Diagramm + Talking Points
   - WireGuard + Tailscale erklären
7. **Vision** (1 min):
   - Vision-Page → 6 Use-Cases (Feuerwehr, Polizei, THW, ...)
   - „Dieselbe Architektur, andere Hardware-Skins"

---

## 6. Nach der Messe

### Daten sichern

```bash
# Vom Jetson runter:
ssh jetson@jetson-orin "cd /home/jetson/cgi-afcea-san && curl -X GET http://localhost:8080/api/export/json/all > /tmp/afcea-snapshot.json"
scp jetson@jetson-orin:/tmp/afcea-snapshot.json C:\Users\the_s\Documents\SAFIR\docs\
```

### Service-Logs archivieren

```bash
ssh jetson@jetson-orin "sudo journalctl -u safir --since '1 day ago' --no-pager > /tmp/afcea-jetson.log"
scp jetson@jetson-orin:/tmp/afcea-jetson.log C:\Users\the_s\Documents\SAFIR\docs\
```

### Retrospektive

Markiere `docs/PROGRESS.md` mit einem neuen Abschnitt „Nach AFCEA
2026" und halte fest:
- Was hat geklappt?
- Was hat nicht geklappt?
- Welche Feature-Requests kamen von Messebesuchern?
- Welche Bugs wurden vor Ort entdeckt?

Das wird die Input für V2-Roadmap.
