#!/usr/bin/env bash
# SAFIR Sudoers-Setup — erlaubt dem Benutzer 'jetson' passwortlosen
# Shutdown-Aufruf, damit die Hardware-Shutdown-Geste funktioniert.
#
# EINMALIG ausführen: sudo bash scripts/setup-sudoers.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Dieses Skript muss mit sudo ausgeführt werden." >&2
  exit 1
fi

TARGET=/etc/sudoers.d/safir
cat > "$TARGET" <<'EOF'
# SAFIR — passwortloser Shutdown für Hardware-Geste
jetson ALL=(ALL) NOPASSWD: /sbin/shutdown, /usr/sbin/shutdown
EOF
chmod 440 "$TARGET"
chown root:root "$TARGET"

# Syntax-Check
if visudo -cf "$TARGET"; then
  echo "OK: /etc/sudoers.d/safir installiert und validiert."
else
  echo "FEHLER: visudo hat einen Syntax-Fehler gemeldet. Datei wird entfernt." >&2
  rm -f "$TARGET"
  exit 1
fi
