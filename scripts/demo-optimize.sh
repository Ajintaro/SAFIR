#!/bin/bash
# SAFIR Demo-Optimierung — RAM freigeben auf Jetson Orin Nano
# Sicher: Stoppt nur Dienste die für die Demo nicht benötigt werden.
# Nichts wird deinstalliert oder dauerhaft geändert.
# Nach Neustart ist alles wieder wie vorher.

# Kein set -e — manche Prozesse existieren nicht, das ist OK

echo "=== SAFIR Demo-Optimierung ==="
echo "Jetson Orin Nano — $(free -m | awk '/Mem:/ {print $4}') MB frei"
echo ""

# 1. GNOME Hintergrund-Daemons killen (~537 MB)
echo "[1/5] GNOME Hintergrund-Daemons beenden..."
GNOME_KILL=(
    gnome-software          # Software Center — nicht gebraucht
    tracker-miner-fs-3      # Datei-Indexierung — frisst CPU + RAM
    evolution-alarm-notify   # Kalender-Benachrichtigungen
    evolution-calendar-factory
    evolution-addressbook-factory
    evolution-source-registry
    update-notifier          # Update-Hinweise
    gsd-print-notifications  # Drucker
    gsd-disk-utility-notify  # Festplatten-Benachrichtigungen
    gsd-sharing              # Dateifreigabe
    gsd-smartcard            # Smartcard
    gsd-wacom                # Wacom Tablet
    gsd-a11y-settings        # Barrierefreiheit
    gsd-screensaver-proxy    # Bildschirmschoner
)
killed=0
for proc in "${GNOME_KILL[@]}"; do
    if pkill -f "$proc" 2>/dev/null; then
        ((killed++))
    fi
done
echo "  $killed Prozesse beendet"

# Tracker komplett deaktivieren (Session-wide)
if command -v tracker3 &>/dev/null; then
    tracker3 reset -s -r 2>/dev/null || true
fi

# 2. Docker + Containerd stoppen (~48 MB)
echo "[2/5] Docker stoppen..."
if systemctl is-active --quiet docker 2>/dev/null; then
    sudo systemctl stop docker containerd 2>/dev/null && echo "  Docker gestoppt" || echo "  Docker bereits gestoppt"
else
    echo "  Docker nicht aktiv"
fi

# 3. Unnötige Systemdienste stoppen (~60 MB)
echo "[3/5] Unnötige Dienste stoppen..."
STOP_SERVICES=(
    fwupd              # Firmware-Updates
    packagekit         # Software-Pakete
    bluetooth          # Bluetooth
    colord             # Farbprofil-Management
    kerneloops         # Kernel-Crash Reporter
    lpd                # Druckdienst
    rpcbind            # RPC (NFS)
    avahi-daemon       # Bonjour/mDNS
    cups.cupsd         # Drucker
    cups.cups-browsed  # Drucker-Browser
)
for svc in "${STOP_SERVICES[@]}"; do
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
        sudo systemctl stop "$svc" 2>/dev/null && echo "  $svc gestoppt"
    fi
done

# 4. Pagecache freigeben
echo "[4/5] Pagecache freigeben..."
sync
echo 1 | sudo tee /proc/sys/vm/drop_caches > /dev/null 2>&1 || true

# 5. Jetson Performance-Modus sicherstellen
echo "[5/5] Performance-Einstellungen..."
if command -v nvpmodel &>/dev/null; then
    mode=$(nvpmodel -q 2>/dev/null | grep "NV Power Mode" | awk '{print $NF}')
    echo "  Power Mode: $mode"
fi
# CPU Governor auf performance setzen (optional, mehr Strom)
# for cpu in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
#     echo performance | sudo tee "$cpu" > /dev/null 2>&1
# done

echo ""
echo "=== Ergebnis ==="
free -m | awk '/Mem:/ {printf "RAM: %d MB frei (von %d MB, %d%% frei)\n", $4+$7, $2, ($4+$7)*100/$2}'
echo ""
echo "Tipp: Vor Demo auch Firefox und Claude Code beenden für weitere ~600 MB"
echo "Rückgängig: Einfach Jetson neu starten"
