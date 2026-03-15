#!/bin/bash
# SAFIR Autostart — läuft nach GNOME-Login
# Räumt unnötige Prozesse auf und startet den Server

echo "$(date) — SAFIR Autostart"

# 1. GNOME-Daemons killen die trotz Override starten
for proc in gnome-software tracker-miner-fs-3 tracker-extract-3 \
    evolution-alarm-notify evolution-calendar-factory evolution-addressbook-factory \
    evolution-source-registry update-notifier gjs; do
    pkill -f "$proc" 2>/dev/null
done
echo "GNOME-Daemons bereinigt"

# 2. Pagecache freigeben
sync
echo 1 | sudo tee /proc/sys/vm/drop_caches > /dev/null 2>&1

# 3. Audio: Headset als Default setzen (falls vorhanden)
sleep 2
if pactl list short sinks 2>/dev/null | grep -q "Logitech"; then
    pactl set-default-sink alsa_output.usb-Logitech_Logitech_G430_Gaming_Headset-00.analog-stereo 2>/dev/null
    pactl set-default-source alsa_input.usb-Logitech_Logitech_G430_Gaming_Headset-00.mono-fallback 2>/dev/null
    echo "Audio: Logitech Headset gesetzt"
fi

# 4. SAFIR Server starten
cd /home/jetson/cgi-afcea-san
source venv/bin/activate
python3 -m uvicorn app:app --host 0.0.0.0 --port 8080 > /tmp/safir.log 2>&1 &
SAFIR_PID=$!
echo "SAFIR Server gestartet (PID $SAFIR_PID)"

# 5. Warten und nochmal aufräumen (manche GNOME-Daemons starten verzögert)
sleep 15
for proc in gnome-software tracker-miner-fs-3 evolution-alarm-notify update-notifier; do
    pkill -f "$proc" 2>/dev/null
done

echo "$(date) — SAFIR Autostart abgeschlossen"
echo "RAM frei: $(free -m | awk '/Mem:/ {print $4+$7}') MB"
