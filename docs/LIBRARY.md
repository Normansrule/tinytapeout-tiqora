# Library: tape-out and FPGA references

Curated sources for building, checking and bringing up this design, and for taking it to other
processes. Each entry says what it is used for here. This file is identical in
tiqora-skywater130 and tinytapeout-tiqora.

## Tiny Tapeout (the path to silicon this project uses)

| Source | Use it for |
|---|---|
| [GPIO specs](https://tinytapeout.com/specs/gpio/) | pad cell (`sky130_ef_io__gpiov2_pad`), 66 MHz in / 33 MHz out, 4 mA drive, IO supply 1.71 to 5.5 V (3.3 V on the demo board), measured pad latency |
| [Clock specs](https://tinytapeout.com/specs/clock/) | clock pin (QFN-64 pin 37), ~66 MHz ceiling, up to 10 ns insertion delay |
| [Analog specs](https://tinytapeout.com/specs/analog/) | 1.8 V core (VDPWR), ground, met5 reserved for the power grid, met4 power-stripe rules |
| [FAQ](https://tinytapeout.com/faq/) | the 24 general-purpose pins, tile sizes by shuttle, extra clocks on GPIOs |
| [tt-support-tools](https://github.com/TinyTapeout/tt-support-tools) | `tech/<pdk>/tile_sizes.yaml` (die sizes), `tech/<pdk>/def/tt_block_*_pg.def` (pin positions), `precheck/` (the checks the `precheck` job runs), `docs/PINOUT.md` (64-pin QFN) |
| [tt-gds-action](https://github.com/TinyTapeout/tt-gds-action) | the `gds`, `precheck` and `gl_test` jobs; `action.yml` pins the LibreLane version (3.0.14 at `ttsky26d`) |
| [ttsky-verilog-template](https://github.com/TinyTapeout/ttsky-verilog-template) | the reference `info.yaml`, `src/config.json` and test setup this project follows |
| [tt-multiplexer](https://github.com/TinyTapeout/tt-multiplexer) | how a tile connects to the pads through the shared multiplexer |
| [Zero to ASIC course](https://www.zerotoasiccourse.com/) | the end-to-end open-source ASIC course behind Tiny Tapeout |

## SkyWater SKY130 (130 nm, this design's process)

| Source | Use it for |
|---|---|
| [SKY130 PDK documentation](https://skywater-pdk.readthedocs.io/) | design rules, layer stack, device and library overviews |
| [open_pdks](https://github.com/RTimothyEdwards/open_pdks) | builds the installed `sky130A`; commit `8afc8346` is the one Tiny Tapeout's flow used for this design; `sky130/openlane/config.tcl` has the core voltage and the slew/cap/fanout limits |
| [sky130_fd_sc_hd](https://github.com/google/skywater-pdk-libs-sky130_fd_sc_hd) | the standard-cell library: liberty timing per corner, cell layouts |
| [sky130_fd_io](https://github.com/google/skywater-pdk-libs-sky130_fd_io) | IO pad cells; `cells/top_gpiov2/sky130_fd_io__top_gpiov2.lef` gives the 80 × 200 µm GPIO pad |
| [LibreLane documentation](https://librelane.readthedocs.io/) | every flow variable in `src/config.json` (repair margins, density, routing adjustment) |
| [OpenROAD documentation](https://openroad.readthedocs.io/) | placement, clock tree, resizer, antenna and routing messages (GPL-, DPL-, GRT-, DRT-, ANT- codes) |
| [Magic](http://opencircuitdesign.com/magic/), [KLayout](https://www.klayout.de/), [Netgen](http://opencircuitdesign.com/netgen/) | DRC, layout viewing and LVS, as run by the flow and the pre-flight |
| [Yosys](https://yosyshq.readthedocs.io/), [OpenSTA](https://github.com/parallaxsw/OpenSTA) | synthesis and static timing (the area and timing targets in `test/Makefile`) |
| [OpenRAM](https://github.com/VLSIDA/OpenRAM) | SRAM macros for sky130 and gf180, if program memory moves on chip |

## Other open processes (next targets)

| Source | Use it for |
|---|---|
| [GF180MCU PDK documentation](https://gf180mcu-pdk.readthedocs.io/) and [google/gf180mcu-pdk](https://github.com/google/gf180mcu-pdk) | GlobalFoundries 180 nm; Tiny Tapeout `gf180mcuD` tiles are 346.64 × 160.72 µm (1x1) |
| [IHP-Open-PDK](https://github.com/IHP-GmbH/IHP-Open-PDK) | IHP SG13G2, 130 nm SiGe BiCMOS; Tiny Tapeout `ihp-sg13g2` tiles are 202.08 × 154.98 µm (1x1) |
| [OpenROAD-flow-scripts](https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts) | one flow with ready platforms for sky130, gf180, IHP SG13G2, Nangate45 and ASAP7: the quickest way to estimate this RTL on another node |
| [ASAP7](https://github.com/The-OpenROAD-Project/asap7) | a predictive 7 nm academic PDK (not manufacturable): area and timing trends at advanced nodes |
| [FreePDK45 / Nangate45](https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts/tree/master/flow/platforms/nangate45) | a 45 nm academic library for mid-node estimates |
| [Chipyard](https://chipyard.readthedocs.io/) and [Hammer](https://hammer-vlsi.readthedocs.io/) | Berkeley's SoC generator and its process-portable VLSI flow (used with commercial 16/22 nm and sky130); how a timing peripheral would join a larger RISC-V SoC |

## FPGA (proving the RTL before silicon)

| Source | Use it for |
|---|---|
| [Basys 3 reference manual](https://digilent.com/reference/programmable-logic/basys-3/reference-manual) | the board in `fpga/basys3`: 100 MHz oscillator, switches, LEDs, Pmod pinout, USB-UART |
| AMD 7 Series user guides: UG474 (CLB), UG472 (clocking), UG473 (block RAM), UG470 (configuration), at [docs.amd.com](https://docs.amd.com/) | Artix-7 resources behind the Basys 3 build |
| [openXC7](https://github.com/openXC7), [Project X-Ray](https://github.com/f4pga/prjxray), [nextpnr](https://github.com/YosysHQ/nextpnr) | the open bitstream flow for the Basys 3 (no Vivado) |
| [F4PGA](https://f4pga.org/) | open FPGA toolchain umbrella (Xilinx 7 series, iCE40) |
| [Project IceStorm](https://github.com/YosysHQ/icestorm) | iCE40, used by `fpga.yaml` |
| [cocotb](https://docs.cocotb.org/), [Verilator](https://verilator.org/guide/latest/), [Icarus Verilog](https://steveicarus.github.io/iverilog/) | the simulators and test framework the suites use |
| [SymbiYosys](https://symbiyosys.readthedocs.io/) | formal property checking (the proofs in PRs #12 to #14) |
| [riscv-arch-test](https://github.com/riscv-non-isa/riscv-arch-test) | the official RISC-V conformance tests (Tiqora's act target in `test/Makefile`) |

## Course and lab material (owner's archive, not in this repository)

Files in the project's shared folder; cited where they changed the docs.

| Material | Used for |
|---|---|
| EE290C/EE194 Fall 2026, Lecture 3 "FPGAs for Bringup" | FPGA as the bring-up host for a test chip; resource inference (synchronous-read memories stay portable between FPGA and ASIC); constraints and IO-cell limits. Cited in `docs/APPLICATIONS.md` |
| EE290C Lecture 1 "Intro to Bringup", Chipyard, Baremetal-IDE | bring-up practice: power, clock, reset first, then a serial path for loading code and a debug port (JTAG/DMI). Tiqora's equivalents are the UART bootloader and `TP>` prompt; it has no JTAG |
| EECS 151 ASIC and FPGA labs (riscy-business FPGA project, ASIC Lab 1) | RISC-V pipeline and FPGA timing-closure practice |
| RISC-V Rocket Chip bootcamp (2015), shuttle, chisel-labs | background on in-order RISC-V cores and SoC generators |
