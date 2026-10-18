#!/usr/bin/env python3
"""04_discipline.py — lock the timebase to a one-pulse-per-second source.

Feed a 1 Hz reference (a GPS module's PPS output, or a rubidium standard)
into CAP7 and this measures how far the chip's clock drifts per second,
then slews it with TRATE until the drift is gone.

Slewing rather than stepping matters: a step can make a timestamp go
backwards, and every filter downstream sees a negative time delta.

    python3 04_discipline.py /dev/ttyACM0
"""
import sys, time
sys.path.insert(0, "..")
from tpctl import Tiqora

port = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyACM0"
tp = Tiqora(port)
tp.ping()
tp.configure_capture(enable=0b1000_0000)     # CAP7 = PPS in
tp.drain()

nominal = tp.clock_hz                        # ticks we expect per second
trim_ppm = 0.0
prev = None

print("waiting for pulses on CAP7...")
for ev in tp.events(poll=0.05):
    if ev.channel != 7:
        continue
    if prev is not None:
        measured = (ev.timestamp - prev) & 0x07FFFFFF
        # the 27-bit field wraps every 2.68 s at 50 MHz, so a 1 Hz
        # reference stays unambiguous
        error_ppm = (measured - nominal) / nominal * 1e6
        trim_ppm -= error_ppm * 0.5          # half correction, for stability
        tp.trim(trim_ppm)
        print(f"interval {measured:>10} ticks   "
              f"error {error_ppm:+8.3f} ppm   trim now {trim_ppm:+8.3f} ppm")
    prev = ev.timestamp
