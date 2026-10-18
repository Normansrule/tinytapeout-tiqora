# Tiqora-Serial on a Digilent Basys 3

Run the exact 1 × 2 tile RTL on a [Digilent Basys 3](https://digilent.com/reference/programmable-logic/basys-3/start)
(Artix-7 XC7A35T). The board's USB port is the host link, so `sw/tpctl.py` talks to the FPGA
exactly as it will talk to the chip on the Tiny Tapeout demo board.

## What you need

A Basys 3, a micro-USB cable, and [Vivado ML Standard](https://www.xilinx.com/support/download.html)
(free; the XC7A35T is supported). Nothing else.

## The board, as Tiqora-Serial sees it

| Board | Pin | Function |
|---|---|---|
| 100 MHz oscillator | `clk` | divided to 50 MHz, so the serial port runs at 115,200 baud (clk / 434) |
| BTNC | reset | |
| USB serial | `ui_in[3]` RX, `uo_out[4]` TX | the host link |
| SW0–SW2 | `ui_in[0..2]` | CAP0–CAP2 |
| BTNL / BTNR / BTNU (or SW4–6) | `ui_in[4..6]` | CAP3–CAP5 |
| SW7 | `ui_in[7]` | CAP6 |
| BTND (or SW8) | `uio_in[0]` | CAP7 |
| LED 0–7 | `uo_out` | TRIG0–2, EVT, TX, OVF, HB (heartbeat), EVTP |
| LED 8 | | reset released |
| LED 9–15 | `uio_out[1..7]` | ACT and the live event-queue bits |
| 7-segment | `uo_out` · `ui_in` in hex | |

## Build, load, talk to it

```bash
cd fpga/basys3
make bit && make prog                               # Vivado: build and load (~5 min)
python3 ../../sw/tpctl.py --port /dev/ttyUSB1 ping  # second serial port of the board; COMx on Windows
python3 ../../sw/tpctl.py --port /dev/ttyUSB1 time
python3 ../../sw/tpctl.py --port /dev/ttyUSB1 --help
```

Enable a capture channel, press BTNL, and read back its timestamp to the 20 ns tick; fire a
trigger with `pulse` and watch LED 0. LED 6 (heartbeat) blinks with no host attached at all.

## Simulation, before you have a board

```bash
make sim          # about two minutes
```

The testbench drives the simulated board the way a PC drives the real one, at 115,200 baud:
ping (`5A 01`), two TIME reads that advance, a CFG write, a BTNL press read back as a
channel-3 rising event timestamped after those reads, and a PULSE seen on LED 0. **7 of 7 pass.**
`make resources` estimates about 520 LUTs (2.5%) and 420 flip-flops (1%) of the XC7A35T.

## Status

Verified here: Verilator lint, the board-level simulation, Yosys synthesis for Artix-7, and the
Tcl scripts' flow (with stand-ins for Vivado's commands). Not yet run: Vivado itself and a real
board — the first `make bit` and `make prog` are the real test.
