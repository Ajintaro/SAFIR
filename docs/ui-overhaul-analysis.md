# SAFIR — UI Overhaul Analyse (Phase 10)

> **Kontext.** Der User hat auf einem 14-Zoll-Surface (2400×1600 Pixel,
> ≈200 PPI, devicePixelRatio 1.5) beobachtet, dass die SAFIR-UI massiv
> zu kleine Schriften hat. Gerade aus normaler Sitzdistanz (50–70 cm)
> sind viele Elemente nicht mehr lesbar — insbesondere der
> Header-Subtitle, die BAT-Einheit, Sidebar-Separator-Labels,
> Topbar-Status-Chips, Settings-Formularlabels und
> Triage-Counter-Werte.
>
> Dieses Dokument ist die **Diagnose** vor dem Redesign. Es enthält:
> 1. Harte Messdaten aus der aktuellen UI (DOM + CSS-Audit)
> 2. Warum die aktuellen Zahlen nicht den 2026-Standards entsprechen
> 3. Ein Ziel-Design-System (konkrete Werte, keine Vagueheiten)
> 4. Einen gestaffelten Migrationsplan
>
> **Datum:** 16.04.2026. Autor der Analyse: Claude Code.

---

## Executive Summary (Kurzfassung für den User)

Die UI-Kritik ist empirisch begründet, nicht „gefühlt". Konkret:

1. **81 % aller CSS-`font-size`-Deklarationen sind < 13 px** (228 von 283
   Werten im Template). Die dominanteste Einzelgröße ist **10 px**
   (28.6 %).
2. **Die 9-/10-px-Texte liegen physiologisch am Lesbarkeitsrand** für
   einen Surface mit 200 PPI aus 60 cm Sitzdistanz (ca. 4.3 arc min
   visueller Winkel — unter der 5-arc-min-Schwelle für 20/20-Vision).
3. **Kein einziges der 5 großen Design-Systeme** (GOV.UK, Material 3,
   Fluent 2, Apple HIG, IBM Carbon) erlaubt Text unter 10 px. GOV.UK,
   die beste Referenz für Stress-UIs, sagt explizit: „below 14 px is
   bad for accessibility and should not be included as options."
4. **Die aktuelle „Tactical-HUD"-Ästhetik** (Bracket-Corners + Share
   Tech Mono + UPPERCASE überall) entspricht Filmen und Spielen
   (Destiny 2, The Expanse), nicht produktiven militärischen Systemen
   wie Palantir Blueprint, Anduril Lattice, Helsing Altra, SitaWare,
   ATAK — die alle **sachliche, lesbarkeits-first** gestaltet sind.
5. **Das rote Alarm-Token `#cc2222` auf `#0f1209`** liefert Kontrast
   3.5 : 1 — **fail für WCAG 2.2 AA bei normalem Text**. Muss auf
   `#e84848` (5.8 : 1) oder heller angehoben werden.
6. **Touch-Target-Größen** sind in Voice-Command-Chips & Primary-CTAs
   unter 32 × 32 px → fail für SC 2.5.8 (Minimum 24 × 24, Best Practice
   44 × 44).

**Kern-Empfehlung**: Von „Informationsdichte um jeden Preis" auf
**Progressive Disclosure + Strategic Minimalism** umsteigen. Typografie-
Basis auf **16 px Body / 14 px absolutes Minimum** hochziehen.
Triage-Counter als **32-px-Zahlen**. Font-Stack von Rajdhani/Share Tech
Mono auf **Inter + JetBrains Mono** migrieren (bessere x-Height,
lesbarer bei hohem PPI).

Geschätzter Aufwand: **20 h (2–3 Arbeitstage)** in 6 Stufen, mit
sinnvollen Zwischen-Commits nach jeder Stufe.

---

## 1. Gemessener Ist-Zustand

### 1.1 Font-Size-Distribution im CSS

Über `grep -oE "font-size:\s*[0-9]+px" templates/index.html` gezählt:

| Pixel-Wert | Anzahl Deklarationen | Anteil |
|-----------:|---------------------:|-------:|
| **8 px**   | 6                    | 2.1 %  |
| **9 px**   | 47                   | 16.6 % |
| **10 px**  | 81                   | 28.6 % |
| **11 px**  | 61                   | 21.6 % |
| **12 px**  | 39                   | 13.8 % |
| **13 px**  | 9                    | 3.2 %  |
| **14 px**  | 14                   | 4.9 %  |
| **16 px**  | 14                   | 4.9 %  |
| **17–56 px** | 12                 | 4.3 %  |
| **Summe**  | 283                  | 100 %  |

- **81 % aller Font-Size-Deklarationen liegen bei 8–12 px.**
- Die dominanteste einzelne Schriftgröße ist **10 px** (28.6 %).
- 13 px (WCAG-Mindeststandard „klein") kommt nur 9× vor.

### 1.2 DOM-Messungen zur Laufzeit

Bei `viewport 2560×1271, devicePixelRatio 1.5` (entspricht dem Surface-Setup) sind auf der **Home-Page** folgende Elemente sichtbar:

| Element | Gemessene fontSize | Kritikalität |
|---|---|---|
| Header: Sprachgestützte Assistenz-Subtitle | **9 px** | hoch — ist Produkt-Beschreibung |
| Header: BAT Alpha42 (Unit-Name) | **10 px** | hoch — Identifikation des Geräts |
| Header: CGI Wordmark | 28 px | OK |
| Header: SAFIR Name | 18 px | OK |
| Topbar: Sprache aktiv-Chip | **10 px** | hoch |
| Topbar: 2 Teilnehmer-Chip | **10 px** | hoch |
| Sidebar: Nav-Separator "Rettungskette" / "Verwaltung" | **9 px** | hoch — strukturiert Navigation |
| Sidebar: Footer-Badge „SAFIR v2.1 · CGI Deutschland · AFCEA 2026" | **9 px** | mittel |
| Sidebar: Nav-Label „Start" / „Patienten" / „Dokumente" | **13 px** | Grenzwertig |
| Home-Hero „SAFIR" | ~48 px | OK |
| Home-Hero Subtitle | 12–13 px | mittel |

Auf **Settings → Sprachbefehle** (63 Textelemente auf einer Seite):

| Element | Gemessene fontSize | Kritikalität |
|---|---|---|
| Voice-Command-Chip „aufnahme starten" | **10 px** | **kritisch** — zentrales UI-Element |
| Button „Sprachbefehle speichern" (Primary CTA) | **11 px** | **kritisch** |
| Command-Key-Badge „record_start" etc. | **10 px** | mittel |
| Settings-Description | **12 px** | grenzwertig |
| Trigger-Group-Title „Aufnahme starten" | 12 px | grenzwertig |

Auf **Settings → Sicherheit**:

| Element | Gemessene fontSize |
|---|---|
| Kryptographie-Tabelle: „Curve25519 (ECDH)" | **11 px** |
| RFC-Referenzen „RFC 7748" | **11 px** |
| WireGuard-Erklärtext | 12 px |

Auf **Role 1 (Leitstelle)**:

| Element | Gemessene fontSize | Kritikalität |
|---|---|---|
| Triage-Counter T1 Sofort / T2 Dringend | **10 px** | **kritisch** — primäre Leitstellen-KPI |
| Transport-Panel-Header „Eingehende Transporte" | 12 px | grenzwertig |

### 1.3 Was wir nicht haben

- **Kein zentrales Design-Token-System für Typografie.** Die 283 Font-Size-Deklarationen sind direkt als `px`-Werte in die Selektoren eingebaut. Es gibt CSS-Custom-Properties nur für Farben.
- **Keine Typografie-Skala.** Wertungen sind ad-hoc: 9, 10, 11, 12, 13, 14, 16, 18 — es gibt keinen Modular-Scale mit fixen Verhältnissen.
- **Keine rem-basierten Werte.** Alle Werte sind hart in Pixeln, was User-seitige OS-Skalierung (Accessibility-Zoom) nicht respektiert.
- **Keine responsive Font-Size-Anpassung**, z. B. via `clamp()` oder Container-Queries.
- **Sidebar operativ nur via Icons nutzbar.** Weil die Nav-Labels (13 px) knapp und die Separator-Gruppen-Labels (9 px) unleserlich sind, orientiert sich der User an Piktogrammen.

---

## 2. Warum die aktuellen Zahlen in 2026 nicht mehr tragen

Ich verweise hier später noch auf den Research-Output. Kurzgefasst die
Gründe:

### 2.1 HiDPI-Displays sind Standard geworden

Das Surface hat eine Pixeldichte von ca. **200 PPI** (vergleichbar mit
einem 14-Zoll-MacBook-Retina). Ein 10-px-Zeichen auf so einem Screen ist
physisch nur noch ca. **1.3 mm hoch**. Die Windows-/macOS-OS-Skalierung
fängt das auf der OS-Ebene üblicherweise ab (z. B. 150 % Display-
Scaling → CSS 10 px = 15 Render-Pixel), aber unsere UI rechnet das
bereits ein über `devicePixelRatio = 1.5`. Was heißt: Die 10 px sind
schon *nach* OS-Skalierung noch so klein.

### 2.2 Lese-Distanz-Rechnung

Ergonomie-Daumenregel: Mindest-Schriftgröße in mm = Leseabstand in m × 4.
Bei einer Monitor-Distanz von 0.60 m ergibt das **≥ 2.4 mm** minimum.
Bei 96 DPI entspricht das ca. **9 px** — aber mit HiDPI-Rendering und
Serifenlosen Display-Fonts wie Inter ist der faktische Cutoff eher bei
**13–14 px**, darunter geht Kontrast verloren.

### 2.3 Stress-Situations-UIs brauchen Reserven

Die SAFIR-Leitstellen-UI wird in einer Notfall-Situation benutzt, in der
Triage-Zahlen in Sekunden erfasst werden müssen. Ein T1-Counter bei
10 px ist ein **Systemfehler** — das muss eine der größten Zahlen auf
dem Screen sein, nicht eine der kleinsten.

### 2.4 Accessibility-Minimums

WCAG 2.2 AA fordert (Success Criterion 1.4.12 Text Spacing) dass Text-
Inhalte skalierbar sind bis 200 % ohne Layout-Bruch. 10-px-Text auf
200 % = 20 px — das funktioniert bei uns nicht, weil die Container
(Chips, Topbar-Badges) hart gepixelt sind.

---

## 2.5 Priorisierte Schwachstellen-Liste

Sortiert nach **Pain-Faktor = Sichtbarkeit × Nutzungshäufigkeit ×
Stress-Kritikalität**. Schwachstellen mit Pain-Faktor HOCH müssen
zuerst adressiert werden.

| # | Element | Aktuell | Pain | Begründung |
|---|---|---|---|---|
| 1 | **Triage-Counter-Werte T1/T2/T3/T4** (Role 1) | 10 px | **KRITISCH** | Primäre Leitstellen-KPI. In Sekunden erfassbar sein. Heute kleiner als das Footer-Badge. |
| 2 | **Primary-CTAs** (z. B. „Sprachbefehle speichern") | 11 px | **KRITISCH** | Haupt-Aktions-Buttons. Müssen eindeutig dominieren. |
| 3 | **Voice-Command-Chips** in Settings | 10 px | HOCH | Zentrale Konfig-UI, wird oft editiert. |
| 4 | **Header-Unit-Name „BAT Alpha42"** | 10 px | HOCH | Identifiziert das Gerät. Wichtig bei Multi-BAT-Setups. |
| 5 | **Header-Subtitle** „Sprachgestützte Assistenz…" | 9 px | HOCH | Produkt-Beschreibung, wird von Messebesuchern gelesen. |
| 6 | **Sidebar-Separator-Labels** „RETTUNGSKETTE" / „VERWALTUNG" | 9 px | HOCH | Strukturiert die gesamte Navigation. Unleserlich → Sidebar wird piktogramm-lastig. |
| 7 | **Topbar-Status-Chips** „Sprache aktiv" / „2 Teilnehmer" | 10 px | MITTEL | Status-Indikatoren, nicht zeit-kritisch aber durchgehend sichtbar. |
| 8 | **Sidebar-Nav-Labels** | 13 px | MITTEL | Grenzwertig lesbar, Label ist primär — Icon sekundär. |
| 9 | **Kryptographie-Tabelle** (Sicherheit-Page) | 11 px | MITTEL | Wird bei Demo-Talking-Points gezeigt. |
| 10 | **Footer-Badge** „SAFIR v2.1 · CGI Deutschland · AFCEA 2026" | 9 px | NIEDRIG | Akzeptabel klein, aber hart am Limit. |
| 11 | **UPPERCASE-Buttons** mit 3+ Wörtern | variiert | MITTEL | Accessibility-Problem (Worterkennung, Screen-Reader). |
| 12 | **Rotes Alarm-Token `#cc2222` Text** | 3.5 : 1 Kontrast | HOCH | WCAG-AA-fail für Body-Text. Muss auf ≥ 4.5 : 1 angehoben werden. |
| 13 | **Touch-Targets < 44 × 44** an Chips/Close-Icons | variiert | MITTEL | SC 2.5.8 Minimum ist 24×24, aber Stress-Safe ist 44×44. |

**Reihenfolge für Migration**:
- **Stufe 2 (Quick Wins)**: #1, #2, #3, #4, #5, #6, #12 → die ersten 1–2 Tage.
- **Stufe 3 (Layout-Overhaul)**: #7, #8, #13 → ergibt sich aus Topbar/Sidebar-Refactor.
- **Stufe 4 (Polish)**: #9, #10, #11.

---

## 3. Ziel-Design-System (Vorschlag)

### 3.1 Typografie-Skala (1.25 Major Third + Stress-Aufschlag)

Die Skala orientiert sich am GOV.UK-Prinzip „accessibility-first" mit
dem Research-Aufschlag für Stress-UIs (+2 px über Enterprise-Normal).
Minimum-Body ist 16 px, **absolute Floor** ist 14 px — **nichts kleiner**.

| Rolle | Token | px | Line-Height | Weight | Einsatz |
|---|---|---:|---:|---:|---|
| Display | `--fs-display` | 40 | 48 | 600 | Hero/Empty-State nur |
| H1 | `--fs-h1` | 32 | 40 | 600 | Seitentitel („LAGEKARTE") |
| H2 | `--fs-h2` | 24 | 32 | 600 | Panel-Titel |
| H3 | `--fs-h3` | 20 | 28 | 600 | Karten-Header (Patient-Name) |
| Body-LG | `--fs-body-lg` | 18 | 26 | 400 | Transkripte, primäre Lesetexte |
| **Body** | `--fs-body` | **16** | **24** | 400 | Standard-Fließtext, Listen |
| Body-SM | `--fs-body-sm` | 14 | 20 | 400 | Meta-Infos — **absolutes Minimum** |
| Label | `--fs-label` | 14 | 18 | 600 | UPPERCASE-Tags, max. 2 Wörter |
| Mono-Numeric | `--fs-mono` | 16 | 24 | 500 | Vitalwerte, Koordinaten, RFID-UIDs |

**Abgleich mit aktuellen SAFIR-Größen:**

| Stelle | Aktuell | Neu | Delta |
|---|---:|---:|---:|
| Header Subtitle „Sprachgestützte Assistenz…" | 9 px | 14 px | **+5 px** |
| Header Unit-Name „BAT Alpha42" | 10 px | 16 px | **+6 px** |
| Topbar-Status-Chips | 10 px | 14 px | **+4 px** |
| Sidebar-Group-Separator „RETTUNGSKETTE" | 9 px | 14 px | **+5 px** |
| Sidebar-Nav-Labels | 13 px | 16 px | **+3 px** |
| Voice-Command-Chips | 10 px | 14 px | **+4 px** |
| Primary-CTA „Sprachbefehle speichern" | 11 px | 16 px | **+5 px** |
| Triage-Counter-Werte T1/T2/T3/T4 | 10 px | **32 px** | **+22 px** |
| Kryptographie-Tabelle | 11 px | 14 px | **+3 px** |
| Footer-Badge | 9 px | 14 px | **+5 px** |

### 3.2 Typografie-Skala für engere Viewports

Alternative für kleinere Displays (z. B. 11-Zoll-Tablets, wenn SAFIR mal mobil läuft): via `clamp(14px, 1.2vw, 16px)` dynamisch. **Aber nicht auf Kosten der Lesbarkeit**. Mindestgröße bleibt 12 px absolut.

### 3.3 Line-Height + Letter-Spacing

Aktuell ist `letter-spacing` oft **0.12em bis 0.18em** UPPERCASE (stilistisch fürs Tactical-HUD-Feeling). Das raubt Lesbarkeit bei 10-px-Text zusätzlich.

**Neue Regeln**:
- **Line-Height 1.5** für Fließtext
- **Line-Height 1.2** für Überschriften
- **Letter-Spacing**: 0em Body, 0.05em UPPERCASE-Labels (reduziert von 0.12em)
- **Text-Transform uppercase** nur noch für Labels und einzelne Status-Chips, nicht für Buttons (die werden lesbarer mit normaler Schreibweise)

### 3.4 Hierarchie-Prinzipien

**Nicht mehr "maximale Informationsdichte"**, sondern **Progressive Disclosure**:
- Pro Screen maximal 3 Hierarchie-Level sichtbar
- Rest per Klick/Hover/Scroll erreichbar
- Negative-Space ist erlaubt und erwünscht

**1-Zeilen-Faustregel pro Komponente**:
- Eine Patient-Card zeigt auf erster Ebene: Name + Triage + Zustand (das wars). Alles andere — Vitals-Details, Timeline — über Expand-Button.
- Sidebar zeigt nur Text-Label + Icon. Subtitle erst auf Hover, nicht permanent.
- Topbar zeigt Status als Icon + kurzes Wort (nicht „Sprachsteuerung aktiv im Hintergrund und empfängt Kommandos").

---

## 4. Gestaffelter Migrationsplan

### 4.1 Stufe 1 — Typografie-Tokens einführen (~3 h)

- `:root` erweitern um `--fs-display`, `--fs-h1`, ..., `--fs-micro`
- Die Tokens pro Theme überschreibbar machen (Bundeswehr-Theme könnte minimal kleiner sein falls military tighter)
- Ein globales `body { font-size: var(--fs-body); }` setzen
- Danach 283 Font-Size-Deklarationen in ~10 Runden iterieren und durch Tokens ersetzen

**Ergebnis**: Alles beim Alten, aber jetzt Design-Token-basiert. Keine visuellen Änderungen.

### 4.2 Stufe 2 — Kritische Elemente hochziehen (~4 h)

Die 5 schmerzhaftesten Stellen zuerst:

1. **Header Subtitle** 9 → 14 px
2. **Header Unit-Name** 10 → 16 px
3. **Topbar-Status-Chips** 10 → 14 px
4. **Sidebar-Nav-Labels** 13 → 15 px
5. **Sidebar-Group-Separator** 9 → 12 px (+ UPPERCASE aufheben)
6. **Triage-Counter-Werte** 10 → 32 px
7. **Voice-Command-Chips** 10 → 14 px
8. **Primary-CTAs** 11 → 16 px

Visuelle Live-Tests nach jeder Gruppe.

### 4.3 Stufe 3 — Layout-Dichte reduzieren (~6 h)

- Topbar: statt 4 Mini-Chips → 2 große Info-Panels
- Sidebar: Icons größer (24 px statt 16 px), Labels lesbar, Subtitle auf Hover
- Settings-Cards: Chip-Reihen rein visuell großzügiger
- Role1-Triage-Panel: Zahlen dominant, Labels sekundär (nicht wie heute umgekehrt)
- Patient-Cards in Phase 0: zweispaltig großzügig, Expand-Button für Details

### 4.4 Stufe 4 — Component-Polish (~4 h)

- Touch-Targets mind. 44×44 px (Buttons, Nav-Items, Chips)
- Hover-States mit deutlicheren Farb-Transitionen (aktuell zu subtle)
- Focus-States für Tastatur-Accessibility
- Konsistente Spacing-Skala (4, 8, 12, 16, 24, 32, 48)

### 4.5 Stufe 5 — Theme-Review (~2 h)

- Bundeswehr-Theme: Die harten 9-px-`font-size: 9px`-Overrides komplett rausnehmen und durch die Tokens ersetzen
- Saphir / Dark / Light: alle konsistent mit neuer Skala
- CGI-Rot behalten, aber mit mehr Atmung drumherum

### 4.6 Stufe 6 — Messe-Vorbereitungs-Test (~1 h)

- E2E-Demo-Run erneut durchlaufen (Latenzen sollten gleich bleiben)
- Physischer Test am Surface in 60 cm Abstand: alle Infos lesbar?
- Physischer Test mit Brillenträgern, um Accessibility zu verifizieren

**Geschätzte Gesamt-Aufwand**: 20 h = 2–3 Arbeitstage. Das ist ein großer Brocken — aber vor der AFCEA-Messe entscheidend.

---

## 5. Risiken + Open Decisions

### 5.1 Risiken

- **Visueller Bruch**: Wenn wir Font-Size-Tokens einziehen und nicht alle Stellen konsistent migrieren, bekommen wir hässliche Größen-Sprünge. → Mitigation: Token-Migration in **einem** Commit, möglichst atomar.
- **Layout-Überlauf**: Größere Schriften bedeuten mehr Fläche. Topbar und Sidebar müssen entsprechend mehr Platz bekommen. → Mitigation: `overflow: hidden` ersetzen durch `overflow: auto` in Containern.
- **Zeitdruck vs. Messe**: Die Messe ist in 3 Wochen. Die aktuelle UI funktioniert, aber ist suboptimal. → User-Entscheidung nötig ob wir das **komplett** machen oder nur Stufe 1+2.

### 5.2 Open Decisions für den User

1. **Scope**: Nur Font-Size-Tokens hochziehen (Stufen 1–2, ca. 7 h) oder kompletter Redesign-Pass (Stufen 1–6, ca. 20 h)?
2. **Globaler Body-Font**: Aktuell Inter (Dark-Theme). Beibehalten oder auf System-Font-Stack (sieht nativer aus, weniger Branding)?
3. **Rajdhani/Share Tech Mono im Bundeswehr-Theme**: Die Tactical-HUD-Ästhetik soll bleiben, aber Rajdhani ist bei 12 px nicht ideal. Alternative: **IBM Plex Sans** (besser lesbar bei klein, militarisch-industriell).
4. **CGI-Rot vs. Bundeswehr-Olive als Demo-Default**: Welches Theme ist primär für die Messe? Das bestimmt, welche Skala wir als „Master" tunen.
5. **Dichte-Philosophie**: „Tactical, dense, information-rich" wie jetzt — oder „Modern, spacious, progressive-disclosure"? Das ist eine Design-Grundsatzentscheidung.

---

## 6. Externe Belege (Research Stand April 2026)

### 6.1 Industrie-Standards im Vergleich (Body-Text und Sub-Labels)

| Design-System | Body | Sekundär/Label | Caption-Minimum | Line-Height Body |
|---|---|---|---|---|
| **GOV.UK** (Large Screens) | **19 px** | 16 px | 16 px | 1.32 |
| **Material 3** | 16 px | 14 px | 12 px (absolutes Minimum) | 1.5 |
| **Microsoft Fluent 2 (Web)** | 14 px | 12 px | 10 px | 1.43 |
| **Apple HIG** | 17 pt ≈ 22 px auf HiDPI | 13 pt | 11 pt (absolutes Minimum) | 1.3 |
| **IBM Carbon** | 14 px productive / 16 px expressive | 12 px | 12 px | 1.5 |
| **SAFIR aktuell** | **10–12 px** (keine definierte Base) | **9–10 px** | **8 px** | 1.0–1.4 |

**Zentrale Erkenntnis**: SAFIR liegt aktuell **unter dem Caption-Minimum
jedes der 5 großen Design-Systeme**. GOV.UK ist die beste Referenz für
uns, weil GOV.UK denselben Anspruch hat wie SAFIR — „für alle, unter
Stress, auf allen Geräten, mit Zeitdruck". GOV.UK sagt explizit:
*„Smaller font sizes (14px and below) are bad for accessibility and
should not be included as options in the typography scale."*

### 6.2 Physikalische Reading-Distance-Rechnung für das Surface

Surface 14″ @ 2400×1600 bei 200 PPI = **0.127 mm pro Pixel**. Komfort-
Mindestgröße bei 60 cm Sitzdistanz (Wissenschaftliches Komfort-Minimum:
12.5 arc minutes visueller Winkel):

- **Cap-Height ≥ 3.0 mm** = **≥ 24 px** Cap-Height
- Cap-Height typischerweise 70 % der font-size → **Font-Size ≥ 17 px**

Bei unseren aktuellen **8–10 px** Sub-Labels:
- Effektive Cap-Height 5.6–7 px = 0.7–0.9 mm
- Visueller Winkel bei 60 cm: **≈ 4.3 arc min** → **unterhalb** der
  minimalen Erkennbarkeitsschwelle von 5 arc min für 20/20-Vision.

**Das heißt**: Die 10-px-Texte sind für einen Teil der Nutzer auf diesem
Display physiologisch am Limit lesbar. Für Brillenträger oder Menschen
über 50 schon drunter.

### 6.3 WCAG 2.2 / EU Accessibility Act (EAA) — rechtliche Lage

- **WCAG 2.2 ist seit Oktober 2025 ISO/IEC 40500:2025** — internationaler
  Standard.
- **EU Accessibility Act (EAA)** trat 28. Juni 2025 in Kraft.
  Bundeswehr-Ausschreibungen ab 2026 erwarten mindestens **WCAG 2.1 AA**,
  **WCAG 2.2 AA** ist De-facto-Best-Practice.
- **Touch-Targets (SC 2.5.8, neu in WCAG 2.2)**: mindestens **24 × 24 CSS px** (AA).
  Enhanced AAA und Apple HIG: **44 × 44**.
- **Kontrast normaler Text (SC 1.4.3)**: 4.5 : 1. Unser aktuelles
  `--mil-red #cc2222` auf `#0f1209` liefert **3.5 : 1** → **fail für Text**.
  Workaround: Rot für Alarm-Text muss auf **#e84848** (5.8 : 1) angehoben werden.
- **Text-Spacing (SC 1.4.12)**: Line-Height ≥ 1.5, Paragraph-Spacing
  ≥ 2 × font-size, Letter-Spacing ≥ 0.12 × font-size, Word-Spacing
  ≥ 0.16 × font-size — alles zoomable bis 200 % ohne Layout-Bruch.

### 6.4 Tactical/Military UI Design 2026 — was Best Practice wirklich ist

**Palantir Blueprint**, **Anduril Lattice**, **Helsing Altra**,
**SitaWare Frontline**, **ATAK** — keines dieser produktiven
militärischen C2-Systeme nutzt „Tactical-HUD-Retro-Look":

- **Blueprint**: Sachliches Enterprise-Dark-Theme, Mixed Case, kein
  UPPERCASE-Zwang, Monospace nur für Zahlen/IDs.
- **Anduril Lattice**: „simple and intuitive", ruhige Flächen, große
  Klickziele, klare Trennung Map / Objects / Details.
- **Helsing Altra** (Februar 2026): „instantly readable for human
  operators" — Lesbarkeit **vor** Ästhetik.
- **SitaWare Frontline**: „for stressful environments and on touch
  devices" — große Tasten, Dropdowns, keine Tipp-Zwänge, STANAG-3345-konform.
- **ATAK/CivTAK** (US Army Standard): mobil-first, minimalistisch,
  vollständiges Figma-Design-System öffentlich.

**Bracket-Corners + Share Tech Mono + UPPERCASE überall** = findet sich
in **Spielen und Filmen** (Destiny 2, Death Stranding, The Expanse) —
nicht in produktiven militärischen Systemen. Das ist
„designed-for-camera", nicht „designed-for-operator".

### 6.5 Stress-UI-Prinzipien (Wickens-HIP-Modell, NN/G, Smashing, NIST)

Unter Stress degradiert Working Memory massiv:
- Informationsdichte **30–50 % reduzieren** gegenüber normalem Enterprise-UI.
- Schriftgrößen **+2–4 px** über normalem Normal-UI (Body 18–20 px statt 14–16 px).
- **Eine primäre Aufgabe pro View** — Progressive Disclosure für Details.
- **Line-Height ≥ 1.4** (nicht enger).
- Letter-Spacing bei UPPERCASE: **0.08–0.12 em** (nicht 0.18 em — das zerrt Worterkennung).

### 6.6 UPPERCASE-Problematik

Microsoft Writing Style Guide + Edinburgh Style Guide 2025:
*„Never use capitals … cause accessibility problems."*

- Word-Shape-Recognition geht verloren → Lesegeschwindigkeit -13 bis -20 %.
- Screen-Reader lesen UPPERCASE teils buchstabenweise vor (insb. bei < 4 Zeichen).
- Dyslexie- und Low-Vision-Nutzer doppelt betroffen.

**Regel für SAFIR**: UPPERCASE nur bei Status-Tags (max. 2 Wörter) und
Section-Headers (max. 3 Wörter). **Niemals** bei Button-Texten,
Beschreibungen, oder Texten < 14 px.

### 6.7 2026-Dashboard-Trends: Strategic Minimalism + Progressive Disclosure

- **Strategic Minimalism** (SaaSUI 2026): „every element on screen must
  earn its place by directly moving the user closer to their goal,
  otherwise it's gone."
- **Progressive Disclosure** (NN/G, IxDF): Statt „alles auf einen Blick"
  → „Essentials primary, Details on demand". Patienten-Karte zeigt Name
  + Triage + eine Leitverletzung → Klick öffnet 9-Liner/Vitals/Timeline.
- **Negative Space als Premium-Signal** (Healthcare UX 2026): Leere
  Flächen sind **kognitive Pausenräume**, nicht „verschwendeter Platz".

### 6.8 Konkrete Zahlen, mit denen SAFIR neu gebaut werden sollte

Type-Scale auf 1.25-Modular-Scale (Major Third) + GOV.UK-Aufschlag für Stress:

| Rolle | Font-Size | Line-Height | Weight | Einsatz in SAFIR |
|---|---|---|---|---|
| Display | 40 px | 48 px | 600 | Nur Splash/Empty-State |
| H1 | 32 px | 40 px | 600 | Seitentitel („LAGEKARTE") |
| H2 | 24 px | 32 px | 600 | Panel-Titel |
| H3 | 20 px | 28 px | 600 | Karten-Header (Patient-Name) |
| **Body-Large** | **18 px** | **26 px** | 400 | Transkripte, primäre Lesetexte |
| **Body** | **16 px** | **24 px** | 400 | Standard-Fließtext, Listen |
| Body-Small | 14 px | 20 px | 400 | Meta-Infos — **absolutes Minimum** |
| Label | 14 px | 18 px | 600 | UPPERCASE-Tags, max. 2 Wörter |
| Mono-Numeric | 16 px | 24 px | 500 | Vitalwerte, Koordinaten, RFID-UIDs |

**Absolutes Verbot**: nichts unter 14 px sichtbar. Für Jetson-OLED separat.

Touch-Targets:

| Element | Größe |
|---|---|
| Standard-Button | 44 × 44 px |
| Primary CTA | 56 × 56 px |
| Icon-only Button | 44 × 44 px (Icon visuell 20–24 px) |
| **Triage-Buttons Role 1** | **64 × 64 px** (stress-kritisch!) |
| Karten-Klickziel | gesamte Karte, min. 88 px Höhe |

Kontrast-Fixes:

| Token | Aktuell | Problem | Neu |
|---|---|---|---|
| --mil-red (Text) | #cc2222 | 3.5 : 1 — **fail** | **#e84848** (5.8 : 1) |
| neues Token: --mil-text-muted | — | fehlt, Opacity 0.5 willkürlich | **#8a8060** (4.6 : 1) |

Font-Stack-Empfehlungen:
- **Primary UI**: **Inter** statt Rajdhani (neutraler, bessere x-Height
  auf HiDPI). Rajdhani hat sehr kleine x-Height — wirkt auf 200 PPI
  kleiner als die px-Angabe suggeriert.
- **Monospace (Daten)**: **JetBrains Mono** oder **IBM Plex Mono** statt
  Share Tech Mono — moderner, bessere Lesbarkeit für Zahlen, gleicher
  technischer Charakter.
- `-webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility;`

### 6.9 Quellen (Auswahl)

**Design Systems**: [Fluent 2 Typography](https://fluent2.microsoft.design/typography) · [Material 3 Type-Scale](https://m3.material.io/styles/typography/type-scale-tokens) · [GOV.UK Type Scale](https://design-system.service.gov.uk/styles/type-scale/) · [Apple HIG Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility) · [IBM Carbon Typography](https://carbondesignsystem.com/elements/typography/type-sets/) · [Palantir Blueprint](https://blueprintjs.com/)

**WCAG / Accessibility**: [W3C WCAG 2.2](https://www.w3.org/TR/WCAG22/) · [SC 2.5.8 Target Size](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html) · [WCAG 2.2 als ISO/IEC 40500:2025](https://adaquickscan.com/blog/wcag-2-2-iso-standard-2025) · [WCAG Minimum Font Size](https://www.a11y-collective.com/blog/wcag-minimum-font-size/) · [BOIA: All-Caps Headings](https://www.boia.org/blog/all-caps-headings-are-they-bad-for-accessibility)

**Tactical / Defense UI**: [Anduril Lattice SDK](https://www.anduril.com/lattice-sdk/) · [Helsing Altra](https://helsing.ai/altra) · [Helsing Altra Feb 2026](https://invidis.com/news/2026/02/helsing-altra-mission-critical-digital-signage-for-the-battlefield/) · [SitaWare Frontline](https://systematic.com/int/industries/defence/products/sitaware-suite/sitaware-frontline/) · [ATAK Design System (Figma)](https://www.figma.com/community/file/1571370238280853168/atak-design-system-tactical-assault-kit-team-awareness-kit) · [Visual Logic: Warrior-Friendly Systems (eBrief)](https://info.breakingdefense.com/hubfs/BreakingDefense_UXMakingMilitarySystemsWarriorFriendly_VisualLogic_eBrief.pdf)

**Command & Control / Dashboard Trends 2026**: [SaaSUI 2026](https://www.saasui.design/blog/7-saas-ui-design-trends-2026) · [Fuselab Enterprise UX 2026](https://fuselabcreative.com/enterprise-ux-design-guide-2026-best-practices/) · [NN/G Progressive Disclosure](https://www.nngroup.com/articles/progressive-disclosure/)

**Stress UX / Cognitive Load**: [Smart Interface Design: Designing for Stress](https://smart-interface-design-patterns.com/articles/stress/) · [NIST GCR 15-996 Health IT](https://nvlpubs.nist.gov/nistpubs/gcr/2015/NIST.GCR.15-996.pdf) · [Akendi: Wickens-Model UX](https://www.akendi.com/blog/using-the-wickens-model-when-designing/)

**Typografie / Visual Acuity**: [Smashing: 16 Pixels Body Copy](https://www.smashingmagazine.com/2011/10/16-pixels-body-copy-anything-less-costly-mistake/) · [Learn UI Design: Font Size Guidelines](https://www.learnui.design/blog/mobile-desktop-website-font-size-guidelines.html) · [Inclusive Design Toolkit Text](https://www.inclusivedesigntoolkit.com/text_guidance/)
