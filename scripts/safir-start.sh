#!/bin/bash
# SAFIR Autostart — Jetson Orin Nano
# Startreihenfolge: PulseAudio → Ollama vorladen → Whisper → SAFIR App

echo "$(date) — SAFIR Autostart"

# 0. GPIO Pinmux setzen (falls systemd-Service noch nicht gelaufen)
if [ -x /home/jetson/cgi-afcea-san/scripts/pinmux-setup.sh ]; then
    sudo /home/jetson/cgi-afcea-san/scripts/pinmux-setup.sh 2>/dev/null || true
fi

# OLED-Statusanzeige via Python (smbus2 direkt)
oled_status() {
    python3 -c "
import smbus2, time
from PIL import Image, ImageDraw, ImageFont
bus = smbus2.SMBus(7)
addr = 0x3C
for cmd in [0xAE,0xD5,0x80,0xA8,0x3F,0xD3,0x00,0x40,0x8D,0x14,0x20,0x00,0xA1,0xC8,0xDA,0x12,0x81,0xFF,0xD9,0xF1,0xDB,0x40,0xA4,0xA6,0xAF]:
    bus.write_byte_data(addr, 0x00, cmd)
img = Image.new('1', (128, 64), 0)
draw = ImageDraw.Draw(img)
try:
    f1 = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', 13)
    f2 = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', 9)
except:
    f1 = f2 = ImageFont.load_default()
draw.rectangle([0,0,127,63], outline=1)
draw.rectangle([2,2,125,61], outline=1)
bb = f1.getbbox('$1')
draw.text(((128-(bb[2]-bb[0]))//2, 16), '$1', font=f1, fill=1)
bb2 = f2.getbbox('$2')
draw.text(((128-(bb2[2]-bb2[0]))//2, 34), '$2', font=f2, fill=1)
raw = img.tobytes()  # Pillow-14 kompatibel (kein getdata())
rb = (128 + 7)//8
def px(x,y): return bool(raw[y*rb + (x>>3)] & (0x80 >> (x & 7)))
for page in range(8):
    bus.write_byte_data(addr, 0x00, 0xB0+page)
    bus.write_byte_data(addr, 0x00, 0x00)
    bus.write_byte_data(addr, 0x00, 0x10)
    buf=[]
    for x in range(128):
        byte=0
        for bit in range(8):
            y=page*8+bit
            if px(x,y): byte|=(1<<bit)
        buf.append(byte)
    for i in range(0,128,16):
        bus.write_i2c_block_data(addr, 0x40, buf[i:i+16])
bus.close()
" 2>/dev/null
}

oled_status "SAFIR" "Booting..."

# 1. GNOME-Daemons killen die trotz Override starten
for proc in gnome-software tracker-miner-fs-3 tracker-extract-3     evolution-alarm-notify evolution-calendar-factory evolution-addressbook-factory     evolution-source-registry update-notifier gjs; do
    pkill -f "$proc" 2>/dev/null
done
echo "GNOME-Daemons bereinigt"
oled_status "SAFIR" "Aufraumen..."

# 1b. Verwaiste whisper-server-Prozesse killen (Zombies aus früherem kill -9
#     auf uvicorn — Kinder bleiben stehen und fressen je ~1 GB RAM)
if pgrep -f whisper-server > /dev/null 2>&1; then
    echo "Whisper-Zombies gefunden — werden entfernt"
    pkill -9 -f whisper-server 2>/dev/null
    sleep 1
fi

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
oled_status "SAFIR" "Ollama laden..."
echo "Ollama: Starte und lade Modell vor..."
systemctl --user start ollama 2>/dev/null || sudo systemctl start ollama 2>/dev/null
sleep 2
# Modell einmal warm starten, damit GPU-RAM reserviert wird
curl -s http://127.0.0.1:11434/api/generate -d '{"model":"qwen2.5:1.5b","prompt":"Hi","stream":false,"options":{"num_gpu":20}}' > /dev/null 2>&1
echo "Ollama: Modell qwen2.5:1.5b auf GPU vorgeladen"
# Modell sofort entladen — GPU-RAM für Whisper freigeben
curl -s http://127.0.0.1:11434/api/generate -d '{"model":"qwen2.5:1.5b","prompt":"","keep_alive":0}' > /dev/null 2>&1
echo "Ollama: Modell entladen, GPU frei für Whisper"

# 6. SAFIR Server im Vordergrund starten (lädt Whisper intern)
#    exec ersetzt die Shell durch uvicorn — systemd sieht einen einzigen
#    Prozess und kann ihn sauber überwachen/stoppen. Manueller Aufruf
#    blockiert das Terminal bis Ctrl-C.
oled_status "SAFIR" "Server startet..."
cd /home/jetson/cgi-afcea-san
source venv/bin/activate
echo "$(date) — starte SAFIR App (uvicorn) im Vordergrund"
echo "RAM vor uvicorn: $(free -m | awk '/Mem:/ {print $4+$7}') MB"
exec python3 -m uvicorn app:app --host 0.0.0.0 --port 8080
