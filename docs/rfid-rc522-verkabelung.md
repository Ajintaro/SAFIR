# RC522 RFID-Leser — Verkabelung Jetson Orin Nano

## Pinbelegung

| RC522 Pin | Kabelfarbe | Jetson Pin | Funktion   |
|-----------|------------|------------|------------|
| SDA (NSS) | lila       | Pin 24     | SPI0_CS0   |
| SCK       | schwarz    | Pin 23     | SPI0_CLK   |
| MOSI      | blau       | Pin 19     | SPI0_MOSI  |
| MISO      | weiß       | Pin 21     | SPI0_MISO  |
| GND       | grau       | Pin 20     | Ground     |
| RST       | rot        | Pin 7      | GPIO Reset |
| VCC       | braun      | Pin 17     | 3.3V       |

## Hinweise

- RC522 ist ein 3.3V-Modul — kein Level-Shifter nötig
- VCC an 3.3V (Pin 17), NICHT an 5V (Pin 2/4)
- Pin 1 und Pin 6 sind anderweitig belegt
- SPI0 muss im Device Tree aktiviert sein (siehe unten)

## SPI aktivieren

```bash
sudo /opt/nvidia/jetson-io/jetson-io.py
# → Configure Jetson 40pin Header → Configure header pins manually → SPI0 aktivieren
```

Alternativ per Kommandozeile:
```bash
sudo /opt/nvidia/jetson-io/config-by-function.py -o dtbo spi0
sudo reboot
```

## Test

```bash
ls /dev/spidev*
# Erwartet: /dev/spidev0.0
```
