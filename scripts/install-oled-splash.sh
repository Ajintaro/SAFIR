#!/usr/bin/env bash
# SAFIR OLED Splash-Install — installiert Boot- und Shutdown-Anzeigen
# die unabhängig von SAFIR laufen.
#
# EINMALIG ausführen: sudo bash scripts/install-oled-splash.sh
#
# Installiert:
#   /usr/local/bin/safir-oled-msg          (OLED-Helper)
#   /etc/systemd/system/safir-boot-splash.service
#   /usr/lib/systemd/system-shutdown/safir-oled
#
# Aktiviert:
#   systemctl enable safir-boot-splash.service
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "Dieses Skript muss mit sudo ausgeführt werden." >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

echo "==> Installiere /usr/local/bin/safir-oled-msg"
install -m 0755 -o root -g root \
    "$REPO_DIR/scripts/safir-oled-msg.py" \
    /usr/local/bin/safir-oled-msg

echo "==> Teste /usr/local/bin/safir-oled-msg"
if /usr/local/bin/safir-oled-msg "INSTALL" "Test OK" ; then
    echo "    OLED antwortet — Helper funktioniert"
    sleep 2
else
    echo "    WARNUNG: OLED-Helper-Test fehlgeschlagen — ist das OLED angeschlossen?"
fi

echo "==> Installiere /etc/systemd/system/safir-boot-splash.service"
install -m 0644 -o root -g root \
    "$REPO_DIR/scripts/systemd/safir-boot-splash.service" \
    /etc/systemd/system/safir-boot-splash.service

echo "==> Installiere /usr/lib/systemd/system-shutdown/safir-oled"
install -d -m 0755 /usr/lib/systemd/system-shutdown
install -m 0755 -o root -g root \
    "$REPO_DIR/scripts/systemd/safir-oled-shutdown" \
    /usr/lib/systemd/system-shutdown/safir-oled

echo "==> systemctl daemon-reload"
systemctl daemon-reload

echo "==> safir-boot-splash.service aktivieren"
systemctl enable safir-boot-splash.service

echo ""
echo "OK — Installation abgeschlossen."
echo ""
echo "Aktive Komponenten:"
echo "  - safir-boot-splash.service  (läuft beim nächsten Boot automatisch)"
echo "  - /usr/lib/systemd/system-shutdown/safir-oled  (läuft bei jedem Shutdown)"
echo ""
echo "Sofort-Test:"
echo "  sudo systemctl start safir-boot-splash.service"
echo "  → sollte auf dem OLED 'STARTE / Ubuntu laedt' anzeigen"
echo ""
echo "Shutdown-Test (macht tatsächlich einen Shutdown):"
echo "  sudo shutdown -h +1   # in 1 Minute"
echo "  → beim Halt zeigt das OLED 'SHUTDOWN / Kernel halt'"
