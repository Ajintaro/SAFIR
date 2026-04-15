#!/usr/bin/env python3
"""Listet alle Audio-Output-Devices die sounddevice sieht."""
import sounddevice as sd

print("=" * 72)
print("Alle Devices die sounddevice via PortAudio sieht:")
print("=" * 72)
for i, d in enumerate(sd.query_devices()):
    out = d.get("max_output_channels", 0)
    in_ = d.get("max_input_channels", 0)
    name = d.get("name", "?")
    rate = d.get("default_samplerate", 0)
    if out > 0:
        marker = "OUT"
    elif in_ > 0:
        marker = "IN "
    else:
        marker = "   "
    print(f"  [{i:>2}] {marker} ch={out}/{in_} {int(rate)}Hz  {name}")
