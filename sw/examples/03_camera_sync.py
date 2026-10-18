#!/usr/bin/env python3
"""03_camera_sync.py — what the chip is actually for.

Fire a camera shutter at a fixed rate and timestamp two returning signals
against the same clock: the camera's strobe output and an inertial
measurement unit (IMU) data-ready line. Report the skew between them.

    TRIG0  uo_out[0]  ->  camera trigger in
    CAP0   ui_in[0]   <-  camera strobe out
    CAP1   ui_in[1]   <-  IMU data ready

On a microcontroller the gap between those two interrupts is tens of
microseconds and varies shot to shot, and that variance is what limits
fusion quality. Here both are timestamped in hardware.

    python3 03_camera_sync.py /dev/ttyACM0 --fps 30
"""
import argparse, sys, time
sys.path.insert(0, "..")
from tpctl import Tiqora

ap = argparse.ArgumentParser()
ap.add_argument("port", nargs="?", default="/dev/ttyACM0")
ap.add_argument("--fps", type=float, default=30.0)
ap.add_argument("--frames", type=int, default=100)
a = ap.parse_args()

tp = Tiqora(a.port)
tp.ping()
tp.configure_capture(enable=0b0000_0011)      # CAP0 strobe, CAP1 IMU
tp.set_pulse_width(tp.ticks(1e-6))            # 1 us shutter pulse
tp.drain()

period = tp.ticks(1.0 / a.fps)
next_frame = tp.time() + period

print(f"{'frame':>6}{'strobe':>12}{'imu':>12}{'skew us':>10}")
for n in range(a.frames):
    tp.arm(0, next_frame)

    # wait past the frame, then collect whatever arrived
    time.sleep(1.0 / a.fps + 0.002)
    strobe = imu = None
    for ev in tp.drain():
        if ev.channel == 0:
            strobe = ev.timestamp
        elif ev.channel == 1:
            imu = ev.timestamp

    if strobe is not None and imu is not None:
        skew = ((imu - strobe) & 0x07FFFFFF)
        if skew > 0x03FFFFFF:                 # negative, after wrap
            skew -= 0x08000000
        print(f"{n:>6}{strobe:>12}{imu:>12}{skew / tp.clock_hz * 1e6:>10.2f}")
    else:
        print(f"{n:>6}{'-' if strobe is None else strobe:>12}"
              f"{'-' if imu is None else imu:>12}{'':>10}")

    next_frame += period
