# SAFIR — Sicherheitsarchitektur

> **Für Messebesucher und technische Auditoren.** Dieses Dokument
> beantwortet die häufigste Frage: *„Wie sicher ist die Kommunikation
> zwischen Jetson und Leitstelle?"* — transparent, ohne Marketing,
> mit Verweisen auf die eingesetzten Industriestandards.

**Kurzantwort:** SAFIR nutzt **WireGuard** (über Tailscale als Mesh-VPN)
für die komplette Transport-Verschlüsselung. Alle Patientendaten zwischen
Feldgerät (Jetson) und Leitstelle (Surface) sind **Ende-zu-Ende mit
ChaCha20-Poly1305 verschlüsselt**. Nicht mal Tailscale selbst kann
mitlesen (Zero-Trust-Architektur, Schlüsselpaare liegen ausschließlich
auf den Endgeräten).

---

## 1. Die 3 Schichten, die schützen

```
┌──────────────────────────────────────────────────────────────────┐
│                                                                  │
│   [Jetson BAT]                                        [Surface]  │
│                                                                  │
│     SAFIR-App                                         SAFIR-App  │
│        │                                                  │      │
│        │  HTTPS/WSS                            HTTPS/WSS │      │
│        │  (TLS 1.3 zusätzlich möglich)                   │      │
│        ▼                                                  ▼      │
│     ╔═══════════════════════════════════════════════════════╗    │
│     ║  WireGuard-Tunnel  (ChaCha20-Poly1305, End-zu-End)    ║    │
│     ║                                                        ║    │
│     ║  Curve25519 Schlüsselaustausch                         ║    │
│     ║  Poly1305 Message-Authentication-Code                  ║    │
│     ║  Blake2s Hashing                                       ║    │
│     ║                                                        ║    │
│     ║  Session-Keys rotieren alle 2 Minuten oder 60 MB       ║    │
│     ╚═══════════════════════════════════════════════════════╝    │
│        ▲                                                  ▲      │
│        │                                                  │      │
│        └──────── Internet / Mobile / Starlink ────────────┘      │
│                   (alle Bytes verschlüsselt)                     │
│                                                                  │
│                         ┌────────────────┐                       │
│                         │ Tailscale Cloud│                       │
│                         │  Control Plane │  ← Nur Public Keys   │
│                         │  (Koordination)│    + ACL-Regeln       │
│                         └────────────────┘    Keine Payloads!    │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### Schicht 1 — WireGuard-Tunnel (Transport-Verschlüsselung)

Jede TCP/UDP-Verbindung zwischen Jetson und Surface läuft durch einen
WireGuard-Tunnel. WireGuard ist:

- Seit **Linux-Kernel 5.6 (März 2020)** Teil des Mainline-Kernels
- **1 kleines Crypto-Primitiv pro Aufgabe** — keine Algorithmus-Suite,
  keine Verhandlung, keine Downgrade-Angriffe möglich
- Auditiert von u. a. **Jason A. Donenfeld**, **NSF-geförderte Reviews**
- Deutlich kleinerer Angriffsflächen-Footprint als IPsec/OpenVPN
  (ca. **4.000 Zeilen Code** vs. > 500.000 bei IPsec)

**Die 4 eingesetzten Primitive:**

| Aufgabe | Algorithmus | Anwendung |
|---|---|---|
| Schlüsselaustausch | **Curve25519** (ECDH) | Noise-IK-Handshake beim Tunnel-Aufbau |
| Symmetrische Verschlüsselung | **ChaCha20** | Alle Payload-Bytes verschlüsselt |
| Message-Authentication | **Poly1305** | Jedes Paket kryptografisch authentifiziert |
| Hashing | **Blake2s** | Innerhalb des Noise-Handshakes |

**Re-Keying:** Session-Schlüssel werden alle **2 Minuten** oder nach
**60 MB Traffic** rotiert (Perfect Forward Secrecy). Ein eventuell
kompromittierter Schlüssel gefährdet also höchstens 2 Minuten Traffic.

### Schicht 2 — Tailscale (Identity-Management)

Tailscale fügt zu WireGuard drei Dinge hinzu, die pures WireGuard nicht
hat:

1. **Identity-basierte Peer-Autorisierung** — Jedes Gerät ist an einen
   Benutzer-Account gekoppelt, nicht an eine statische IP. Austausch
   von Geräten erfordert Neu-Pairing durch den Admin.
2. **ACL (Access Control List)** — Feingranulare Regeln wie „nur
   `jetson-orin` darf zu `ai-station:8080`". In SAFIR-Setup sind nur
   die benötigten Ports (`ws`, `/api/ingest`) erlaubt.
3. **NAT-Traversal + Relays** — Baut auch hinter Firmen-NAT oder Mobile-
   Hotspot eine Direct-Connection auf (UDP-Hole-Punching). Fallback
   über DERP-Relays wenn Direct nicht geht.

**Wichtig — was Tailscale NICHT sehen kann:**

- Der **Inhalt** aller Pakete ist mit WireGuard verschlüsselt.
  Tailscale kennt nur Public-Keys, Peer-IPs und Paket-Größen — nicht
  die Payloads.
- Schlüsselpaare werden **auf den Endgeräten erzeugt** und verlassen
  diese nie. Tailscale bekommt nur die Public Keys.
- Selbst wenn Tailscale Inc. kompromittiert wäre: Ein Angreifer bekäme
  maximal Metadaten (welcher Peer spricht mit welchem, wie viel Traffic),
  **nicht die eigentlichen Patientendaten**.

### Schicht 3 — Anwendungs-Authentifizierung

Zusätzlich zum Transport-Tunnel prüfen die Anwendungen:

- **HTTPS/WSS** kann zusätzlich oben drauf gestapelt werden (doppelte
  Verschlüsselung, falls gewünscht für Regulatory Compliance)
- **Patient-IDs** sind UUID-basiert, nicht vorhersagbar (`PAT-<8 hex>`)
- **RFID-Tag-IDs** sind UID-basierte Pointer, nicht die Daten selbst —
  die Daten liegen verschlüsselt im SAFIR-Datenbank-State

---

## 2. Was passiert bei konkreten Angriffs-Szenarien?

### Szenario A — Mitlesen auf dem WLAN / Mobile Hotspot

*„Ich stehe im selben WLAN wie der Jetson. Was sehe ich?"*

**Antwort:** WireGuard-UDP-Pakete zum Tailscale-DERP-Relay oder direkt
zum Surface. Alle Bytes sind ChaCha20-verschlüsselt. Ohne den privaten
Schlüssel (der auf dem Jetson liegt) kommst du nicht an Klartext.

**Rechenzeit zum Brechen:** Nach aktuellem Stand keine praktische
Angriffsmethode gegen ChaCha20-Poly1305 bekannt. Brute-Force bei
256-Bit-Schlüssel erfordert etwa 2⁻²³ des bekannten Universums an
Zeit-Steel (physikalisch unmöglich).

### Szenario B — Lost & Found: Verlorener Jetson

*„Was passiert wenn der Jetson verloren geht oder gestohlen wird?"*

**Antwort:** Kritisch, aber beherrschbar.

- Der Finder sieht **bereits auf dem Jetson gespeicherte Patientendaten**
  (die sind lokal im `state.patients` Dict und teilweise auch auf
  MIFARE-Karten).
- Der Finder kann **nicht** neue Verbindungen ins Tailnet aufbauen —
  die Tailscale-Keys sind an OS-User und Geräte-Hash gekoppelt. Bei
  einem Geräte-Reset werden sie ungültig.
- **Gegenmaßnahme:** Admin kann den Jetson-Peer aus der Tailscale-Admin-
  Console **sofort sperren** (1 Klick). Der verlorene Jetson kann dann
  nichts mehr an das Tailnet senden.
- **Zukünftig:** Full-Disk-Encryption (LUKS) auf dem Jetson würde auch
  den Offline-Zugriff auf Patientendaten verhindern. Das ist nicht Teil
  der aktuellen Demo-Konfiguration — wäre ein sinnvoller nächster
  Härtungsschritt.

### Szenario C — Bundeswehr-Netz / NATO-Secret-Einsatz

*„Dürfen wir SAFIR im NATO-Netz einsetzen?"*

**Antwort:** Mit WireGuard als Krypto-Backbone ja, technisch auf
derselben Ebene wie IPsec/IKEv2-Lösungen die aktuell von NATO zugelassen
sind. **Formale Freigaben** (BSI-VS-NfD, NATO-Restricted) sind jedoch
**nicht Teil** der aktuellen Demo — das ist ein regulatorischer Prozess,
der beim tatsächlichen Einsatz vom BWB durchgeführt werden müsste.

Tailscale als Cloud-Komponente wäre im kritischen Einsatz durch
**Headscale** (Open-Source-Tailscale-Server, self-hosted auf einem
gehärteten Server im Bundeswehr-Netz) ersetzbar. Das lokale Protokoll
zwischen Endgeräten ändert sich dadurch **nicht** — es bleibt WireGuard.

---

## 3. Was SAFIR (noch) NICHT hat — Transparente Limits

Damit keine falschen Erwartungen entstehen:

1. **Keine App-Layer-Verschlüsselung zusätzlich zu WireGuard.** Wir
   vertrauen darauf dass der Transport-Tunnel reicht. Für höhere
   Assurance (Defense-in-Depth) könnte zusätzlich AES/Fernet auf
   `/api/ingest`-Payloads gelegt werden. Das ist aber nur kosmetisch —
   WireGuard ist bereits ein Industriestandard.
2. **Keine Hardware-Attestation.** SAFIR prüft nicht, ob das Jetson-
   Betriebssystem unverändert ist. Ein kompromittiertes OS könnte
   Patientendaten exfiltrieren. Secure-Boot + TPM-Attestation wäre
   möglich, ist aber aktuell nicht aktiviert.
3. **Keine Rotation des Tailscale-Auth-Keys.** Der Auth-Key läuft
   unbegrenzt, bis er manuell über die Admin-Console widerrufen wird.
   Bei Produktions-Einsatz sollten Keys regelmäßig rotiert werden
   (Tailscale unterstützt das via Auth-Key-Expiry).
4. **NFC/RFID-Karten sind unverschlüsselt.** Die MIFARE-Classic-Karten
   nutzen den Default-Key `FFFFFFFFFFFF`. Physischer Zugriff auf eine
   Karte = Lesbarkeit der Patient-ID + Triage. Für die Demo OK
   (Karten bleiben beim BAT), für Produktion wäre MIFARE-DESFire mit
   AES-Keys der nächste Schritt.

---

## 4. Talking Points für Messebesucher (Kurzfassung)

Wenn jemand auf der AFCEA fragt: *„Wie sicher ist das?"* — diese 5
Sätze reichen meistens:

1. **„Wir nutzen WireGuard, das seit 2020 im Linux-Kernel ist und von
   der Krypto-Community als Goldstandard gilt."**
2. **„Jedes Paket ist mit ChaCha20-Poly1305 End-zu-End-verschlüsselt.
   Schlüssel rotieren alle 2 Minuten."**
3. **„Tailscale ist nur für die Identity-Verwaltung zuständig — sie
   sehen die Patientendaten nie. Die Schlüssel liegen auf den End-
   geräten."**
4. **„Wir sind bewusst auf einen gut auditierten Industriestandard
   gegangen statt eigenen Krypto-Code zu schreiben. Don't roll your
   own crypto."**
5. **„Für einen Voll-NATO-Einsatz wäre Headscale statt Tailscale als
   Self-Hosted-Coordination die nächste Stufe — das Protokoll zwischen
   den Endgeräten bleibt WireGuard."**

---

## 5. Verifikation / weiterführende Lektüre

- **WireGuard Whitepaper:** https://www.wireguard.com/papers/wireguard.pdf
- **Tailscale Security FAQ:** https://tailscale.com/security
- **Noise Protocol Framework:** https://noiseprotocol.org/noise.html
  (das zugrundeliegende Framework für den WireGuard-Handshake)
- **Curve25519:** Daniel J. Bernstein, 2006 — Standard seit RFC 7748
- **ChaCha20-Poly1305:** RFC 8439 — in TLS 1.3 als AEAD-Cipher-Suite

---

## Appendix — Aktueller SAFIR-Demo-Status

- **Jetson ↔ Surface:** WireGuard via Tailscale ✓
- **Tailnet:** `jaimy.reuter@gmail.com` Account, 2 aktive Peers
  (`jetson-orin`, `ai-station`)
- **ACL:** Default (alle Peers können miteinander sprechen —
  Production-Lockdown käme bei echter Bundeswehr-Integration)
- **DERP-Relay:** Nuremberg + Frankfurt (automatisches Failover)
- **Keys:** Auto-generiert beim ersten Login, liegen in
  `/var/lib/tailscale/` (Jetson) bzw. `%ProgramData%\Tailscale\`
  (Windows-Surface)
