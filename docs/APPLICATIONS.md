# What Tiqora-Serial is good for

Tiqora-Serial is the timing unit of the Tiqora microcontroller with no CPU: a host computer
sends it six-byte commands over serial, and it stamps pin edges with a 20 ns tick and drives
outputs on an exact programmed tick. The timing happens in hardware; the thinking happens on
the host. Choose it when a PC, a Raspberry Pi or an existing microcontroller needs nanosecond
timing it cannot get from its own pins.

## Best uses at 130 nm today (Tiny Tapeout, sky130)

| Use | Why it fits | Limit to know |
|---|---|---|
| A USB time-interval meter for a PC (pulse widths, periods, delays between two signals) | 8 capture inputs stamped to the 20 ns clock in hardware, read back over serial | the host drains the event queue over 115,200 baud serial, so sustained event rates are limited by the serial link; bursts beyond the queue set the sticky `OVF` flag |
| Exact-tick triggers from a computer that cannot time them itself (camera, laser, DAQ, stepper pulses) | 3 deadline outputs rise on the programmed tick however late the host's next byte is | the deadline must be written before it passes; pads limit outputs to 33 MHz |
| Event logging from lab equipment, with ordering across channels | one timebase for all channels; each event carries its channel and edge | 20 ns resolution; inputs are synchronised, so each stamp lags its edge by a fixed 3 clocks |
| Teaching timing hardware without writing firmware | the protocol is the whole interface; the Python library and command-line tool are `sw/tpctl.py` | no programmability on the chip: logic beyond "stamp" and "trigger" runs on the host |

What it is not good at: anything that must react to an event faster than a serial round trip
(use the Tiqora microcontroller, which reacts on chip), or high sustained event rates.

## What it could be best at on a smaller process

None of this is measured; it is what the architecture implies.

- **Finer timestamps.** Resolution is one clock period; a faster clock gives finer stamps
  (5 ns at 200 MHz, arithmetic only). On sky130 the slowest corner has 4.68 ns of slack at
  50 MHz (measured), and the Tiny Tapeout pads cap the clock at 66 MHz.
- **A drop-in timing block for a system-on-chip.** The shared timing unit (`src/sync/`, byte
  identical to Tiqora's) is already CPU-independent: on a larger chip its register interface
  would sit on the SoC bus instead of behind the UART, as a timestamp and trigger peripheral.
- **A faster host link.** The UART is the throughput limit. On a chip with a USB or SPI device
  block, the same timing unit could stream events orders of magnitude faster.

## Portability: keeping the RTL ready for other processes

Checked on 2026-11-15 on branch `tapeout-audit`:

| Rule | State | How it was checked |
|---|---|---|
| No process-specific cells instantiated in the RTL | met: no `sky130_` instance in `src/` | `grep -rn "sky130_" src --include=*.sv` |
| No macros, no latches | met: `design__instance__area__macros: 0`, `design__inferred_latch__count: 0` | flow metrics |
| Synchronous reset only, no `initial` blocks in synthesised RTL | met | `grep -rln negedge src`, `grep -rn initial src` |
| Single clock domain; pin inputs synchronised before use | met (two-flop synchronisers in `sync_capture.sv`; the UART receive pin also has two synchroniser flops in `src/uart/tp_uart_rx.sv`) | source review |
| Sizes are parameters | channel count, comparator count, queue depth and fraction width are parameters of the shared `src/sync/` modules | `src/sync/*.sv` |
| Process-specific settings kept out of the RTL | met: `src/config.json`, `src/synth_exclude.cells`, `src/pnr_exclude.cells` and the Tiny Tapeout wrapper | file review |

To move to another process, keep `src/sync/` and the host port, replace the wrapper and the flow
configuration, re-time the pad paths, and re-run gate-level simulation with the new cells.
Tiny Tapeout already builds GF180MCU and IHP SG13G2 tiles with the same `tt-gds-action`
(`pdk:` input); tile sizes are in `tech/*/tile_sizes.yaml` of tt-support-tools.

See [MANUFACTURING.md](MANUFACTURING.md) for the sky130 facts and [LIBRARY.md](LIBRARY.md) for
guides to other processes and FPGAs.
