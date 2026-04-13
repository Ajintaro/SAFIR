# SAFIR RFID-Karten-Datenformat

Dieses Dokument beschreibt das Datenformat, das SAFIR auf MIFARE-Classic-1K-Karten
schreibt, damit externe Reader (z.B. am Surface-PC der Notfallzentrale auf der AFCEA-Messe)
die Patientendaten auswerten können.

## Karten-Typ

- **Chip:** NXP MIFARE Classic 1K (ISO/IEC 14443-A)
- **Speicher:** 16 Sektoren × 4 Blöcke × 16 Byte = 1024 Byte
- **Authentifizierung:** Key A, Default-Key `FF FF FF FF FF FF` (unverändert ab Werk)
- **Schreibender:** Jetson Orin Nano mit RC522-Modul (Bit-Bang SPI, siehe `shared/rfid.py`)

## Block-Layout

Beschrieben werden nur Sektor 1 und 2. Alle anderen Sektoren bleiben unberührt.
Die Sektor-Trailer (Block 7, 11, ...) werden **nicht** angefasst — Default-Keys bleiben gültig.

### Sektor 1 (Blöcke 4–6)

| Block | Offset | Größe | Feld                   | Encoding                                   |
|------:|-------:|------:|------------------------|--------------------------------------------|
|   4   |   0    |   8   | Magic `SAFIR\0\0\0`    | ASCII, Null-padded                         |
|   4   |   8    |   1   | Version                | uint8 (aktuell `0x01`)                     |
|   4   |   9    |   3   | Reserved               | `0x00 0x00 0x00`                           |
|   4   |  12    |   4   | Schreibzeit            | uint32 Little-Endian (Unix-Timestamp)      |
|   5   |   0    |  16   | Patient-ID             | ASCII, Null-padded (z.B. `PAT-A1B2C3D4`)   |
|   6   |   0    |   1   | Triage                 | uint8 (1=T1, 2=T2, 3=T3, 4=T4, 0=unbek.)   |
|   6   |   1    |   1   | Alter                  | uint8                                      |
|   6   |   2    |   1   | Geschlecht             | ASCII-Byte (`m`, `w`, `0` für unbekannt)   |
|   6   |   3    |   1   | Flags                  | Reserved (0)                               |
|   6   |   4    |   1   | Blutdruck systolisch   | uint8 (mmHg)                               |
|   6   |   5    |   1   | Blutdruck diastolisch  | uint8 (mmHg)                               |
|   6   |   6    |   1   | Puls                   | uint8 (Schläge/min)                        |
|   6   |   7    |   1   | Atemfrequenz           | uint8 (Züge/min)                           |
|   6   |   8    |   1   | SpO2                   | uint8 (%)                                  |
|   6   |   9    |   1   | GCS                    | uint8 (3–15)                               |
|   6   |  10    |   6   | Reserved               | 0                                          |

### Sektor 2 (Blöcke 8–10)

| Block | Offset | Größe | Feld                   | Encoding                                   |
|------:|-------:|------:|------------------------|--------------------------------------------|
|   8   |   0    |  16   | Name Teil 1            | UTF-8, Null-padded (Byte 0–15 des Namens)  |
|   9   |   0    |  16   | Name Teil 2            | UTF-8, Null-padded (Byte 16–31 des Namens) |
|  10   |   0    |  16   | Verletzungs-Mechanismus| UTF-8, Null-padded (erstes Mechanismus-Item)|

## Magic-Check

Ein Reader **muss** die ersten 8 Byte von Block 4 prüfen. Ist die Sequenz nicht
genau `53 41 46 49 52 00 00 00`, handelt es sich nicht um eine SAFIR-Karte und
die Daten dürfen nicht interpretiert werden.

## Minimal-Lesefluss (pseudo-APDU via PC/SC)

Die folgenden APDUs funktionieren mit PC/SC-Readern, die den MIFARE-Classic-Modus
unterstützen (z.B. ACR122U; einige ReinerSCT cyberJack RFID-Modelle). SAFIR selbst
nutzt den RC522 per Bit-Bang-SPI und die Low-Level-Funktionen in `shared/rfid.py`.

```text
# 1) Karten-UID lesen
APDU: FF CA 00 00 00                                       # Get UID
RESP: <4 bytes UID> + 9000

# 2) Default Key A in Reader-Slot 0 laden (einmalig)
APDU: FF 82 00 00 06 FF FF FF FF FF FF                    # Load Key
RESP: 9000

# 3) Block 4 (Sektor 1) mit Key A aus Slot 0 authentifizieren
APDU: FF 86 00 00 05 01 00 04 60 00                       # General Authenticate
RESP: 9000

# 4) Block 4 lesen (16 Byte)
APDU: FF B0 00 04 10                                       # Read Binary
RESP: <16 bytes> + 9000

# 5) Wiederholen für Blöcke 5, 6 (gleiche Auth), dann 8, 9, 10 (Sektor 2, neue Auth auf Block 8)
```

## Referenz-Implementierungen

| Rolle               | Datei                           | Zweck                                           |
|---------------------|---------------------------------|-------------------------------------------------|
| **Writer (Jetson)** | `shared/rfid.py`                | RC522 Bit-Bang, schreibt Patientendaten         |
| **Reader (Surface)**| `scripts/safir-card-reader.py`  | pyscard + Tk-UI, liest und zeigt Patient an     |
| **Format-Builder**  | `_build_patient_payload()` in `shared/rfid.py` | Konvertiert Patient-Dict in Block-Bytes |

## Änderungen

- **v1** (2026-04-13) — Initiales Layout für AFCEA-Messe-Prototyp. Sektor 1+2.
  Keine CRC, keine Verschlüsselung (Default Keys). Für produktiven Einsatz
  muss das Layout um CRC32, signierte Payloads und sektorspezifische Keys
  erweitert werden (siehe TEMPEST-/EmSec-Anforderungen aus Bundeswehr-Feedback).
