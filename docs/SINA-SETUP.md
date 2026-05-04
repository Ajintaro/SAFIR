# SAFIR auf SINA-Laptop einrichten (Windows 11, ohne LLM)

> **Ziel**: SINA-Laptop wird als zweite Leitstelle ("Rettungsstation") im
> Tailscale-Mesh betrieben. Kein LLM, kein Mikro — empfängt Patientendaten
> vom Jetson-BAT, zeigt Lagekarte, exportiert DOCX/PDF/JSON/XML.
>
> **Footprint**: ~150 MB Python-Dependencies (ohne torch/whisper).
> **Voraussetzung**: Tailscale auf SINA aktiv, im selben Tailnet wie Surface.

---

## Schritt 0 — Vorab-Checks auf SINA

In PowerShell (Windows-Taste → "powershell"):

```powershell
# Welcher Python ist da?
python --version
# Erwartet: Python 3.10 oder neuer

# Falls 'python' nicht gefunden wird:
where python
# Falls leer: Python muss installiert werden (Schritt 1)

# Tailscale-Status?
tailscale status
# Sollte das Tailnet zeigen mit Surface, Jetson und SINA

# Eigener Tailscale-Hostname:
tailscale ip -4
# Diese IP brauchen wir gleich für Jetson-Config
```

**Ergebnis hier merken**: Python-Version, Tailscale-IP der SINA.

---

## Schritt 1 — Python 3.10+ installieren (falls nicht vorhanden)

**Variante A: Microsoft Store** (am einfachsten, keine Admin-Rechte nötig)
- Store öffnen → "Python 3.12" suchen → Installieren

**Variante B: python.org** (offline-Installer)
- Download von Surface (Surface hat bereits Python): C:\Python312\python-3.12.x-amd64.exe
- USB-Stick oder via Tailscale-SCP zu SINA übertragen
- Installer ausführen mit Häkchen "Add Python to PATH"

**Verifizieren**:
```powershell
python --version
pip --version
```

---

## Schritt 2 — SAFIR-Code von Surface holen

### Variante A: Via Tailscale (am einfachsten, falls SSH/SCP zwischen den Geräten erlaubt)

Auf **Surface** (Git-Bash):
```bash
cd /c/Users/the_s/Documents/SAFIR
# Tarball ohne Entwicklungs-Ballast
tar --exclude='.git' --exclude='__pycache__' --exclude='backend/data' \
    --exclude='backend/exports' --exclude='node_modules' \
    -czf /tmp/safir-sina.tar.gz .

# Größe checken — sollte unter 50 MB sein
ls -lh /tmp/safir-sina.tar.gz

# Zu SINA übertragen (Tailscale-Hostname oder IP):
scp /tmp/safir-sina.tar.gz <username>@<sina-tailscale-ip>:C:/safir-sina.tar.gz
```

Auf **SINA** (PowerShell):
```powershell
cd C:\
mkdir SAFIR
cd SAFIR
tar -xzf C:\safir-sina.tar.gz
# Falls 'tar' nicht da ist: 7-Zip nutzen oder den ZIP-Weg unten
```

### Variante B: Via USB-Stick

1. Auf Surface: Repo als ZIP packen
   ```bash
   cd /c/Users/the_s/Documents/SAFIR
   git archive HEAD --format=zip --output=/tmp/safir-sina.zip
   ```
2. ZIP auf USB-Stick kopieren
3. Auf SINA: USB einstecken, ZIP nach `C:\SAFIR\` entpacken (rechtsklick → "Alle extrahieren")

### Variante C: Via HTTP-Server (falls SCP blockiert)

Auf Surface (PowerShell):
```powershell
cd C:\Users\the_s\Documents\SAFIR
python -m http.server 8000
```

Auf SINA (PowerShell):
```powershell
cd C:\SAFIR
# Surface-Tailscale-Name oder IP einsetzen:
Invoke-WebRequest -Uri http://ai-station:8000/safir-sina.tar.gz -OutFile safir.tar.gz
tar -xzf safir.tar.gz
```

---

## Schritt 3 — Python-Environment + Dependencies

In PowerShell, im SAFIR-Verzeichnis:

```powershell
cd C:\SAFIR

# Virtuelle Umgebung anlegen
python -m venv .venv

# Aktivieren (PowerShell-Variante)
.venv\Scripts\Activate.ps1

# Falls Activation-Policy meckert ("Ausführung von Skripts deaktiviert"):
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned

# Schlanke Dependencies installieren (ohne LLM)
pip install -r backend\requirements-sina.txt
```

**Falls kein Internet auf SINA** (typisch bei stark gehärteten Geräten):

Auf Surface vorbereiten:
```powershell
cd C:\Users\the_s\Documents\SAFIR
mkdir wheels-sina
pip download -r backend\requirements-sina.txt -d wheels-sina\
# Plus pip selbst falls SINA gar nichts hat:
pip download pip wheel setuptools -d wheels-sina\
```

`wheels-sina/` Ordner zu SINA kopieren (USB / SCP / HTTP). Auf SINA dann:
```powershell
pip install --no-index --find-links wheels-sina\ -r backend\requirements-sina.txt
```

---

## Schritt 4 — config.json anpassen

Datei: `C:\SAFIR\backend\config.json`

```json
{
    "device_id": "sina-rettungsstation",
    "device_name": "SINA Rettungsstation",
    "unit_name": "Rettungsstation Bonn",
    "role": "role1",
    "ollama": {
        "url": "http://127.0.0.1:11434",
        "model": "gemma4:e4b"
    },
    "rfid": {
        "operators": []
    }
}
```

**Wichtig — kein LLM**: Die `ollama`-Sektion bleibt drin (das Backend prüft nur bei Bedarf), aber da kein Ollama läuft, sind LLM-Features wie `/api/llm/review-session` halt nicht funktional. Alle anderen Endpoints (Patient-Sync, Lagekarte, Export) gehen.

---

## Schritt 5 — Backend starten

Direkt aus dem PowerShell-Fenster:

```powershell
cd C:\SAFIR\backend
..\.venv\Scripts\python.exe -m uvicorn app:app --host 0.0.0.0 --port 8080
```

Oder als Komfort: `start-sina.cmd` im SAFIR-Root anlegen:
```cmd
@echo off
REM SAFIR Surface/SINA Backend Starter (kein --reload, kein State-Verlust)
cd /d "%~dp0backend"
..\.venv\Scripts\python.exe -m uvicorn app:app --host 0.0.0.0 --port 8080
```

Doppelklick → läuft.

**Verifizieren** (anderes PowerShell-Fenster):
```powershell
curl.exe http://localhost:8080/api/status
# Sollte JSON zurückgeben mit device, version, etc.
```

---

## Schritt 6 — Tailscale Serve für HTTPS (optional, empfohlen)

Damit Browser einen "grünen Schloss"-Zugang hat:

```powershell
tailscale serve --bg --https=443 http://localhost:8080
```

Browser-URL für Demo-Besucher: `https://<sina-tailnet-name>.tail0fe60f.ts.net/`

---

## Schritt 7 — Jetson umstellen damit er an SINA pusht statt an Surface

Auf **Jetson** (via SSH von Surface):

```bash
ssh jetson@jetson-orin
sudo nano /home/jetson/cgi-afcea-san/config.json
```

`backend.url` ändern auf SINA:
```json
"backend": {
    "url": "http://<sina-tailscale-ip>:8080"
}
```

Service neu starten:
```bash
sudo systemctl restart safir
```

Ab jetzt landen Patientendaten vom Jetson auf SINA.

---

## Schritt 8 — Verifikation

1. **SINA-UI** im Browser öffnen: `http://localhost:8080` oder Tailscale-HTTPS
2. Lagekarte sollte erscheinen
3. **Auf Jetson** einen Test-Patient via Demo-Szenario anlegen → "Melden" drücken
4. **SINA**: Patient sollte in der Lagekarte + Patientenliste auftauchen

---

## Was läuft NICHT auf SINA (weil kein LLM)

- ❌ KI-Review der Jetson-Extraktion (Session-Review-Feature)
- ❌ KI-gestützte Patient-Erweiterung
- ✅ Alles andere: Lagekarte, Patient-Sync, Export DOCX/PDF/JSON/XML, Triage,
     RFID-Empfang via Omnikey, Tailscale-HTTPS

Falls du später doch ein LLM auf SINA willst:
- Ollama für Windows: `ollama.com/download/windows`
- `ollama pull gemma4:e4b` (~9.6 GB Download)
- Sektion `"ollama.url"` in config.json bleibt wie sie ist
- LLM-Review-Endpoint funktioniert dann automatisch

---

## Häufige Stolperfallen

| Problem | Lösung |
|---|---|
| `python` nicht erkannt | PATH-Eintrag fehlt → in Systemumgebungsvariablen `C:\Python312` und `C:\Python312\Scripts` eintragen |
| Activation-Policy blockt `Activate.ps1` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` einmal ausführen |
| Firewall blockt Port 8080 | Windows-Firewall: Eingehende Regel für Python-Backend auf Port 8080 zulassen |
| Tailscale-IP der SINA stimmt nicht überein mit Jetson-Config | `tailscale ip -4` auf SINA, Wert in Jetson `config.json:backend.url` eintragen |
| pip schlägt mit SSL-Fehlern fehl | Möglicherweise eigene CA — `pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r ...` |
| `ImportError: No module named 'docx'` | python-docx nicht installiert → `pip install python-docx` (achte auf den **Bindestrich**, das Paket heißt `python-docx`, der Import ist `from docx import ...`) |
| Backend startet, aber UI kommt nicht | Pfad-Issue — sicherstellen dass `templates/` und `static/` parallel zu `backend/` liegen |

---

*SAFIR · CGI Deutschland · AFCEA 2026 · SINA-Setup-Guide*
