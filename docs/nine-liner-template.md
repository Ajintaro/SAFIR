# 9-LINER MEDEVAC · SAFIR Feldkarte

> Laminierbares A5-Dokument für Messebesucher und Feldbenutzung.
> Drucken → laminieren → bei Bedarf mit Folienstift ausfüllen.
> Alternativ: Komplette 9 Zeilen in SAFIR einsprechen, das LLM
> extrahiert automatisch die Felder (Voice-Befehl „neun liner").

---

## NATO MEDEVAC 9-Liner

| # | Feld | Inhalt | Hinweis |
|---|---|---|---|
| **Line 1** | Koordinaten Landezone | MGRS, 8- oder 10-stellig | z. B. `32U MC 1234 5678` |
| **Line 2** | Funkfrequenz / Rufzeichen | Primär- + Sekundärfrequenz, Callsign | z. B. `40.250 MHz · Alpha 2-6` |
| **Line 3** | Patienten nach Dringlichkeit | A — Urgent (<2 h), B — Urgent-Surgical, C — Priority (<4 h), D — Routine (<24 h), E — Convenience | Zahl + Buchstabe, z. B. `2 A` |
| **Line 4** | Sonderausstattung | A — Keine, B — Winde (Hoist), C — Bergungsgerät, D — Beatmungsgerät | genau einer der 4 |
| **Line 5** | Patienten Liegend/Gehfähig | `L+n` für liegend, `A+n` für gehfähig | z. B. `L 2 · A 1` |
| **Line 6** | Sicherheitslage am LZ | N — Kein Feind, P — Möglicher Feind, E — Feind im Gebiet, X — Bewaffnete Eskorte nötig | genau einer |
| **Line 7** | Markierung Landeplatz | A — Panels, B — Pyrotechnik, C — Rauch, D — Keine, E — Sonstige | genau einer |
| **Line 8** | Patient Nationalität / Status | A — US Militär, B — US Zivil, C — NATO/Verbündete, D — Gegner/POW, E — Zivilisten nicht-NATO | Mehrfach möglich |
| **Line 9** | ABC-Kontamination / Gelände | N — Nuklear, B — Biologisch, C — Chemisch; sonst Gelände-Beschreibung | Wenn keine Kontamination: Gelände (z. B. „offenes Feld, moderate Hanglage") |

---

## So sprichst du den 9-Liner in SAFIR ein

Starte mit dem Voice-Befehl **„neun liner"** (oder drücke den Taster B lang).
SAFIR erwartet danach eine zusammenhängende Ansage mit allen 9 Zeilen.
Zeilennummern explizit aussprechen hilft dem LLM beim Mapping.

### Beispiel-Diktat (für Messebesucher)

> „**Neun liner** starten. **Zeile eins** MGRS drei zwei uniform mike charlie eins zwei drei vier fünf sechs sieben acht. **Zeile zwei** Funkfrequenz vierzig komma zwei fünf null Megahertz, Rufzeichen alpha zwei sechs. **Zeile drei** zwei Patienten Dringlichkeit alpha, beide urgent. **Zeile vier** bravo, wir brauchen Winde. **Zeile fünf** beide liegend, also lima zwei. **Zeile sechs** papa, möglicher Feind im Gebiet. **Zeile sieben** charlie, wir markieren mit Rauch. **Zeile acht** charlie, NATO Kräfte. **Zeile neun** november, keine Kontamination, offenes Gelände."

### Was SAFIR daraus automatisch extrahiert

```
line1  → "32U MC 12345678"
line2  → "40.250 MHz · Alpha 2-6"
line3  → "2 A"
line4  → "B — Winde (Hoist)"
line5  → "L 2"
line6  → "P — Mögl. Feind"
line7  → "C — Rauch"
line8  → "C — NATO/Verbündete"
line9  → "N — Keine Kontamination · offenes Gelände"
```

---

## Kurz-Referenz (Feld-Abkürzungen)

**Line 3 — Dringlichkeit:**
- `A` Urgent (< 2 h)
- `B` Urgent-Surgical
- `C` Priority (< 4 h)
- `D` Routine (< 24 h)
- `E` Convenience

**Line 4 — Sonderausstattung:** `A` Keine · `B` Winde · `C` Bergung · `D` Beatmung

**Line 6 — Sicherheit:** `N` Kein Feind · `P` Möglich · `E` Feind im Gebiet · `X` Eskorte

**Line 7 — Markierung:** `A` Panels · `B` Pyro · `C` Rauch · `D` Keine · `E` Sonstige

**Line 8 — Status:** `A` US-Mil · `B` US-Ziv · `C` NATO · `D` Gegner/POW · `E` Zivilisten

**Line 9 — Kontamination:** `N` Nuklear · `B` Biologisch · `C` Chemisch · sonst Gelände

---

*SAFIR · CGI Deutschland · AFCEA 2026*
