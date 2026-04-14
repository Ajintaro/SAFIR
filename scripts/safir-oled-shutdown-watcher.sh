#!/bin/bash
# SAFIR OLED Shutdown-Watcher.
#
# Horcht via dbus-monitor auf das systemd-logind Signal PrepareForShutdown
# und schreibt SOFORT "REBOOTING" auf das OLED — noch bevor systemd
# anfängt, Services in der Stop-Reihenfolge abzubauen.
#
# Muss als root laufen, damit dbus-monitor vollen Monitoring-Zugriff hat.
# Als User gibt es nur "eavesdropping" mit Access-Denied-Warnung.

set -u

OLED_SCRIPT=/home/jetson/cgi-afcea-san/scripts/oled-status.py
SHUTDOWN_WAV=/home/jetson/cgi-afcea-san/sounds/shutdown.wav

exec dbus-monitor --system \
    "type='signal',interface='org.freedesktop.login1.Manager',member='PrepareForShutdown'" \
    2>/dev/null | \
while IFS= read -r line; do
    case "$line" in
        *"member=PrepareForShutdown"*)
            in_signal=1
            ;;
        *"boolean true"*)
            if [ "${in_signal:-0}" = "1" ]; then
                # Fire-and-forget: OLED mit REBOOTING + Shutdown-Sound parallel.
                # Beide laufen als Hintergrund-Prozess und werden von systemd
                # gleich wieder gestoppt — wir warten bewusst nicht.
                /usr/bin/python3 "$OLED_SCRIPT" reboot &
                if [ -f "$SHUTDOWN_WAV" ]; then
                    /usr/bin/aplay -q -D plughw:0,0 "$SHUTDOWN_WAV" 2>/dev/null &
                fi
                in_signal=0
            fi
            ;;
        *"boolean false"*)
            # PrepareForShutdown(false) bedeutet: Shutdown wurde abgebrochen
            in_signal=0
            ;;
    esac
done
