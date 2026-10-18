#!/usr/bin/env python3
"""01_hello.py — prove the link works. Run this first.

    python3 01_hello.py /dev/ttyACM0
"""
import sys, time
sys.path.insert(0, "..")
from tpctl import Tiqora

port = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyACM0"
tp = Tiqora(port)

print("protocol version:", tp.ping())

# The timebase should advance by roughly the wall-clock time between reads.
a = tp.time()
time.sleep(0.1)
b = tp.time()
elapsed = (b - a) & 0xFFFFFFFF
print(f"timebase moved {elapsed} ticks in 100 ms")
print(f"implied clock:  {elapsed / 0.1 / 1e6:.2f} MHz")
print("status:", tp.status())

# If the implied clock is nowhere near the tile clock you configured, the
# baud rate is off: the chip's baud is clk_hz/434, so a different tile
# clock means a different baud rate on the host.
