#!/usr/bin/env python3
"""02_selfcal_latency.py — measure the chip's own capture latency.

Wire TRIG0 (uo_out[0]) to CAP0 (ui_in[0]) with a jumper. The chip then
fires a trigger at a tick it chose and timestamps the result coming back
in, so the difference is the capture path latency: two synchroniser
clocks plus however long your wire and the pad take.

That number is a constant. Subtract it from every timestamp and your
measurements are calibrated to the pin rather than to the internal flop.
This is the whole reason a constant latency beats a small jittery one.

    python3 02_selfcal_latency.py /dev/ttyACM0
"""
import sys, statistics, time
sys.path.insert(0, "..")
from tpctl import Tiqora

port = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyACM0"
tp = Tiqora(port)
tp.ping()

tp.configure_capture(enable=0x01)       # CAP0 only, rising edge
tp.set_pulse_width(64)                  # a wide pulse is easy to catch
tp.drain()

deltas = []
for i in range(20):
    fire_at = tp.time() + tp.ticks(0.002)     # 2 ms from now
    tp.arm(0, fire_at)
    time.sleep(0.01)
    for ev in tp.drain():
        if ev.channel == 0 and ev.rising:
            # both are low 27 bits of the same timebase
            d = (ev.timestamp - (fire_at & 0x07FFFFFF)) & 0x07FFFFFF
            if d < 1000:                        # ignore anything stale
                deltas.append(d)

if not deltas:
    sys.exit("no events captured — is TRIG0 wired to CAP0?")

print(f"samples:  {len(deltas)}")
print(f"latency:  {statistics.mean(deltas):.2f} ticks "
      f"({statistics.mean(deltas) / tp.clock_hz * 1e9:.0f} ns)")
print(f"spread:   {min(deltas)} to {max(deltas)} ticks")
if min(deltas) == max(deltas):
    print("\nzero spread: the capture path is perfectly deterministic,")
    print("which is the property the chip exists to provide.")
