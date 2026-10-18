#!/usr/bin/env python3
"""tpctl.py — host library and command-line tool for Tiqora-Serial.

Talks to the chip over any serial port: the Tiny Tapeout demo board's USB-C
connection, or a 3.3 V USB-to-UART adapter wired to two pins.

As a library:

    from tpctl import Tiqora
    tp = Tiqora("/dev/ttyACM0")
    tp.ping()
    tp.configure_capture(enable=0xFF)
    tp.arm(channel=0, at=tp.time() + 50_000)
    for ev in tp.events():
        print(ev)

As a tool:

    python3 tpctl.py --port /dev/ttyACM0 ping
    python3 tpctl.py --port /dev/ttyACM0 status
    python3 tpctl.py --port /dev/ttyACM0 watch
    python3 tpctl.py --port /dev/ttyACM0 pulse 0b001

Requires pyserial (`pip install pyserial`) for real hardware. The protocol
encoding and decoding work without it, which is what selftest exercises.
"""

from __future__ import annotations

import argparse
import struct
import sys
import time as _time
from dataclasses import dataclass

# ---------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------

CMD_WRITE = 0x01
CMD_READ  = 0x02
CMD_PING  = 0x03
RSP_ACK   = 0x06
RSP_NAK   = 0x15
RSP_MAGIC = 0x5A

# Register offsets. Identical to the full Tiqora chip.
REG_TIME  = 0    # R   32-bit timebase
REG_EVENT = 1    # R   oldest queued event; reading POPS it
REG_STAT  = 2    # R   status word
REG_CFG   = 3    # W   capture enable and edge selection
REG_CMP0  = 4    # W   arm trigger 0 at this timebase value
REG_CMP1  = 5    # W   arm trigger 1 at this timebase value
REG_PW    = 7    # W   trigger pulse width, in ticks
REG_ADJ   = 8    # W   step the timebase by a signed amount
REG_RATE  = 9    # W   fractional rate trim
REG_PULSE = 10   # W   fire trigger channels now

DEFAULT_BAUD = 115200          # clk_hz / 434, i.e. 50 MHz / 434
DEFAULT_CLOCK_HZ = 50_000_000


class TiqoraError(RuntimeError):
    pass


# ---------------------------------------------------------------------
# Decoded event
# ---------------------------------------------------------------------

@dataclass
class Event:
    """One entry from the chip's event queue."""
    software: bool      # True = a software mark, False = a hardware capture
    channel: int        # capture channel 0-7, or the software tag
    rising: bool        # edge polarity
    timestamp: int      # low 27 bits of the timebase, in ticks

    @classmethod
    def decode(cls, word: int) -> "Event":
        return cls(
            software=bool((word >> 31) & 1),
            channel=(word >> 28) & 0x7,
            rising=bool((word >> 27) & 1),
            timestamp=word & 0x07FF_FFFF,
        )

    def seconds(self, clock_hz: int = DEFAULT_CLOCK_HZ) -> float:
        """Timestamp in seconds since the last 27-bit rollover."""
        return self.timestamp / clock_hz

    def __str__(self) -> str:
        kind = "mark" if self.software else "CAP%d" % self.channel
        edge = "rising" if self.rising else "falling"
        return f"{kind:>6}  {edge:<7}  t={self.timestamp}"


@dataclass
class Status:
    """The decoded status word."""
    count: int          # events currently queued
    empty: bool
    full: bool
    overflow: bool      # an event was lost. Sticky.
    armed: int          # bit per compare channel
    triggers: int       # bit per compare channel, high while pulsing
    levels: int         # live state of the eight capture pins

    @classmethod
    def decode(cls, word: int) -> "Status":
        return cls(
            count=word & 0xF,
            empty=bool((word >> 4) & 1),
            full=bool((word >> 5) & 1),
            overflow=bool((word >> 6) & 1),
            armed=(word >> 8) & 0xF,
            triggers=(word >> 12) & 0xF,
            levels=(word >> 16) & 0xFF,
        )

    def __str__(self) -> str:
        return (f"queue {self.count}"
                f"{' EMPTY' if self.empty else ''}"
                f"{' FULL' if self.full else ''}"
                f"{'  OVERFLOW' if self.overflow else ''}"
                f"   armed 0b{self.armed:04b}"
                f"   trig 0b{self.triggers:04b}"
                f"   pins 0b{self.levels:08b}")


# ---------------------------------------------------------------------
# Frame encoding and decoding, kept free of any serial dependency so it
# can be tested without hardware
# ---------------------------------------------------------------------

def encode_write(addr: int, value: int) -> bytes:
    if not 0 <= addr <= 15:
        raise ValueError("register address must be 0-15")
    return bytes([CMD_WRITE, addr]) + struct.pack("<I", value & 0xFFFF_FFFF)


def encode_read(addr: int) -> bytes:
    if not 0 <= addr <= 15:
        raise ValueError("register address must be 0-15")
    return bytes([CMD_READ, addr])


def encode_ping() -> bytes:
    return bytes([CMD_PING])


def decode_word(data: bytes) -> int:
    if len(data) != 4:
        raise TiqoraError(f"expected 4 bytes, got {len(data)}")
    return struct.unpack("<I", data)[0]


# ---------------------------------------------------------------------
# The chip
# ---------------------------------------------------------------------

class Tiqora:
    """A Tiqora-Serial chip on a serial port.

    `transport` lets you substitute anything with read(n) and write(b)
    methods, which is how the self-test runs without hardware.
    """

    def __init__(self, port: str | None = None, baud: int = DEFAULT_BAUD,
                 clock_hz: int = DEFAULT_CLOCK_HZ, timeout: float = 1.0,
                 transport=None):
        self.clock_hz = clock_hz
        if transport is not None:
            self._io = transport
        else:
            try:
                import serial
            except ImportError:
                raise TiqoraError(
                    "pyserial is not installed. pip install pyserial") from None
            if port is None:
                raise TiqoraError("no serial port given")
            self._io = serial.Serial(port, baud, timeout=timeout)

    # -- raw access ---------------------------------------------------

    def _exchange(self, out: bytes, nreply: int) -> bytes:
        self._io.write(out)
        got = self._io.read(nreply)
        if len(got) != nreply:
            raise TiqoraError(
                f"timed out: wanted {nreply} bytes, got {len(got)}. "
                "Check the baud rate, the wiring, and that TX and RX are "
                "not swapped.")
        return got

    def ping(self) -> int:
        """Check the link. Returns the protocol version."""
        r = self._exchange(encode_ping(), 2)
        if r[0] != RSP_MAGIC:
            raise TiqoraError(
                f"bad ping reply 0x{r[0]:02X}, expected 0x{RSP_MAGIC:02X}")
        return r[1]

    def read_reg(self, addr: int) -> int:
        return decode_word(self._exchange(encode_read(addr), 4))

    def write_reg(self, addr: int, value: int) -> None:
        r = self._exchange(encode_write(addr, value), 1)
        if r[0] == RSP_NAK:
            raise TiqoraError(f"chip refused the write to register {addr}")
        if r[0] != RSP_ACK:
            raise TiqoraError(f"unexpected reply 0x{r[0]:02X} to a write")

    # -- timebase -----------------------------------------------------

    def time(self) -> int:
        """Current timebase, in ticks. One tick is one chip clock."""
        return self.read_reg(REG_TIME)

    def ticks(self, seconds: float) -> int:
        """Convert seconds to ticks at the configured clock."""
        return int(round(seconds * self.clock_hz))

    def step(self, delta_ticks: int) -> None:
        """Jump the timebase by a signed amount, in one clock.

        Coarse. Use once at startup. A step can make a timestamp appear to
        go backwards, so prefer `trim` once you are close.
        """
        self.write_reg(REG_ADJ, delta_ticks & 0xFFFF_FFFF)

    def trim(self, ppm: float) -> None:
        """Slew the timebase by `ppm` parts per million.

        Positive runs the clock fast. Resolution is about 0.06 ppm and the
        range is roughly +/- 1e6 ppm, so anything a crystal can drift by.
        Slewing never makes a timestamp go backwards, which stepping can.
        """
        mag = int(round(abs(ppm) * 1e-6 * (1 << 24)))
        if mag > 0xFF_FFFF:
            raise ValueError("trim out of range")
        word = mag | (0x8000_0000 if ppm < 0 else 0)
        self.write_reg(REG_RATE, word)

    # -- capture ------------------------------------------------------

    def configure_capture(self, enable: int = 0xFF, falling: int = 0x00,
                          both_edges: bool = False) -> None:
        """Enable capture channels and choose which edge each one captures.

        enable      bit per channel, 1 = this channel produces events
        falling     bit per channel, 1 = capture the falling edge instead
        both_edges  capture both edges on every enabled channel
        """
        word = (enable & 0xFF) | ((falling & 0xFF) << 8)
        if both_edges:
            word |= 1 << 16
        self.write_reg(REG_CFG, word)

    def status(self) -> Status:
        return Status.decode(self.read_reg(REG_STAT))

    def pop(self) -> Event | None:
        """Take the oldest event off the queue, or None if it is empty."""
        if self.status().empty:
            return None
        return Event.decode(self.read_reg(REG_EVENT))

    def drain(self) -> list[Event]:
        """Take every queued event."""
        out = []
        while True:
            st = self.status()
            if st.empty:
                return out
            out.append(Event.decode(self.read_reg(REG_EVENT)))

    def events(self, poll: float = 0.001):
        """Yield events forever, polling the queue.

        Each read is a serial round trip, so the sustainable rate is a few
        hundred events per second at 115200 baud. For faster capture, watch
        the EVTP pin with a logic analyser and use the queue for the
        timestamps you actually need.
        """
        while True:
            st = self.status()
            if st.overflow:
                print("warning: the event queue overflowed; events were lost",
                      file=sys.stderr)
            if st.empty:
                _time.sleep(poll)
                continue
            yield Event.decode(self.read_reg(REG_EVENT))

    # -- triggers -----------------------------------------------------

    def set_pulse_width(self, ticks: int) -> None:
        """Trigger output pulse width, shared by all channels."""
        self.write_reg(REG_PW, ticks)

    def arm(self, channel: int, at: int) -> None:
        """Fire trigger `channel` when the timebase reaches `at`.

        The output edge lands on that exact tick, whatever else is going
        on. Channels 0 and 1 only; channel 2 is reachable by `pulse`.
        """
        if channel == 0:
            self.write_reg(REG_CMP0, at & 0xFFFF_FFFF)
        elif channel == 1:
            self.write_reg(REG_CMP1, at & 0xFFFF_FFFF)
        else:
            raise ValueError("only channels 0 and 1 can be armed by register; "
                             "use pulse() for channel 2")

    def pulse(self, mask: int) -> None:
        """Fire the trigger channels in `mask` immediately."""
        self.write_reg(REG_PULSE, mask & 0x7)


# ---------------------------------------------------------------------
# Self-test: exercises the protocol against a model of the chip, so it
# runs with no hardware and no pyserial
# ---------------------------------------------------------------------

class _FakeChip:
    """Enough of the chip to check the host side end to end."""

    def __init__(self):
        self.regs = {REG_TIME: 1000, REG_STAT: 1 << 4, REG_EVENT: 0}
        self.writes = []
        self._out = bytearray()
        self._in = bytearray()

    def write(self, data: bytes):
        self._in += data
        while self._in:
            cmd = self._in[0]
            if cmd == CMD_PING:
                del self._in[0]
                self._out += bytes([RSP_MAGIC, 0x01])
            elif cmd == CMD_READ and len(self._in) >= 2:
                addr = self._in[1]
                del self._in[0:2]
                self._out += struct.pack("<I", self.regs.get(addr, 0))
                if addr == REG_TIME:
                    self.regs[REG_TIME] += 37      # the clock runs
            elif cmd == CMD_WRITE and len(self._in) >= 6:
                addr = self._in[1]
                val = struct.unpack("<I", bytes(self._in[2:6]))[0]
                del self._in[0:6]
                self.writes.append((addr, val))
                self._out += bytes([RSP_ACK])
            elif cmd not in (CMD_READ, CMD_WRITE, CMD_PING):
                del self._in[0]
                self._out += bytes([RSP_NAK])
            else:
                break                               # wait for more bytes

    def read(self, n: int) -> bytes:
        take = bytes(self._out[:n])
        del self._out[:n]
        return take


def selftest() -> int:
    fake = _FakeChip()
    tp = Tiqora(transport=fake, clock_hz=50_000_000)
    checks = failures = 0

    def chk(cond, name):
        nonlocal checks, failures
        checks += 1
        if cond:
            print(f"  ok    {name}")
        else:
            failures += 1
            print(f"  FAIL  {name}")

    print("\n=== tpctl self-test (no hardware) ===\n")

    chk(tp.ping() == 1, "ping returns the protocol version")

    t = tp.time()
    chk(t == 1000, "reading the timebase decodes little endian")
    chk(tp.time() > t, "successive reads see the clock advance")

    tp.configure_capture(enable=0xFF)
    chk(fake.writes[-1] == (REG_CFG, 0x0000_00FF), "capture enable encodes")

    tp.configure_capture(enable=0x0F, falling=0xF0, both_edges=True)
    chk(fake.writes[-1] == (REG_CFG, 0x0001_F00F),
        "edge selection and both-edges encode")

    tp.arm(0, 0x1234_5678)
    chk(fake.writes[-1] == (REG_CMP0, 0x1234_5678), "arming channel 0 encodes")

    tp.pulse(0b101)
    chk(fake.writes[-1] == (REG_PULSE, 0b101), "pulse mask encodes")

    tp.step(-1000)
    chk(fake.writes[-1] == (REG_ADJ, (-1000) & 0xFFFF_FFFF),
        "a negative step encodes as two's complement")

    tp.trim(1.0)
    addr, val = fake.writes[-1]
    chk(addr == REG_RATE and val == round(1e-6 * (1 << 24)),
        "a +1 ppm trim encodes to the fractional rate")
    tp.trim(-1.0)
    chk(fake.writes[-1][1] & 0x8000_0000 != 0, "a negative trim sets the sign")

    chk(tp.ticks(0.001) == 50_000, "one millisecond is 50,000 ticks at 50 MHz")

    ev = Event.decode(0x1800_0101)
    chk(not ev.software and ev.channel == 1 and ev.rising
        and ev.timestamp == 0x101, "a hardware event word decodes")
    ev = Event.decode(0xD800_0277)
    chk(ev.software and ev.channel == 5, "a software mark decodes")

    st = Status.decode((1 << 4) | (0b0001 << 8) | (0xA5 << 16))
    chk(st.empty and st.armed == 1 and st.levels == 0xA5,
        "the status word decodes")
    st = Status.decode((1 << 6) | 2)
    chk(st.overflow and st.count == 2, "overflow and queue count decode")

    fake.regs[REG_STAT] = 0
    fake.regs[REG_EVENT] = 0x1800_0101
    got = tp.pop()
    chk(got is not None and got.channel == 1, "pop returns a decoded event")
    fake.regs[REG_STAT] = 1 << 4
    chk(tp.pop() is None, "pop returns None on an empty queue")

    try:
        tp.write_reg(99, 0)
        chk(False, "an out-of-range register is rejected")
    except ValueError:
        chk(True, "an out-of-range register is rejected")

    print(f"\n{checks} checks, {failures} failures")
    print("SELF-TEST PASSED\n" if failures == 0 else "SELF-TEST FAILED\n")
    return 1 if failures else 0


# ---------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Control a Tiqora-Serial chip")
    ap.add_argument("--port", "-p", help="serial port, e.g. /dev/ttyACM0 or COM3")
    ap.add_argument("--baud", "-b", type=int, default=DEFAULT_BAUD)
    ap.add_argument("--clock", type=int, default=DEFAULT_CLOCK_HZ,
                    help="chip clock in Hz, for tick/second conversion")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("selftest", help="check the host code with no hardware")
    sub.add_parser("ping",   help="check the link")
    sub.add_parser("time",   help="read the timebase")
    sub.add_parser("status", help="read and decode the status word")
    sub.add_parser("drain",  help="print every queued event")
    sub.add_parser("watch",  help="print events as they arrive, until Ctrl-C")

    p = sub.add_parser("read", help="read a register"); p.add_argument("addr", type=int)
    p = sub.add_parser("write", help="write a register")
    p.add_argument("addr", type=int); p.add_argument("value")
    p = sub.add_parser("pulse", help="fire trigger channels now")
    p.add_argument("mask")
    p = sub.add_parser("arm", help="arm a trigger this many seconds from now")
    p.add_argument("channel", type=int); p.add_argument("seconds", type=float)
    p = sub.add_parser("capture", help="enable capture channels")
    p.add_argument("enable", help="bit mask, e.g. 0xFF")

    a = ap.parse_args(argv)

    if a.cmd == "selftest":
        return selftest()

    tp = Tiqora(a.port, a.baud, a.clock)

    if a.cmd == "ping":
        print(f"Tiqora-Serial, protocol version {tp.ping()}")
    elif a.cmd == "time":
        t = tp.time()
        print(f"{t} ticks  ({t / a.clock:.6f} s at {a.clock/1e6:g} MHz)")
    elif a.cmd == "status":
        print(tp.status())
    elif a.cmd == "read":
        print(f"0x{tp.read_reg(a.addr):08X}")
    elif a.cmd == "write":
        tp.write_reg(a.addr, int(a.value, 0)); print("ok")
    elif a.cmd == "pulse":
        tp.pulse(int(a.mask, 0)); print("ok")
    elif a.cmd == "arm":
        at = tp.time() + tp.ticks(a.seconds)
        tp.arm(a.channel, at); print(f"trigger {a.channel} armed for tick {at}")
    elif a.cmd == "capture":
        tp.configure_capture(enable=int(a.enable, 0)); print("ok")
    elif a.cmd == "drain":
        evs = tp.drain()
        print(f"{len(evs)} event(s)")
        for e in evs:
            print("  " + str(e))
    elif a.cmd == "watch":
        print("watching for events, Ctrl-C to stop")
        try:
            for e in tp.events():
                print("  " + str(e))
        except KeyboardInterrupt:
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
