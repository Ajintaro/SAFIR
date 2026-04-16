#!/usr/bin/env python3
"""Phase 10 Mass-Migration: font-size: Xpx -> CSS-Token.

Ersetzt alle kleinen font-size Deklarationen im templates/index.html.
Sowohl im <style>-Block als auch in inline-styles.

Regeln:
  8–11 px -> var(--fs-body-sm)    /* 14 px */
  12–13 px -> var(--fs-body)       /* 16 px */
  14+ px  -> bleibt unveraendert
"""
import re
import sys
from pathlib import Path

SRC = Path("templates/index.html")
content = SRC.read_text(encoding="utf-8")

def replace_fontsize(match):
    px = int(match.group(1))
    if px <= 11:
        return "font-size:var(--fs-body-sm)"  # 14 px
    if px <= 13:
        return "font-size:var(--fs-body)"     # 16 px
    return match.group(0)

# Alle font-size:XXpx im GANZEN Dokument, nicht nur im <style>
# Aber: nicht in <script> Blocks (falls JS enthaelt solche Strings)
# Einfacher Ansatz: komplett global, sollte safe sein weil font-size:Xpx syntaktisch
# nur in CSS-Kontexten valide ist.

pattern = re.compile(r"font-size:[\s]*(\d+)px")

# Finde und schuetze <script>-Bloecke
script_blocks = []
def protect_script(m):
    idx = len(script_blocks)
    script_blocks.append(m.group(0))
    return f"__SCRIPT_BLOCK_{idx}__"

protected = re.sub(r"<script[^>]*>.*?</script>", protect_script, content, flags=re.DOTALL)

# Jetzt ersetzen
before_count = len(pattern.findall(protected))
new_protected = pattern.sub(replace_fontsize, protected)
after_count = len(pattern.findall(new_protected))

# Scripts zurueckholen
def restore_script(m):
    idx = int(m.group(1))
    return script_blocks[idx]
new_content = re.sub(r"__SCRIPT_BLOCK_(\d+)__", restore_script, new_protected)

SRC.write_text(new_content, encoding="utf-8")

print(f"Total font-size px-Werte (ohne <script>): {before_count}")
print(f"Davon durch Token ersetzt:                {before_count - after_count}")
print(f"Uebrig als px (14+):                      {after_count}")
