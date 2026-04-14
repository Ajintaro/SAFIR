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
                # Fire-and-forget: OLED wird sofort mit REBOOTING beschrieben.
                # Bei reboot/poweroff reicht ein Signal, danach stoppt systemd uns.
                /usr/bin/python3 "$OLED_SCRIPT" reboot &
                in_signal=0
            fi
            ;;
        *"boolean false"*)
            # PrepareForShutdown(false) bedeutet: Shutdown wurde abgebrochen
            in_signal=0
            ;;
    esac
done
