# SAFIR auf SINA-Workstation — Live-Deployment

> **Erstellt:** 04.05.2026 von Claude Code (Sandbox-Session, Windows 11 + PowerShell).
>
> Dieses Dokument beschreibt was an einer **SINA-Workstation** als
> zweite Leitstelle eingerichtet wurde. Es ergaenzt
> [`SINA-SETUP.md`](SINA-SETUP.md) (das die Schritte vorab listet) um den
> tatsaechlichen Live-Stand inkl. SSH-Anbindung, Bug-Fixes und der
> Konflikt-Aufloesung gegenueber den parallel auf MacBook entstandenen
> Aenderungen.
>
> Zielgruppe: andere Claude-Code-Sessions (Jetson, MacBook), die wissen
> muessen was die SINA jetzt ist und wie sie damit reden.

---

## TL;DR — SINA ist jetzt eine vollwertige Leitstelle im Mesh

| Eigenschaft | Wert |
|---|---|
| Tailscale-Hostname | `desktop-45t6p3p` |
| Tailscale-IP | `100.95.246.25` |
| HTTPS-URL (LE-Cert) | `https://desktop-45t6p3p.tail0fe60f.ts.net/` |
| HTTP (Diagnose) | `http://127.0.0.1:8080` |
| Rolle | `role1` — Rettungsstation Bonn |
| Code-Stand | parallel zu `origin/main` (incl. Bug-Fix `starlette<1.0`) |
| LLM | keine Ollama-Instanz (schlanke Variante, kein KI-Review) |
| RFID-Reader | HID Omnikey 5022 (USB), `pyscard` installiert |
| Auto-Start | Task Scheduler bei User-Login (`SAFIR-SINA-Backend`) |
| Desktop-Shortcuts | `start-safir.bat` / `stop-safir.bat` |
| SSH-Server | OpenSSH (Windows-Capability), Port 22, Default-Shell PowerShell |
| Jetson → SINA | Pubkey-Auth, Alias `ssh sina` auf Jetson |
| Surface (alt) | bleibt im Tailnet; **Jetson pusht aber nicht mehr dorthin** |

---

## 1. Hardware/OS

- Windows 11
- User: `Rettung` (lokaler Admin)
- Python 3.12.10 via `winget install Python.Python.3.12`
- venv: `C:\Users\Rettung\Documents\SAFIR\.venv`
- Repo-Pfad: `C:\Users\Rettung\Documents\SAFIR`

## 2. Backend-Stack

Schlanke Variante ohne Ollama/Whisper/Vosk — nur das FastAPI-Backend
fuer Lagekarte, Patient-Sync, Export, RFID-Empfang via Omnikey.

**Dependencies:** [`backend/requirements-sina.txt`](../backend/requirements-sina.txt) (bereits gepatched, siehe Bug-Fix unten)

```
fastapi==0.135.1
starlette<1.0          # Bug-Fix: 1.0 hat breaking changes in TemplateResponse
uvicorn==0.41.0
httpx==0.28.1
Jinja2==3.1.6
numpy==2.2.6
psutil==7.2.2
python-docx==1.2.0
reportlab>=4.0.0
websockets==16.0
pyscard>=2.0           # PC/SC fuer Omnikey-Reader (Wheels fuer Windows)
```

### Bug-Fix: `starlette<1.0`

Beim ersten Start lief `/api/status` durch (200 OK), aber `/` warf 500
mit `TypeError: unhashable type: 'dict'` aus
`jinja2.environment._load_template`. Ursache: pip hatte automatisch
`starlette==1.0.0` mitgezogen (FastAPI 0.135.1 hat keine Obergrenze).
Starlette 1.0 hat die `TemplateResponse`-Signatur breaking-change-maessig
geaendert (erster Parameter ist jetzt `request` statt `name`). Der
SAFIR-Code nutzt aber ueberall noch das alte Pattern
`templates.TemplateResponse("index.html", {"request": request, "config": ...})`.

Fix: `pip install "starlette<1.0"` — Pin steht in `requirements-sina.txt`.

### Start/Stop

- **Manuell**: Doppelklick auf Desktop-Shortcuts `start-safir.bat`,
  `stop-safir.bat` (oeffnen Browser auf HTTPS-URL).
- **Auto-Start**: Task Scheduler-Eintrag `SAFIR-SINA-Backend`, Trigger
  `At log on`, Action: `pythonw.exe -m uvicorn app:app ...` (kein
  Konsolenfenster).
- **Repo-Skript**: [`start-sina.cmd`](../start-sina.cmd) im Repo-Root —
  beide .bat-Wrapper rufen letztlich diesen Starter, der stdout/stderr
  in `logs\backend.log` umleitet.

## 3. Tailscale Serve (HTTPS im Mesh)

```powershell
tailscale serve --bg --https=443 http://localhost:8080
```

Erreichbar fuer alle Tailnet-Mitglieder unter
`https://desktop-45t6p3p.tail0fe60f.ts.net/` mit echtem Let's-Encrypt-Cert.

## 4. Jetson auf SINA umstellen (`backend.url`)

Auf dem Jetson ist `backend.url` von `http://100.101.80.64:8080`
(Surface) auf `http://100.95.246.25:8080` (SINA) gesetzt:

```bash
# Datei: /home/jetson/cgi-afcea-san/config.json (Zeile ~239)
"backend": { "url": "http://100.95.246.25:8080", ... }
```

Backup als `/home/jetson/cgi-afcea-san/config.json.bak.before-sina`
gesichert (Surface-Wert wiederherstellbar).

Nach `sudo systemctl restart safir.service` zeigt der Jetson-Log:

```
[BACKEND-WS] Verbinde zu ws://100.95.246.25:8080/ws...
[BACKEND-WS] Verbunden.
POST http://100.95.246.25:8080/api/heartbeat "HTTP/1.1 200 OK"
```

Surface (`ai-station`, 100.101.80.64) bleibt **physisch im Tailnet**,
ist aber nicht mehr im Datenfluss.

## 5. Operator-Karte / Lock-Verhalten

`backend/config.json` enthielt initial den `OP2 / Jaimy Reuter / 6C472E06`-
Eintrag. Auf der SINA wurde das geleert (Open Mode), damit der User eine
neue Karte registrieren konnte. Anschliessend wurde via UI eine Karte
mit derselben UID `6C472E06` als `SINA1 / Sina Workstation / arzt`
registriert — der Lock ist wieder aktiv.

> **Hinweis fuer Jetson/MacBook-Claude**: `backend/config.json` ist
> SINA-spezifisch (Identity + Operator-Karten) und wird **nicht** im
> Repo committed. Lokale Werte koennen vom committeten Stand abweichen.

## 6. SSH-Server auf SINA (Jetson kann remote arbeiten)

OpenSSH Server als Windows-Capability installiert, Default-Shell
PowerShell. Jetson kann sich passwortlos anmelden:

```bash
# Vom Jetson:
ssh sina                                      # interaktive PowerShell
ssh sina "cd Documents\SAFIR; git pull"       # Code-Sync
scp datei sina:Documents/SAFIR/...            # File-Upload
```

### Setup-Skripte (committed im Repo)

- [`scripts/setup-ssh-server.ps1`](../scripts/setup-ssh-server.ps1) —
  installiert OpenSSH-Capability, startet `sshd` + `ssh-agent`, legt
  Firewall-Regel an, setzt DefaultShell auf PowerShell. Muss als
  Administrator ausgefuehrt werden.

- [`scripts/add-jetson-ssh-key.ps1`](../scripts/add-jetson-ssh-key.ps1) —
  legt einen Pubkey in `C:\ProgramData\ssh\administrators_authorized_keys`
  ab und setzt die strikte ACL (`SYSTEM` + `Administrators`,
  no inheritance). Pubkey kommt als Parameter oder via stdin-Pipe.

### Wichtig: Admin-User brauchen `administrators_authorized_keys`

Windows-OpenSSH hat in `sshd_config` einen Match-Block, der fuer
Mitglieder der lokalen `Administrators`-Gruppe **ausschliesslich**
`C:\ProgramData\ssh\administrators_authorized_keys` als
`AuthorizedKeysFile` verwendet — nicht das User-eigene
`~/.ssh/authorized_keys`. Symptom bei falscher Ablage:
`Permission denied (publickey,password,keyboard-interactive)`.

ACL-Anforderung: nur `NT AUTHORITY\SYSTEM` und
`BUILTIN\Administrators` mit FullControl, keine Inheritance.

### Jetson `~/.ssh/config`

```
Host sina
    HostName desktop-45t6p3p
    User Rettung
```

## 7. Code-Stand & Konflikt-Aufloesung

Beim heutigen `git pull origin main` kollidierte
`backend/config.json` mit lokalen Aenderungen. **Lokal aufgeloest**
zugunsten der vom User in der Live-Session bestaetigten Werte
(Role 1 / Rettungsstation Bonn / `sina-rettungsstation`):

| Feld | Lokaler Live-Stand | Macbook-Commit `5cb0824` |
|---|---|---|
| `device_id` | `sina-rettungsstation` | `sina-01` |
| `unit_name` | `Rettungsstation Bonn` | `Rettungsstation West` |
| `role` | `role1` | `role2` |
| `role_label` | `Rettungsstation (Role 1)` | `OP Zentrum (Role 2)` |
| `system_name` | `SINA Workstation` (uebernommen) | `SINA Workstation` |

Weitere Macbook-Aenderungen aus diesem Pull wurden komplett uebernommen
(navigation mit lucide-icons, version-schema in `shared/version.py`,
neue `templates/_icons.svg.html`, etc.).

> **Falls die Macbook-Werte (Role 2 / OP Zentrum / Rettungsstation West)
> die "richtigen" Default-Werte fuer die Distribution sein sollen**:
> bitte `backend/config.json` im Repo so committen, und die SINA-
> Live-Werte sind dann nur lokales Override.

## 8. Was wurde in DIESEM Commit committed?

Aenderungen die aus diesem Setup-Lauf in das Repo gehen:

- `docs/SINA-DEPLOYMENT.md` — diese Datei
- `start-sina.cmd` — generischer SAFIR-Starter im Repo-Root, mit
  Logging in `logs/backend.log`
- `scripts/setup-ssh-server.ps1` — Admin-Skript fuer OpenSSH-Setup
- `scripts/add-jetson-ssh-key.ps1` — Admin-Skript zum Eintragen eines
  Pubkeys in `administrators_authorized_keys` (Pubkey als Parameter)
- `backend/requirements-sina.txt` — Pin `starlette<1.0`, plus
  optionales `pyscard>=2.0`

**Bewusst NICHT committed** (SINA-spezifisch):
- `backend/config.json` — Identity + Operator-Karten lokal

## 9. Was kann/soll Jetson-Claude tun?

Wenn du dies liest und auf dem Jetson laeufst:

1. **Code-Sync zur SINA fuehren** ist jetzt remote moeglich:
   ```bash
   ssh sina "cd Documents\SAFIR; git pull origin main"
   ssh sina "& 'C:\Users\Rettung\Desktop\stop-safir.bat'; & 'C:\Users\Rettung\Desktop\start-safir.bat'"
   ```

2. **Live-Test der WS-Sync** vom Jetson aus pruefen (sollte schon
   gruen sein; bei Restart-Bedarf):
   ```bash
   sudo journalctl -u safir.service -n 30 | grep BACKEND-WS
   ```

3. **Falls die Role-Wahl (Role 1 vs Role 2) doch geaendert werden soll**:
   bitte mit dem User abstimmen — die SINA wurde live als Role 1
   eingerichtet, das MacBook hatte parallel Role 2 in `backend/config.json`
   committed. Aktuell laeuft die SINA als Role 1.

4. **Sicherheitshinweis**: Der Jetson-Pubkey gibt **Admin-Shell** auf
   die SINA. Wenn der Jetson-Privatkey kompromittiert ist, ist die SINA
   offen. Falls Restriktion gewuenscht: `command="..."`-Prefix in
   `administrators_authorized_keys` einbauen
   (z.B. nur `git pull` zulassen).

## 10. Bekannte offene Punkte

- **`pyscard`** ist installiert; Backend erkennt den Omnikey 5022.
  Falls eine Karte mal nicht erkannt wird, im Log nach
  `safir.omnikey: Omnikey-Scan: UID ...` suchen.
- **Default-Browser**: `start-safir.bat` oeffnet `https://desktop-45t6p3p.tail0fe60f.ts.net/`
  — wenn Tailscale mal down ist, schlaegt das fehl. Dann manuell
  `http://127.0.0.1:8080` aufrufen.
- **Reload-Fenster im Browser**: Wenn die `config.json` live geaendert
  wird (z.B. Operator registriert), muss der Browser-Tab refresht
  werden — der Lock-Status wird beim WS-`init` einmalig gepushed.
- **Surface-Cleanup**: Surface (`ai-station`, 100.101.80.64) ist noch
  im Tailnet. Falls sie ganz raus soll: Tailscale-Admin-Panel oder
  `tailscale logout` auf der Surface selbst.

---

*SAFIR / CGI Deutschland / SINA-Live-Deployment 04.05.2026*
