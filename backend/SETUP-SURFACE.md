# SAFIR Leitstelle — Setup für MS Surface (Role 1)

## Hardware
- Microsoft Surface mit NVIDIA RTX 4060 (8 GB VRAM)
- Windows
- Tailscale installiert, Hostname: `ai-station`, IP: `100.101.80.64`

## 1. Repository klonen

```cmd
git clone https://github.com/Ajintaro/SAFIR.git
cd SAFIR
```

## 2. Python einrichten

Falls Python noch nicht installiert: https://www.python.org/downloads/

```cmd
cd backend
pip install fastapi uvicorn httpx
```

## 3. SAFIR Backend starten

```cmd
python -m uvicorn app:app --host 0.0.0.0 --port 9090
```

> **Port 9090** weil 8080 eventuell durch andere Dienste belegt ist.

Im Browser öffnen: **http://localhost:9090**

Du siehst die taktische Lagekarte mit der Rettungsstation (Bonn).

## 4. Ollama installieren (optional, für KI-Triage-Empfehlung)

Die RTX 4060 hat genug VRAM für ein mittelgroßes LLM.

1. Ollama installieren: https://ollama.com/download/windows
2. Modell laden:
   ```cmd
   ollama pull qwen2.5:7b
   ```
3. Prüfen ob es läuft:
   ```cmd
   curl http://localhost:11434/api/tags
   ```

## 5. Verbindung testen

### Vom Surface aus den Jetson erreichen:
```cmd
curl http://100.126.179.27:8080/api/status
```
→ Sollte JSON mit Jetson-Status zurückgeben.

### Vom Jetson aus das Surface erreichen:
```bash
curl http://100.101.80.64:9090/api/status
```
→ Sollte JSON mit Leitstelle-Status zurückgeben.

## 6. Firewall

Falls die Verbindung nicht klappt — Windows Firewall muss Port 9090 freigeben:

```cmd
netsh advfirewall firewall add rule name="SAFIR Leitstelle" dir=in action=allow protocol=TCP localport=9090
```

Oder in den Windows-Einstellungen: **Firewall → Eingehende Regeln → Neue Regel → Port → TCP 9090 → Zulassen**

## Was passiert wenn alles läuft

1. Jetson (Phase 0) registriert Verwundete per Sprache
2. Sanitäter sagt **"Patient melden"** → Daten werden an `http://100.101.80.64:9090/api/ingest` gesendet
3. **Auf dem Surface erscheint sofort:**
   - Patient im Dashboard (rechtes Panel)
   - BAT-Marker auf der taktischen Karte
   - Triage-Übersicht aktualisiert sich
   - Event im Live-Ticker

## Tailscale-Netzwerk

| Gerät | Hostname | Tailscale-IP | Rolle | Port |
|-------|----------|-------------|-------|------|
| Jetson Orin Nano | `jetson-orin` | 100.126.179.27 | Phase 0 (BAT) | 8080 |
| MS Surface | `ai-station` | 100.101.80.64 | Role 1 (Leitstelle) | 9090 |

## Daten zurücksetzen

```cmd
rmdir /s backend\data
```
Dann Backend neustarten — startet mit leerem Zustand.
