#!/usr/bin/env bash
#
# deploy-all.sh — SAFIR auf Jetson + SINA Workstation parallel deployen
#
# Bringt beide Backends auf den aktuellen origin/main:
#   1. Pre-Flight: HEAD == origin/main, SSH zur SINA erreichbar
#   2. Parallel: SINA via SSH (git pull + Win32_Process restart),
#      Jetson via systemctl restart (lokal, sudo)
#   3. Post-Flight: /api/status pollen bis beide VERSION aus
#      shared/version.py melden
#
# Aufruf: scripts/deploy-all.sh
# Voraussetzung: Aufruf aus dem Repo (Worktree oder Hauptbaum egal),
# HEAD muss zu origin/main gepusht sein, sudo NOPASSWD fuer
# systemctl restart safir.service, ssh sina passwordless.

set -euo pipefail

# ---- Konfiguration -------------------------------------------------------
JETSON_URL="http://127.0.0.1:8080"
SINA_URL="http://100.95.246.25:8080"
SINA_HOST="sina"
SINA_REPO='C:\Users\Rettung\Documents\SAFIR'
SINA_START_CMD='C:\Users\Rettung\Documents\SAFIR\start-sina.cmd'
HEALTH_TIMEOUT=180

# ---- Hilfsfunktionen -----------------------------------------------------
red()    { printf '\033[31m%s\033[0m\n' "$*"; }
green()  { printf '\033[32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
log()    { printf '[deploy] %s\n' "$*"; }

api_version() {
    # Holt das 'version'-Feld aus /api/status. Bei Fehler -> '?'
    local url="$1"
    curl -s --max-time 3 "${url}/api/status" 2>/dev/null \
        | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('version','?'))" 2>/dev/null \
        || echo "?"
}

# ---- 1. Pre-Flight -------------------------------------------------------
REPO_ROOT=$(git rev-parse --show-toplevel)
cd "$REPO_ROOT"

EXPECTED=$(python3 -c "import sys; sys.path.insert(0,'.'); from shared.version import VERSION; print(VERSION)")
log "Erwartete Version: ${EXPECTED}"

# Working tree clean? (untracked files ignorieren — z.B. data/, .reset_marker
# auf dem Jetson-Hauptbaum sind erwartet, blockieren den Deploy nicht)
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    red "[deploy] Working tree hat unstaged/uncommitted Aenderungen — bitte zuerst commiten/stashen."
    git status --short --untracked-files=no
    exit 1
fi

# HEAD == origin/main?
git fetch -q origin main
LOCAL_HEAD=$(git rev-parse HEAD)
ORIGIN_MAIN=$(git rev-parse origin/main)
if [[ "${LOCAL_HEAD}" != "${ORIGIN_MAIN}" ]]; then
    red "[deploy] HEAD (${LOCAL_HEAD:0:7}) != origin/main (${ORIGIN_MAIN:0:7})."
    yellow "[deploy] Bitte zuerst auf main mergen + push, dann erneut versuchen."
    exit 1
fi
log "HEAD == origin/main: ${LOCAL_HEAD:0:7}"

# SSH zur SINA?
if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "${SINA_HOST}" 'exit 0' 2>/dev/null; then
    red "[deploy] SSH zu '${SINA_HOST}' nicht erreichbar."
    exit 1
fi
log "SSH zu ${SINA_HOST}: OK"

# sudo passwordless?
if ! sudo -n true 2>/dev/null; then
    red "[deploy] sudo benoetigt Passwort — passwordless-sudo fuer systemctl notwendig."
    exit 1
fi

# Status vor Deployment
log "Vor Deploy: Jetson=v$(api_version "${JETSON_URL}"), SINA=v$(api_version "${SINA_URL}")"

# ---- 2. Parallel-Deploy --------------------------------------------------
log "Starte parallel: Jetson restart + SINA git-pull+restart..."

# SINA: git pull + alte python-Prozesse killen + neuer Start via Win32_Process
deploy_sina() {
    ssh "${SINA_HOST}" "cd '${SINA_REPO}'; git pull origin main" 1>&2
    ssh "${SINA_HOST}" "
        Get-Process python -EA SilentlyContinue | Stop-Process -Force
        Start-Sleep -Seconds 2
        \$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
            CommandLine = 'cmd /c \"${SINA_START_CMD}\"'
            CurrentDirectory = '${SINA_REPO}'
        }
        if (\$r.ReturnValue -ne 0) { Write-Error \"Win32_Process.Create rc=\$(\$r.ReturnValue)\"; exit 1 }
        Write-Output \"sina-pid=\$(\$r.ProcessId)\"
    "
}

# Jetson: systemctl restart safir
deploy_jetson() {
    sudo -n systemctl restart safir.service
    echo "jetson-restarted"
}

deploy_sina    > /tmp/deploy-sina.log    2>&1 &
SINA_PID=$!
deploy_jetson  > /tmp/deploy-jetson.log  2>&1 &
JETSON_PID=$!

SINA_RC=0
JETSON_RC=0
wait "${SINA_PID}"   || SINA_RC=$?
wait "${JETSON_PID}" || JETSON_RC=$?

if [[ ${SINA_RC} -ne 0 ]]; then
    red "[deploy] SINA-Restart fehlgeschlagen (rc=${SINA_RC}):"
    cat /tmp/deploy-sina.log
    exit 2
fi
log "SINA: $(tail -1 /tmp/deploy-sina.log)"

if [[ ${JETSON_RC} -ne 0 ]]; then
    red "[deploy] Jetson-Restart fehlgeschlagen (rc=${JETSON_RC}):"
    cat /tmp/deploy-jetson.log
    exit 2
fi
log "Jetson: restart-Kommando ok, warte auf Service-Boot"

# ---- 3. Health-Check -----------------------------------------------------
log "Health-Check (max ${HEALTH_TIMEOUT}s, polling alle 3s)..."
deadline=$(($(date +%s) + HEALTH_TIMEOUT))
last_status=""
while true; do
    j=$(api_version "${JETSON_URL}")
    s=$(api_version "${SINA_URL}")
    status="Jetson=v${j}, SINA=v${s}"
    if [[ "${status}" != "${last_status}" ]]; then
        log "  ${status}"
        last_status="${status}"
    fi
    if [[ "${j}" == "${EXPECTED}" && "${s}" == "${EXPECTED}" ]]; then
        green "[deploy] OK — beide auf v${EXPECTED} live"
        break
    fi
    if [[ $(date +%s) -gt ${deadline} ]]; then
        red "[deploy] TIMEOUT nach ${HEALTH_TIMEOUT}s — ${status}"
        exit 3
    fi
    sleep 3
done

# ---- 4. Mesh-Sanity-Check ------------------------------------------------
log "Mesh-Check: sehen sich die Geraete?"
sleep 5  # 1x Heartbeat-Periode (~30s) waere ideal, aber 5s reicht meist
peers_jetson=$(curl -s --max-time 3 "${JETSON_URL}/api/peers" 2>/dev/null \
    | python3 -c "import json,sys; print(len(json.loads(sys.stdin.read()).get('peers',[])))" 2>/dev/null || echo "?")
peers_sina=$(curl -s --max-time 3 "${SINA_URL}/api/peers" 2>/dev/null \
    | python3 -c "import json,sys; print(len(json.loads(sys.stdin.read()).get('peers',[])))" 2>/dev/null || echo "?")
log "  Jetson sieht ${peers_jetson} Peer(s) (inkl. self), SINA ${peers_sina}"

green "[deploy] FERTIG — v${EXPECTED} auf beiden Geraeten"
