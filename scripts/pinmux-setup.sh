#!/bin/bash
# ============================================================================
# SAFIR Pinmux-Setup — Jetson Orin Nano GPIO Header
# ============================================================================
# Setzt den Tegra234 Pinmux für alle 40-Pin Header-GPIOs per devmem.
# Nötig weil das Device-Tree Overlay nicht korrekt angewendet wird
# (alle Pins stehen nach Boot auf Tristate/High-Z).
#
# Muss als root laufen (braucht /dev/mem Zugriff).
# Wird automatisch via systemd-Service beim Boot ausgeführt.
# ============================================================================

set -euo pipefail

log() { echo "$(date '+%H:%M:%S') [pinmux] $*"; }

# Prüfe ob busybox devmem verfügbar ist
if ! command -v busybox &>/dev/null; then
    log "FEHLER: busybox nicht gefunden"
    exit 1
fi

# ============================================================================
# Tegra234 PADCTL Register-Werte
# ============================================================================
# Bit [1:0]  PM       — Function Select (0=GP, 1=Alt1, ...)
# Bit [3:2]  PUPD     — 00=none, 01=pull-down, 10=pull-up
# Bit [4]    Tristate  — 0=DRIVE, 1=HIGH-Z ← MUSS 0 sein!
# Bit [5]    Park
# Bit [6]    E_INPUT  — 0=disable, 1=enable
# Bit [10]   Schmitt Trigger
#
# GPIO Output:  PM=0, Tristate=0, E_INPUT=0, Schmitt=1 → 0x0400
# GPIO Input:   PM=0, Tristate=0, E_INPUT=1, Schmitt=1 → 0x0440
# SPI1 Output:  PM=1, Tristate=0, E_INPUT=0, Schmitt=1 → 0x0401
# SPI1 Input:   PM=1, Tristate=0, E_INPUT=1, Schmitt=1 → 0x0441
# SPI1 CS0:     PM=1, Tristate=0, E_INPUT=0, PUPD=pull-up, Schmitt=1 → 0x0409
# ============================================================================

log "Starte Pinmux-Konfiguration für 40-Pin Header..."

# --- RC522 RFID: SPI-Pins als GPIO für Bit-Bang (Pin 19, 21, 23, 24) ---
# spidev-Treiber hat keine pinctrl im DT → Bit-Bang über GPIO nutzen
# Kabelfarben: MOSI=blau, MISO=weiß, SCK=schwarz, NSS=lila
log "SPI-Pins als GPIO (RC522 Bit-Bang)..."
busybox devmem 0x0243d040 32 0x0400  # Pin 19: MOSI (blau)    — GPIO Output
busybox devmem 0x0243d018 32 0x0440  # Pin 21: MISO (weiß)    — GPIO Input
busybox devmem 0x0243d028 32 0x0400  # Pin 23: SCK (schwarz)  — GPIO Output
busybox devmem 0x0243d008 32 0x0400  # Pin 24: CS0 (lila)     — GPIO Output

# --- RC522 RST (Pin 7) als GPIO Output ---
log "Pin 7: RST (rot) als GPIO Output..."
busybox devmem 0x02448030 32 0x0400  # Pin 7: SOC_GPIO59_PAC6 — GPIO Out

# --- Allgemeine GPIO-Pins ---
log "Allgemeine GPIO-Pins..."
busybox devmem 0x02430098 32 0x0440  # Pin 11: UART1_RTS      — GPIO Input
busybox devmem 0x02434088 32 0x0440  # Pin 12: SOC_GPIO41_PH7 — GPIO Input
busybox devmem 0x0243d030 32 0x0440  # Pin 13: SPI3_SCK_PY0   — GPIO Input
busybox devmem 0x02440020 32 0x0440  # Pin 15: SOC_GPIO39_PN1 — GPIO Input
busybox devmem 0x0243d020 32 0x0440  # Pin 16: SPI3_CS1_PY4   — GPIO Input
busybox devmem 0x0243d010 32 0x0440  # Pin 18: SPI3_CS0_PY3   — GPIO Input
busybox devmem 0x0243d000 32 0x0440  # Pin 22: SPI3_MISO_PY1  — GPIO Input
busybox devmem 0x0243d038 32 0x0440  # Pin 26: SPI1_CS1_PZ7   — GPIO Input
busybox devmem 0x024340a0 32 0x0440  # Pin 35: SOC_GPIO44_PI2 — GPIO Input
busybox devmem 0x02430090 32 0x0440  # Pin 36: UART1_CTS_PR5  — GPIO Input
busybox devmem 0x0243d048 32 0x0440  # Pin 37: SPI3_MOSI_PY2  — GPIO Input
busybox devmem 0x02434098 32 0x0440  # Pin 38: SOC_GPIO43_PI1 — GPIO Input
busybox devmem 0x02434090 32 0x0440  # Pin 40: SOC_GPIO42_PI0 — GPIO Input

# AON-Pins (29, 31, 32, 33, 37) brauchen kein devmem — funktionieren ab Werk

log "Fertig — 17 Main-Pins konfiguriert (5× SPI1, 1× GPIO-Out, 11× GPIO-In)"
log "AON-Pins (29, 31, 32, 33, 37) waren bereits funktional"
