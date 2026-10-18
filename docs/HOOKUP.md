# Hooking up Tiqora-Serial

Everything you need to physically connect and talk to the chip.

---

## 1. The short version

On a Tiny Tapeout demo board, plug in the USB-C cable. That is the whole
hookup — the board's onboard RP2040 bridges the chip's serial pins to your
computer.

```bash
pip install pyserial
cd sw && python3 examples/01_hello.py /dev/ttyACM0
```

---

## 2. Voltage, before anything else

**All Tiny Tapeout I/O is 3.3 V.** A 5 V USB-to-UART adapter will put 5 V
on an input pin and can destroy the chip. Many cheap CH340 and FT232
modules ship with a jumper set to 5 V; move it to 3.3 V and check with a
meter before connecting anything.

Adapters known to be fine at 3.3 V: CP2102 modules, FT232RL with the
jumper on 3V3, the Raspberry Pi Debug Probe, and any Pmod USB-UART.

---

## 3. Option A — the demo board, nothing else needed

The demo board carries an RP2040 that is wired to every project pin and
presents itself over the USB-C connector. Its firmware can bridge a serial
port straight through to the project's UART pins, which for this chip are
the Tiny Tapeout recommended ones: RX on `ui_in[3]`, TX on `uo_out[4]`.

1. Select the project on the board (through the commander app or the
   MicroPython REPL).
2. Set the project clock. 50 MHz gives 115200 baud; see the table in
   section 6.
3. Open the serial port and run `01_hello.py`.

On Linux the board usually appears as `/dev/ttyACM0`, on macOS as
`/dev/cu.usbmodem*`, on Windows as a `COM` port. Under Windows Subsystem
for Linux (WSL2) you need `usbipd` to attach the USB device into the
distribution, or just run the Python from Windows instead.

---

## 4. Option B — your own USB-to-UART adapter

Three wires. Note that TX connects to RX and vice versa: the adapter's
transmit line drives the chip's receive pin.

```
   USB-C ─── USB-UART adapter              Tiqora-Serial
             (3.3 V !)                     on the Pmod header
             ------------                  ------------------
             TXD  ───────────────────────►  ui_in[3]    RX
             RXD  ◄───────────────────────  uo_out[4]   TX
             GND  ────────────────────────  GND
             3V3     (leave disconnected if the board is already powered)
```

Do not connect the adapter's 5 V pin to anything.

If nothing comes back, the first thing to try is swapping TXD and RXD.
That is the single most common wiring mistake and it is harmless.

---

## 5. Full pin map

| Pin | Name | Dir | What to connect |
|---|---|---|---|
| `ui[0]` | CAP0 | in | Any signal you want timestamped |
| `ui[1]` | CAP1 | in | " |
| `ui[2]` | CAP2 | in | " |
| **`ui[3]`** | **RX** | **in** | **Adapter TXD — reserved for serial** |
| `ui[4]` | CAP3 | in | Any signal you want timestamped |
| `ui[5]` | CAP4 | in | " |
| `ui[6]` | CAP5 | in | " |
| `ui[7]` | CAP6 | in | " |
| `uo[0]` | TRIG0 | out | Camera trigger, strobe, scope sync |
| `uo[1]` | TRIG1 | out | " |
| `uo[2]` | TRIG2 | out | " (fires only via the PULSE register) |
| `uo[3]` | EVT | out | Interrupt to a host; LED |
| **`uo[4]`** | **TX** | **out** | **Adapter RXD — reserved for serial** |
| `uo[5]` | OVF | out | LED. Lit means events were lost. |
| `uo[6]` | HB | out | LED. About 3 Hz at 50 MHz — proof of life. |
| `uo[7]` | EVTP | out | Scope or logic analyser trigger, one clock per event |
| `uio[0]` | CAP7 | in | Eighth timestamped input |
| `uio[1]` | ACT | out | LED. Serial activity. |
| `uio[4:2]` | EVCH | out | Logic analyser: channel of the queued event |
| `uio[5]` | EVED | out | Logic analyser: edge of that event |
| `uio[7:6]` | EVQ | out | Logic analyser: how many events are queued |

Capture channel numbers skip `ui[3]`, because that pin is the serial
input. CAP7 is on the bidirectional bank.

### Minimum viable wiring

```
   GND, 3V3          power (from the demo board)
   clk               50 MHz from the demo board
   rst_n             from the demo board
   ui_in[3]          <- adapter TXD
   uo_out[4]         -> adapter RXD
   uo_out[6]         -> LED + 1k resistor to ground   (heartbeat)
```

That is enough to run `01_hello.py`. Add capture and trigger wires as you
need them.

---

## 6. Clock and baud rate

The serial bit period is fixed at 434 chip clocks, so the baud rate
follows the clock you give the tile:

| Tile clock | Baud rate | Timestamp resolution |
|---|---|---|
| 50 MHz | 115,207 ≈ **115200** | 20 ns |
| 64 MHz | 147,465 ≈ 147,000 (non-standard) | 15.6 ns |
| 25 MHz | 57,603 ≈ **57600** | 40 ns |
| 12.5 MHz | 28,801 ≈ **28800** | 80 ns |
| 10 MHz | 23,041 (non-standard) | 100 ns |

Use 50, 25 or 12.5 MHz to land on a standard baud rate. There is no baud
divisor register on purpose: a register you can set wrong is a register
that can lock you out of the chip with no way back.

Tell the host tool the clock so it can convert ticks to seconds:

```bash
python3 tpctl.py --port /dev/ttyACM0 --clock 25000000 --baud 57600 time
```

---

## 7. Bring-up order

Work through these in order. Each one rules out a class of problem.

1. **Heartbeat.** `uo_out[6]` should blink at about 3 Hz at 50 MHz. If it
   is dead, the clock or the reset is not reaching the tile, and nothing
   else will work.
2. **Ping.** `python3 tpctl.py -p <port> ping` should print a version. If
   it times out: wrong baud, swapped TX and RX, or the wrong project
   selected on the demo board.
3. **Clock sanity.** `01_hello.py` prints an implied clock frequency from
   two timebase reads. If that is nowhere near your tile clock, your baud
   rate is wrong even though ping worked.
4. **Capture.** Enable the channels, touch a capture pin to 3.3 V, and
   check `EVT` (`uo_out[3]`) goes high. Then read the event.
5. **Trigger.** `tpctl.py -p <port> pulse 0b001` should produce a pulse on
   `uo_out[0]`. Scope it or watch an LED with a long pulse width.
6. **Self-calibration.** Jumper `uo_out[0]` to `ui_in[0]` and run
   `examples/02_selfcal_latency.py`. It measures the chip's own capture
   latency and should report zero spread.

---

## 8. Things that will bite you

**A 5 V adapter.** Covered above, and worth repeating because it is the
one mistake you cannot undo.

**Floating capture inputs.** An unconnected enabled input picks up noise
and fills the event queue. Either leave channels disabled in `CFG` or tie
unused inputs to ground.

**The queue is shallow.** Two entries. Each read is a serial round trip,
so sustained capture above a few hundred events per second will overflow
it. `OVF` on `uo_out[5]` tells you when that happens rather than letting
events vanish. For faster signals, use the `EVTP` pin with a logic
analyser and pull only the timestamps you need.

**The 27-bit timestamp wraps.** Every 2.68 s at 50 MHz. Read `TIME`
periodically and track the rollovers on the host if you need absolute
time over longer spans.

**Reading `EVENT` pops it.** There is no way to peek. Read the status
word first if you need to know whether an event is there.
