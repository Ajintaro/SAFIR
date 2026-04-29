# 9-LINER MEDEVAC · SAFIR Feldkarte (Bundeswehr GSG 07/2018)

> Laminierbares A5-Dokument für Messebesucher und Feldbenutzung.
> Drucken → laminieren → bei Bedarf mit Folienstift ausfüllen.
> Alternativ: Komplette 9 Zeilen in SAFIR einsprechen, das LLM
> extrahiert automatisch die Felder (Voice-Befehl „neun liner").

> **Wichtig:** Dieses Schema folgt dem **Bundeswehr-Standard GSG 07/2018**
> und unterscheidet sich vom US-NATO-Standard ATP-3.7.2 in Codes für
> Dringlichkeit (30/60/90 Min statt 2h/4h/24h), Ausrüstung
> (Defi/Drahtschneider/San-Rucksack statt Winde/Bergung/Beatmung),
> Markierung (A=Rauch statt A=Panels) und Nationalität (A/B/D/E,
> kein C).

---

## 9-Liner MEDEVAC

| # | Feld | Inhalt | Codes / Hinweis |
|---|---|---|---|
| **Line 1** | Koordinaten / Landezone | Ortsangabe, UTM/MGRS, Markierung, „in der Nähe von …" | z. B. `32 U 12345 67890` — Stellen exakt aussprechen, **keine Quadrant-ID erfinden** |
| **Line 2** | Anprechpartner vor Ort | Funkrufname + Frequenz für MIST Report | z. B. `Frequenz Alpha 1 · Rufzeichen Sandtrop 1` |
| **Line 3** | Anzahl + Priorität | **A** = Lebensbedrohlich (30 Min) · **B** = Dringend (60 Min) · **C** = Mit Vorrang (90 Min) · **D** = Routine (24 h) · **E** = Bei Gelegenheit | Zahl + Buchstabe, z. B. `1 D` |
| **Line 4** | Besondere Ausrüstung | **A** = Keine · **B** = Defibrillator · **C** = Drahtschneider · **D** = Sanitätsrucksack · **E** = Sonstiges | bei E in Remarks namentlich nennen |
| **Line 5** | Anzahl + Transportart | **L** = Liegend · **A** = Gehfähig · **E** = Eskorte / Begleitperson | z. B. `A 1 · E 1` (1 gehfähig + 1 Begleitung) |
| **Line 6** | Militärische Sicherheit vor Ort | **N** = NO ENEMY · **P** = Possible Enemy / Gelb · **E** = Enemy in Area / Rot · **X** = Eskorte erforderlich | genau einer |
| **Line 7** | Markierung der Landezone | **A** = Rauchsignal · **B** = Pyro · **C** = Keine · **D** = Andere | Achtung: **A ist Rauch, NICHT Panels** (weicht von NATO ab) |
| **Line 8** | Anzahl + Nationalitäten | **A** = Eigene Kräfte · **B** = Verbündete Kräfte · **D** = Zivilisten · **E** = feindl. Kriegsgefangener | **kein Code „C"** in diesem Schema |
| **Line 9** | Hinweise zur Landezone | Anflugrichtung, Hindernisse, Geländebeschreibung | NICHT mehr ABC/NBC — das gehört in Remarks |
| **RE** | Remarks / Anmerkungen | CBRN-Lage, Feindlage, Patienten-Beschreibung, sonstige Zusatzinfos | alles was nicht in 1–9 passt |

---

## So sprichst du den 9-Liner in SAFIR ein

Starte mit dem Voice-Befehl **„neun liner"** (oder drücke den Taster B lang).
SAFIR erwartet danach eine zusammenhängende Ansage mit allen 9 Zeilen.
Zeilennummern explizit aussprechen hilft dem LLM beim Mapping.

### Beispiel-Diktat (für Messebesucher)

> „**Neun liner**. Abholzone bei Koordinate **32 U, 12345, 67890**, Sammelpunkt südlicher Übungsbereich. Funkkontakt Frequenz **Alpha 1**, Rufzeichen **Sandtrop 1**. Ein Patient, Kategorie **Routine**, wach, ansprechbar, keine lebensbedrohlichen Verletzungen. Keine Spezialausrüstung erforderlich, Standardtransport ausreichend. Patient **gehfähig, Begleitung empfohlen**. Abholzone **gesichert, keine unmittelbare Gefährdung**. Markierung durch Einweiser. **Eigener Soldat**, militärisch betroffen, aktuell stabil. Lageaufnahme nach Zwischenfall im Übungsbetrieb. **Keine CBRN-Gefährdung, keine Brand- oder Explosionsgefahr, keine Feindlage**. Aufnahme beenden."

### Was SAFIR daraus automatisch extrahiert

```
line1    → "32 U 12345 67890"
line2    → "Alpha 1, Sandtrop 1"
line3    → "1 D"               (Routine, 24 h)
line4    → "A"                 (Keine Spezialausrüstung)
line5    → "A1 E1"             (1 gehfähig + 1 Eskorte)
line6    → "N"                 (NO ENEMY)
line7    → "D"                 (Andere — Markierung durch Einweiser)
line8    → "1 A"               (1 Eigene Kraft)
line9    → ""                  (keine besonderen LZ-Hinweise)
remarks  → "Patient wach/ansprechbar, keine CBRN, keine Feindlage,
            aktuell stabil"
```

---

## Kurz-Referenz (Feld-Abkürzungen)

**Line 3 — Priorität (Bundeswehr):**
- `A` Lebensbedrohlich (30 Min)
- `B` Dringend (60 Min)
- `C` Mit Vorrang (90 Min)
- `D` Routine (24 h)
- `E` Bei Gelegenheit

**Line 4 — Besondere Ausrüstung:** `A` Keine · `B` Defibrillator · `C` Drahtschneider · `D` Sanitätsrucksack · `E` Sonstiges

**Line 5 — Transportart:** `L` Liegend · `A` Gehfähig · `E` Eskorte/Begleitperson

**Line 6 — Sicherheit:** `N` NO ENEMY · `P` Possible/Gelb · `E` Enemy/Rot · `X` Eskorte erforderlich

**Line 7 — Markierung LZ:** `A` Rauchsignal · `B` Pyro · `C` Keine · `D` Andere

**Line 8 — Nationalität:** `A` Eigene Kräfte · `B` Verbündete · `D` Zivilisten · `E` Feindl. Kriegsgefangener (kein C!)

**Line 9 — LZ-Hinweise:** Anflugrichtung, Hindernisse, Gelände (KEIN ABC/NBC mehr)

**Remarks (RE):** Alles weitere — CBRN, Feindlage, Patienten-Status

---

## Unterschiede zum NATO ATP-3.7.2

| Feld | NATO US | Bundeswehr GSG 07/2018 |
|---|---|---|
| L3 | A=<2h, B=Surgical, C=<4h, D=<24h, E=Convenience | A=30Min, B=60Min, C=90Min, D=24h, E=Bei Gelegenheit |
| L4 | A=Keine, B=Winde, C=Bergung, D=Beatmung | A=Keine, B=Defi, C=Drahtschneider, D=San-Rucksack, E=Sonstiges |
| L5 | L<n>, A<n> | L, A, **+E (Eskorte)** |
| L7 | A=Panels, B=Pyro, C=Rauch, D=Keine, E=Sonst. | **A=Rauch**, B=Pyro, C=Keine, D=Andere |
| L8 | A=US-Mil, B=US-Ziv, C=NATO, D=POW, E=Zivil | A=Eigene, B=Verbündete, **kein C**, D=Zivil, E=POW |
| L9 | NBC-Codes | Nur LZ-Hinweise (Anflug/Hindernisse) |
| RE | — | Remarks/Anmerkungen (NEU) |

---

*SAFIR · CGI Deutschland · AFCEA 2026 · Bundeswehr GSG 07/2018*
