# Manufacturing facts

What Tiqora-Serial needs to be made, and where each number comes from. Every row names its source: a
file you can open, a command you can run, or a GitHub run. "Measured" means a tool reported it
for this design; "spec" means the foundry or Tiny Tapeout states it; "estimate" means it was
calculated, not measured. No chip exists yet.

Run used for the measured rows: GitHub `gds` run 43765684876, branch `tapeout-audit` at
917f982 (the speed-work stack, PRs #6, #7 and #9, plus the audit step), Tiny Tapeout
`tt-gds-action@ttsky26d`, LibreLane 3.0.14, 2026-11-15. It prints the flow's `final/metrics.json` to its log.

## The chip at a glance

| Fact | Value | Kind | Source |
|---|---|---|---|
| Process | SkyWater SKY130, 130 nm CMOS | spec | [skywater-pdk.readthedocs.io](https://skywater-pdk.readthedocs.io/) |
| PDK build | sky130A from open_pdks commit `8afc8346a57fe1ab7934ba5a6056ea8b43078e71` | measured | the run's log loads `~/.ciel/ciel/sky130/versions/8afc8346…/sky130A/libs.ref/sky130_fd_sc_hd/techlef/sky130_fd_sc_hd__nom.tlef` |
| Flow | LibreLane 3.0.14 | spec | `librelane-version` default in [tt-gds-action `action.yml`](https://github.com/TinyTapeout/tt-gds-action/blob/ttsky26d/action.yml) at tag `ttsky26d` |
| Standard cells | `sky130_fd_sc_hd` (high density), minus `src/synth_exclude.cells` and `src/pnr_exclude.cells` | measured | `src/config.json` |
| Hard macros, SRAM, analog | none: all logic, including the event queue, is standard cells | measured | `design__instance__area__macros: 0`, `…__padcells: 0` in the run's metrics |
| Tiles | 1 × 2 | spec | `info.yaml` (`tiles: "1x2"`) |
| Die area (this design) | **161.00 × 225.76 µm = 36,347 µm²** | spec + measured | Tiny Tapeout [`tech/sky130A/tile_sizes.yaml`](https://github.com/TinyTapeout/tt-support-tools/blob/main/tech/sky130A/tile_sizes.yaml) `1x2: "0 0 161.00 225.76"`; the run's `design__die__bbox` `0.0 0.0 161.0 225.76` |
| One tile | 161.00 × 111.52 µm | spec | same file, `1x1: "0 0 161.00 111.52"` |
| Core area / utilisation | 34,255 µm², 78.6% filled with logic | measured | `design__core__area`, `design__instance__utilization` |
| Standard cells placed | 3,612 (459 flip-flops), plus 2,552 fill | measured | `design__instance__count__stdcell`, `…class:sequential_cell`, `…class:fill_cell` |
| Package (whole chip) | 64-pin QFN, shared by every project on the shuttle | spec | [tt-support-tools `docs/PINOUT.md`](https://github.com/TinyTapeout/tt-support-tools/blob/main/docs/PINOUT.md): "The chip is packaged in a 64-pin QFN package"; [tinytapeout.com/specs/clock](https://tinytapeout.com/specs/clock/) "pin number 37 in the QFN-64 chip package" |

## Inputs and outputs

| Fact | Value | Kind | Source |
|---|---|---|---|
| User pins | 26: `clk`, `rst_n`, 8 `ui_in`, 8 `uo_out`, 8 bidirectional `uio` | spec | [tinytapeout.com/specs/gpio](https://tinytapeout.com/specs/gpio/) |
| Ports on this tile | 45: those 26 plus `ena`, the `uio` split into in/out/enable (24), and `VPWR`, `VGND` | measured | `design__io: 45` |
| Pins Tiqora-Serial uses | all 24 general-purpose pins, plus `clk` and `rst_n` (see [Pin audit](#pin-audit)) | measured | `info.yaml`, `src/tt_um_normansrule_tiqora_serial.sv` |
| Pad cell | `sky130_ef_io__gpiov2_pad`, a wrapper of `sky130_fd_io__top_gpiov2` | spec | [tinytapeout.com/specs/gpio](https://tinytapeout.com/specs/gpio/): "The chip uses the sky130_ef_io_gpiov2_pad macro for the I/O pads" |
| **IO cell size (pitch when abutted)** | **80.000 µm wide × 197.965 µm deep** (`sky130_ef_io__gpiov2_pad`); the bare `sky130_fd_io__top_gpiov2` is 80 × 200 µm | measured from the PDK's LEF | commands below |
| Pad pitch of the finished chip | not published by Tiny Tapeout; at least 80 µm, because neighbouring pad cells abut | open | see below |
| Pin pitch on the tile edge | 2.76 µm, pins 0.30 × 1.00 µm on metal 4, along the top edge | spec + measured | template DEF, command below; the run's log ("Wrote pin ui_in[0] at layer met4 at (138310, 224760, …)") |
| Pad speed limits | inputs up to 66 MHz, outputs up to 33 MHz, 4 mA drive, ~20 ns round trip | spec (measured by Tiny Tapeout on TT3.5) | [tinytapeout.com/specs/gpio](https://tinytapeout.com/specs/gpio/) |
| Tiqora-Serial against those limits | `clk` 50 MHz (≤ 66); outputs are decoded from registered state, so they change only after a 50 MHz clock edge and toggle at 25 MHz at most (≤ 33); UART 115,200 baud | spec of this design | `info.yaml` `clock_hz`, `README.md` |

### Where the IO cell pitch comes from

The pad cell is a library cell; its outline in the LEF file is the pitch it occupies when pads
are placed side by side. Three ways to read it, each giving the same 80 µm:

```bash
# 1. Your installed PDK. open_pdks usually merges the pad cells into one LEF; if this file
#    is missing, run: grep -rl 'MACRO sky130_ef_io__gpiov2_pad' "$PDK_ROOT/sky130A/libs.ref/sky130_fd_io"
grep -A6 'MACRO sky130_ef_io__gpiov2_pad$' "$PDK_ROOT/sky130A/libs.ref/sky130_fd_io/lef/sky130_ef_io.lef" | grep SIZE
#    SIZE 80.000 BY 197.965 ;

# 2. The open_pdks source at the exact commit the flow used.
git clone --filter=blob:none --no-checkout https://github.com/RTimothyEdwards/open_pdks.git
cd open_pdks && git sparse-checkout set --no-cone 'sky130/custom/sky130_fd_io/*'
git checkout 8afc8346a57fe1ab7934ba5a6056ea8b43078e71
grep SIZE sky130/custom/sky130_fd_io/lef/sky130_ef_io__gpiov2_pad.lef
#    SIZE 80.000 BY 197.965 ;

# 3. SkyWater's own IO library (the cell inside the wrapper).
git clone --depth 1 https://github.com/google/skywater-pdk-libs-sky130_fd_io.git
grep SIZE skywater-pdk-libs-sky130_fd_io/cells/top_gpiov2/sky130_fd_io__top_gpiov2.lef
#    SIZE 80 BY 200 ;        (commit 63752cd, 2023-02-15)
```

Methods 2 and 3 were run for this page on 2026-11-15. Method 1 depends on where your PDK is
installed (`~/pdk` on the owner's machine). The power and ground pad cells in the same
library are 75 µm wide (`sky130_fd_io__top_power_hvc_wpadv2`, `sky130_fd_io__top_ground_hvc_wpad`).

The tile's own pins are a different pitch, set by Tiny Tapeout's template:

```bash
git clone --depth 1 https://github.com/TinyTapeout/tt-support-tools.git
awk '/- ui_in\[[01]\] /{n=4} n-->0' tt-support-tools/tech/sky130A/def/tt_block_1x2_pg.def
#    + LAYER met4 ( -150 -500 ) ( 150 500 )   + PLACED ( 138460 225260 ) N    (ui_in[0])
#    + LAYER met4 ( -150 -500 ) ( 150 500 )   + PLACED ( 135700 225260 ) N    (ui_in[1])
#    138.460 − 135.700 = 2.76 µm; pins are 0.30 µm × 1.00 µm (DEF units are nm)
```

Tiny Tapeout's multiplexer connects those tile pins to the pads; nobody routes a tile pin to a
pad directly.

## Metal layers

| Fact | Value | Kind | Source |
|---|---|---|---|
| Layers in SKY130 | local interconnect (li1) and five metals (met1 to met5) | spec | `sky130_fd_sc_hd__nom.tlef` ("created 14 layers, 25 vias" in the run's log) |
| Layers Tiqora-Serial routes on | li1 (inside cells), met1, met2, met3, met4 | measured | the run's log: "Setting signal max routing layer to: met4 and clock max routing layer to met4" |
| Layer Tiqora-Serial may not use | met5: Tiny Tapeout's power grid | spec + measured | [tinytapeout.com/specs/analog](https://tinytapeout.com/specs/analog/): "You are not allowed to use the metal 5 layer"; the `precheck` job's forbidden-layer check (met5.drawing / pin / label) passed |
| Power stripes | vertical met4 stripes, 38.87 µm pitch | measured | `src/config.json` `FP_PDN_VPITCH: 38.87` |

## Power domains

| Rail | Voltage | Kind | Source |
|---|---|---|---|
| Core (`VPWR`) | 1.80 V nominal; timing is signed off at 1.60 V (slow), 1.80 V (typical) and 1.95 V (fast) | spec | `VDD_PIN_VOLTAGE "1.80"` in open_pdks `sky130/openlane/config.tcl`; the corner names `ss_100C_1v60`, `tt_025C_1v80`, `ff_n40C_1v95` in the run's metrics |
| Ground (`VGND`) | 0 V | spec | `GND_PIN_VOLTAGE "0.00"`, same file; [tinytapeout.com/specs/analog](https://tinytapeout.com/specs/analog/) "VGND: Ground rail" |
| IO supply | 3.3 V on the demo board; the pads accept 1.71 to 5.5 V; inputs are **not** 5 V tolerant | spec | [tinytapeout.com/specs/gpio](https://tinytapeout.com/specs/gpio/) |
| Power domains inside Tiqora-Serial | one (`VPWR`/`VGND`); no level shifters, no power gating | measured | the tile has two power ports; `design__power_grid_violation__count: 0` |
| Core power | 2.2 mW at the typical corner, 50 MHz | estimate | `power__total 0.00218` W: OpenSTA with its default switching activity, not a measured chip |
| Worst IR drop | 0.07 mV on `VPWR` | estimate | `design_powergrid__drop__worst__net:VPWR` (OpenROAD PDN analysis) |

## What else has to be on the chip

Tiqora-Serial is one project on the shuttle. A working chip needs all of this, none of which this repository makes:

| IP | Made by | What it does |
|---|---|---|
| Pad ring of `sky130_ef_io__gpiov2_pad` cells, power pads, ESD | SkyWater / open_pdks, placed by Tiny Tapeout | connects the die to the package |
| Tiny Tapeout multiplexer and controller | Tiny Tapeout ([tt-multiplexer](https://github.com/TinyTapeout/tt-multiplexer)) | selects one project at a time; drives `ena`; routes `clk`, `rst_n`, `ui_in`, `uo_out`, `uio` |
| Power grid on met5 | Tiny Tapeout | delivers `VPWR`/`VGND` to the tile's met4 stripes |
| 64-pin QFN package and breakout or demo board | Tiny Tapeout | the demo board's microcontroller (RP2040; RP2350 on the newer board) supplies the clock (1 Hz to 66.5 MHz), reset and USB |
| A host computer | off-chip | sends the serial commands through the demo board's USB bridge |

## Signoff checks

| Check | Result | Run |
|---|---|---|
| Routing DRC (OpenROAD) | 0 | measured, run 43765684876 |
| Magic DRC | 0 | measured, same run |
| KLayout FEOL, BEOL, off-grid, zero-area, pin-label, nwell checks | 0 errors | measured, `precheck` job of the same run ("Precheck passed") |
| LVS (netgen) | 0 errors, 0 unmatched nets/pins | measured, same run |
| Antenna | 0 violations after repair (1 diode inserted) | measured, same run |
| Setup timing, 9 corners | met everywhere; worst +4.68 ns at max_ss_100C_1v60 | measured, same run |
| Hold timing, 9 corners | met everywhere; worst +0.113 ns at min_ff_n40C_1v95 | measured, same run |
| Max slew | **950 pins over 0.75 ns at max_ss; 45 at nom_tt** | measured, same run: not yet clean, see the audit PR |
| Max capacitance | **2 nets at max_ss, by under 5%; 0 at nom_tt** | measured, same run: not yet clean |
| Max fanout | **29 clock-tree leaf buffers driving 11 to 14 flip-flops (limit 10), every corner** | measured, same run: not yet clean |
| Gate-level test | pass | measured, `gl_test` job of the same run |
| Tape-out margin audit | `syn/signoff_audit.py`: six gates, run by the `gds` workflow on branch `tapeout-audit` | see the PR |

The flow fails only on typical-corner timing (`TIMING_VIOLATION_CORNERS = *tt*` in LibreLane's
sky130 defaults), so a green `gds` job alone does not prove the slow corners or the electrical
checks. `syn/signoff_audit.py` makes those a visible gate.

## Pin audit

All 24 general-purpose pins have a function (`info.yaml`), and the public pinout is unchanged.
`uio[0]` is an input (capture channel 7); `uio[1]` to `uio[7]` are outputs (`uio_oe` =
`8'b1111_1110`), so their input halves `uio_in[7:1]` are not read, and neither is `ena` (Tiny
Tapeout holds it high while the project is selected). Those eight unread inputs are the eight
disconnected pins the flow reports; none is a critical disconnected pin
(`design__critical_disconnected_pin__count: 0`).
