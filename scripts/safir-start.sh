#!/bin/bash
# SAFIR Autostart — Jetson Orin Nano
# Startreihenfolge: PulseAudio → Ollama vorladen → Whisper → SAFIR App

echo "$(date) — SAFIR Autostart"

# 1. GNOME-Daemons killen die trotz Override starten
for proc in gnome-software tracker-miner-fs-3 tracker-extract-3     evolution-alarm-notify evolution-calendar-factory evolution-addressbook-factory     evolution-source-registry update-notifier gjs; do
    pkill -f "$proc" 2>/dev/null
done
echo "GNOME-Daemons bereinigt"

# 2. Pagecache freigeben
sync
echo 1 | sudo tee /proc/sys/vm/drop_caches > /dev/null 2>&1

# 3. PulseAudio starten (nötig für TTS im Headless-Modus)
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export PULSE_SERVER=unix:${XDG_RUNTIME_DIR}/pulse/native
pulseaudio --check 2>/dev/null || pulseaudio --start 2>/dev/null
sleep 1
echo "PulseAudio: $(pactl info 2>/dev/null | grep 'Default Sink' || echo 'nicht verfügbar')"

# 4. Audio: Headset als Default setzen (falls vorhanden)
if pactl list short sinks 2>/dev/null | grep -q "Logitech"; then
    pactl set-default-sink alsa_output.usb-Logitech_Logitech_G430_Gaming_Headset-00.analog-stereo 2>/dev/null
    pactl set-default-source alsa_input.usb-Logitech_Logitech_G430_Gaming_Headset-00.mono-fallback 2>/dev/null
    echo "Audio: Logitech Headset gesetzt"
    # USB-Headset auch in PulseAudio als Sink laden
    pactl load-module module-alsa-card device_id=0 name=usb_headset 2>/dev/null
    pactl set-default-sink alsa_output.usb_headset.analog-stereo 2>/dev/null
    pactl set-default-source alsa_input.usb_headset.mono-fallback 2>/dev/null
    echo "PulseAudio: Logitech Headset als Default Sink"
fi

# 5. Ollama starten + Modell vorladen (MUSS vor Whisper!)
echo "Ollama: Starte und lade Modell vor..."
systemctl --user start ollama 2>/dev/null || sudo systemctl start ollama 2>/dev/null
sleep 2
# Modell einmal warm starten, damit GPU-RAM reserviert wird
curl -s http://127.0.0.1:11434/api/generate -d '{"model":"qwen2.5:1.5b","prompt":"Hi","stream":false,"options":{"num_gpu":20}}' > /dev/null 2>&1
echo "Ollama: Modell qwen2.5:1.5b auf GPU vorgeladen"
# Modell sofort entladen — GPU-RAM für Whisper freigeben
curl -s http://127.0.0.1:11434/api/generate -d '{"model":"qwen2.5:1.5b","prompt":"","keep_alive":0}' > /dev/null 2>&1
echo "Ollama: Modell entladen, GPU frei für Whisper"

# 6. SAFIR Server starten (lädt Whisper intern)
cd /home/jetson/cgi-afcea-san
source venv/bin/activate
python3 -m uvicorn app:app --host 0.0.0.0 --port 8080 > /tmp/safir.log 2>&1 &
SAFIR_PID=$!
echo "SAFIR Server gestartet (PID $SAFIR_PID)"

# 7. Warten und nochmal aufräumen
sleep 15
for proc in gnome-software tracker-miner-fs-3 evolution-alarm-notify update-notifier; do
    pkill -f "$proc" 2>/dev/null
done

echo "$(date) — SAFIR Autostart abgeschlossen"
echo "RAM frei: $(free -m | awk '/Mem:/ {print $4+$7}') MB"
