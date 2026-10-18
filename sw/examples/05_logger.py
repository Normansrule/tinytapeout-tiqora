#!/usr/bin/env python3
"""05_logger.py — write every event to a CSV file.

    python3 05_logger.py /dev/ttyACM0 events.csv

Columns: wall_clock, channel, edge, tick, seconds_since_rollover.

Note the sustainable rate. Every event costs a serial round trip, so at
115200 baud expect a few hundred events per second before the queue
overflows. The logger prints a warning if it does rather than silently
dropping them.
"""
import csv, sys, time
sys.path.insert(0, "..")
from tpctl import Tiqora

port = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyACM0"
path = sys.argv[2] if len(sys.argv) > 2 else "events.csv"

tp = Tiqora(port)
tp.ping()
tp.configure_capture(enable=0xFF, both_edges=True)
tp.drain()

print(f"logging to {path}, Ctrl-C to stop")
with open(path, "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["wall_clock", "source", "channel", "edge", "tick", "seconds"])
    try:
        for ev in tp.events():
            w.writerow([f"{time.time():.6f}",
                        "software" if ev.software else "capture",
                        ev.channel,
                        "rising" if ev.rising else "falling",
                        ev.timestamp,
                        f"{ev.seconds(tp.clock_hz):.9f}"])
            fh.flush()
    except KeyboardInterrupt:
        print("\nstopped")
