#!/usr/bin/env python3
"""Phase 10 Pass 2: ersetzt auch font-size in JS-Template-Strings /
inline-styles innerhalb von <script>-Bloecken.

Gleiche Regeln wie phase10_fontsize_migrate.py, aber ohne script-Schutz.
Idempotent (einmal ausgefuehrt aendert sich beim zweiten Run nichts).
"""
import re
from pathlib import Path

SRC = Path("templates/index.html")
content = SRC.read_text(encoding="utf-8")

def replace_fontsize(match):
    px = int(match.group(1))
    if px <= 11:
        return "font-size:var(--fs-body-sm)"
    if px <= 13:
        return "font-size:var(--fs-body)"
    return match.group(0)

pattern = re.compile(r"font-size:[\s]*(\d+)px")
before = len(pattern.findall(content))
new_content = pattern.sub(replace_fontsize, content)
after = len(pattern.findall(new_content))

SRC.write_text(new_content, encoding="utf-8")
print(f"Vorher: {before} px-Werte, danach: {after}, ersetzt: {before - after}")
