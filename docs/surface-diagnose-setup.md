# Surface als SAFIR-Diagnose-Gerät einrichten

Dieses Dokument beschreibt, wie das Windows-11-Surface (`ai-station` im Tailnet) als SSH-Client für den Jetson Orin Nano eingerichtet wird, damit Claude Code Desktop vom Surface aus direkt auf dem Jetson arbeiten kann. Zweck: Diagnose- und Debug-Zugang auf der AFCEA-Messe ohne Abhängigkeit vom MacBook.

---

## Ausgangslage (Stand 2026-04-14)

Bereits vorhanden und funktionsfähig:

- Jetson erreichbar als `jetson-orin` im Tailnet (Tailscale IP `100.126.179.27`)
- Surface als `ai-station` im Tailnet (Tailscale IP `100.101.80.64`)
- SSH-Daemon auf Jetson aktiv (`systemctl is-active ssh` → `active`)
- `claude` CLI auf Jetson installiert: `/home/jetson/.nvm/versions/node/v20.20.1/bin/claude`, Version `2.1.107`
- Claude Code Desktop bereits auf Surface installiert

Noch nicht vorhanden:

- `~/.ssh/authorized_keys` auf dem Jetson existiert nicht — muss angelegt werden
- SSH-Key auf Surface muss generiert werden (falls noch nicht vorhanden)
- SSH-Connection in Claude Code Desktop noch nicht konfiguriert

---

## Schritt 1 — SSH-Key auf dem Surface erzeugen

**Auf dem Surface** in Windows Terminal (PowerShell) ausführen:

```powershell
ssh-keygen -t ed25519 -C "surface-ai-station"
```

- Bei der Pfad-Abfrage einfach Enter drücken → Default-Pfad `C:\Users\<DeinUser>\.ssh\id_ed25519`
- Passphrase leer lassen. Begründung: Claude Code Desktop unterstützt keinen `ssh-agent` (GitHub Issue #46273). Eine Passphrase würde bei jeder Verbindung abgefragt werden.

Falls bereits ein Key existiert, einfach den vorhandenen verwenden.

## Schritt 2 — Public Key zum Jetson transportieren

Auf dem Surface:

```powershell
Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub | Set-Clipboard
```

Damit ist der Public Key in der Zwischenablage. Dann zwei Möglichkeiten, um ihn auf dem Jetson in `~/.ssh/authorized_keys` einzutragen:

**Variante A — über die aktuell laufende Claude-Code-Session auf dem Jetson**
Einfach den kopierten Key in die Session pasten und sagen: "Trag diesen Key in `~/.ssh/authorized_keys` ein". Claude legt die Datei mit korrekten Permissions (700 für `~/.ssh`, 600 für `authorized_keys`) an.

**Variante B — manuell vom MacBook aus per SSH**

```bash
ssh jetson@jetson-orin
mkdir -p ~/.ssh && chmod 700 ~/.ssh
nano ~/.ssh/authorized_keys
# Key einfügen (eine Zeile), Strg+O, Enter, Strg+X
chmod 600 ~/.ssh/authorized_keys
```

## Schritt 3 — SSH-Connection in Claude Code Desktop konfigurieren

Auf dem Surface in Claude Code Desktop den "Add SSH connection"-Dialog öffnen und folgende Werte eintragen:

| Feld | Wert | Hinweis |
|---|---|---|
| Host | `jetson-orin` | Tailscale-Hostname funktioniert direkt |
| User | `jetson` | |
| Port | `22` | **Explizit eintragen** — Port-Feld leer hat Bug #26809 (ignoriert `~/.ssh/config`) |
| Identity File | leer, oder `C:/Users/<DeinUser>/.ssh/id_ed25519` | Forward-Slashes, keine Backslashes |

**Wichtig:**

- Nur Private-Key-Datei-Auth wird unterstützt. Kein `ssh-agent`, kein Passwort, kein YubiKey.
- Beim ersten Verbindungsaufbau erscheint eine Host-Key-Warnung — einmal akzeptieren. Bei Problemen manuell:
  ```powershell
  ssh-keyscan jetson-orin >> $env:USERPROFILE\.ssh\known_hosts
  ```
- Der Desktop-Client pusht **nichts** auf den Host — `claude` CLI muss bereits auf dem Jetson installiert sein (ist es, siehe oben).

## Schritt 4 — Verbindung testen

Ohne Messe-Netz, noch am Home-WLAN:

1. Claude Code Desktop → neue SSH-Session auf `jetson-orin` starten
2. Prüfen: `pwd` zeigt `/home/jetson`, `whoami` zeigt `jetson`
3. Prüfen: `ls /home/jetson/cgi-afcea-san` zeigt den Repo-Inhalt
4. **Wichtig:** Diese Datei (`docs/surface-diagnose-setup.md`) einmal in der Desktop-UI öffnen — bestätigt dass Read/File-Browser funktionieren

## Schritt 5 — Messe-Realistik-Test (PFLICHT vor der AFCEA)

Vor der Messe muss einmal komplett getestet werden ohne Heim-WLAN-Fallback:

1. Surface vom Heim-WLAN trennen
2. Mobile Hotspot als einzige Verbindung aktivieren (am besten der Hotspot den du auch auf der Messe nutzen wirst)
3. Jetson ebenfalls auf denselben Hotspot oder autarkes Messe-Setup
4. Tailscale auf beiden Geräten verifizieren: `tailscale status` auf Jetson muss `ai-station` als active zeigen, und umgekehrt
5. Claude Code Desktop → SSH-Session aufbauen, `claude` starten, einen trivialen Test-Befehl ausführen (z.B. `journalctl -u safir --lines 5`)
6. Abschalt-Test: Surface-Display zuklappen/öffnen, prüfen dass die SSH-Session persistent bleibt (bei Bedarf `tmux` vorschalten)

Wenn dieser Test einmal grün war, ist das Surface messe-tauglich.

---

## Geplante Schritte NACH erfolgreicher Surface-Einrichtung

Diese Schritte werden vom Surface aus durchgeführt, sobald Schritt 1-5 abgeschlossen sind:

### Schritt A — Jetson in Headless-Mode überführen

Ziel: ~510 MB RAM freigeben für Qwen-Permanent-Load. Entspricht Task #4 aus AFCEA-Projektplan.

```bash
sudo systemctl set-default multi-user.target
# NICHT im laufenden Betrieb `systemctl isolate multi-user.target` ausführen
# — das killt GNOME sofort und damit aktive Sessions.
# Stattdessen beim nächsten geplanten Reboot wirksam werden lassen.
sudo reboot
```

Nach dem Reboot bootet der Jetson in Text-Mode. Claude Code Desktop verbindet sich weiter wie gewohnt über SSH.

Verifikation nach Reboot:
- `systemctl get-default` → `multi-user.target`
- `free -h` → `used` deutlich unter 3 GB (vorher ~3.4 GB)
- `ps -eo pid,rss,comm --sort=-rss | head` → keine `gnome-shell`, `Xorg`, `gsd-*`, `gjs`, `ibus-extension`, `notify-osd`
- OLED läuft weiter (systemd-Services sind unabhängig von `graphical.target`)

Rückweg jederzeit möglich:
```bash
sudo systemctl set-default graphical.target
sudo reboot
```

### Schritt B — Qwen permanent im VRAM halten

Ziel: Whisper und Qwen gleichzeitig geladen, kein GPU-Swap mehr.

Vorbedingung: Schritt A erfolgreich, `free -h` zeigt mindestens ~4.3 GB available.

Änderungen in `app.py`:
- `_unload_ollama_model()` Aufrufe um Zeile 1028 und 2483 entfernen
- In `_call_ollama()` `"keep_alive": -1` im Request-Body setzen
- OLED-Readiness-Check kann weiter `/api/tags` nutzen (funktioniert auch mit Parallel-Betrieb korrekt) oder optional auf `/api/ps` umgestellt werden, damit der OLED direkt zeigt dass Qwen im VRAM ist

Änderungen in `scripts/safir-start.sh`:
- Preload-and-Unload-Sequenz anpassen: Preload bleibt, das darauffolgende Unload entfernen
- Sicherstellen dass Ollama VOR Whisper gestartet wird (GPU-Fragmentation-Regel aus AFCEA-Memory)

### Schritt C — Stress-Test

Vor dem endgültigen Commit:

1. SAFIR starten mit neuer Konfiguration
2. `curl -s http://localhost:11434/api/ps` — Qwen muss `qwen2.5:1.5b` zeigen, auch ohne laufende Analyse
3. `nvidia-smi` oder `tegrastats` während einer Aufnahme beobachten — VRAM darf nicht ins Swap fallen
4. **5 Aufnahme-und-Analyse-Zyklen hintereinander** ohne Pause durchlaufen
5. Nach jedem Zyklus `free -h` und `dmesg | tail -20` prüfen — kein OOM, kein CUDA-Fehler
6. Zombie-Check: `pgrep -fa whisper-server` — es darf nur genau ein Prozess pro aktiver SAFIR-Instanz laufen

Wenn einer dieser Tests fehlschlägt: Revert auf GPU-Swap, Fehlersuche, NICHT als "instabil aber wird schon gehen" durchwinken.

### Schritt D — Memory und Dokumentation aktualisieren

Nach erfolgreichem Stress-Test:

- `feedback_qwen_gpu_swap_final.md` in Claude-Memory überschreiben mit neuer Regel "Parallel-Betrieb OK, gilt nur mit `multi-user.target` Headless-Mode"
- `project_afcea_san.md` Task #4 als erledigt markieren (headless-boot)
- Diesen Setup-Guide als "Schritte A-D durchgeführt am YYYY-MM-DD" ergänzen
- Commit mit aussagekräftiger Message, Push auf GitHub

---

## Wichtige offene Punkte am Tag der Surface-Einrichtung

- Zombie-Whisper-Server-Bug (siehe `project_safir_session_2026_04_13.md`): Wenn beim Testen `kill -9` nötig wird, `pkill -9 -f whisper-server` mit ausführen, sonst bleiben Kinder als RAM-Leaks (~1 GB pro Zombie) zurück
- MIFARE-Write ist weiterhin ungetestet gegen echte Hardware — wenn beim Debuggen Zeit übrig ist, gute Gelegenheit das nachzuholen
- Reboot-Test des OLED-Boot/Shutdown-Splashes ist noch nicht bestätigt — bei Reboot für Headless-Umschaltung einfach mit beobachten

---

## Referenzen

- AFCEA-Projektkontext: Claude-Memory `project_afcea_san.md`
- Hardware-Session vom 2026-04-13: Claude-Memory `project_safir_session_2026_04_13.md`
- GPU-Swap-Historie: Claude-Memory `feedback_qwen_gpu_swap_final.md`
- Claude Code Desktop SSH Port-Bug: https://github.com/anthropics/claude-code/issues/26809
- Claude Code Desktop ssh-agent Feature Request: https://github.com/anthropics/claude-code/issues/46273
- Tailscale Windows Download: https://tailscale.com/download/windows
