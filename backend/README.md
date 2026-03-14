# SAFIR Leitstelle — Backend Setup

## Schnellstart (macOS / Windows / Linux)

### 1. Repository klonen

```bash
git clone git@github.com:Ajintaro/SAFIR.git
cd SAFIR
```

### 2. Python-Dependencies installieren

```bash
pip3 install fastapi uvicorn httpx
```

Mehr braucht das Backend nicht — kein Whisper, kein Ollama, keine GPU.

### 3. Backend starten

```bash
cd backend
python3 -m uvicorn app:app --host 0.0.0.0 --port 8080
```

### 4. Browser öffnen

```
http://localhost:8080
```

Du siehst die taktische Lagekarte mit der Rettungsstation (Bonn).

---

## Tailscale (für Demo über verschiedene Netzwerke)

Alle Geräte müssen im selben Tailscale-Netzwerk sein:

1. Tailscale installieren: https://tailscale.com/download
2. Einloggen mit dem gemeinsamen Account
3. `tailscale ip -4` zeigt deine Tailscale-IP

### Geräte-Übersicht

| Gerät | Rolle | Tailscale-IP | Port |
|-------|-------|-------------|------|
| Jetson Orin Nano | Phase 0 (BAT) | 100.126.179.27 | 8080 |
| MacBook / Laptop | Role 1 (Leitstelle) | `tailscale ip -4` | 8080 |

### Jetson-Dashboard aufrufen (vom Laptop aus)

```
http://100.126.179.27:8080
```

### Backend-URL auf dem Jetson setzen

Im Jetson-Browser unter `http://localhost:8080` → Einstellungen → Gerät & Netzwerk:
- **Backend-URL**: `http://<LAPTOP_TAILSCALE_IP>:8080`

Oder per API:
```bash
curl -X POST http://100.126.179.27:8080/api/config \
  -H 'Content-Type: application/json' \
  -d '{"backend":{"url":"http://<LAPTOP_TAILSCALE_IP>:8080"}}'
```

---

## Demo-Flow testen

### Auf dem Jetson (Phase 0):

1. Sprachbefehl **"Neuer Patient"** → Patient wird angelegt
2. **"Aufnahme starten"** → Befund einsprechen → **"Aufnahme stoppen"**
3. **"Patient fertig"** → KI-Analyse startet automatisch
4. **"Patient melden"** → Alle Patienten werden an die Leitstelle übertragen

### Auf dem Laptop (Leitstelle):

- Patient erscheint automatisch im Dashboard
- BAT-Marker bewegt sich auf der Karte (GPS-Simulation)
- Triage-Übersicht zeigt Verwundete geclustert nach Transport

---

## Datenstruktur

- `backend/data/patients/` — JSON-Dateien pro Patient (überlebt Neustart)
- `backend/data/state.json` — Transporte, GPS-Positionen, Events

Zum Zurücksetzen: `rm -rf backend/data/` und Backend neustarten.
