# Inside a gate: notes

The "Inside a gate" page (`docs/site/views.html`) shows Tiqora-Serial at four
depths (RTL, sky130 gates, transistors, layout) plus a state-machine and
connection view, all linked: choosing a register, gate, transistor or state
shows it in every view that can. This file records how it is built, how each
view is checked, and what was found on the way. Dates are when a result was
measured; every number says how it was obtained.

The page, its tools and its checks are the same files as in Tiqora
(`tiqora-skywater130`), byte for byte. Only three files are this chip's
own: `docs/views/chip.json` (top module, where the page opens, which module
the connections view starts from, the lockstep runs and the mutant targets),
`docs/views/page.html` (the words) and `test/views/tb_lockstep.sv` (the
bench). Tiqora-Serial has no processor, so there is no instruction table
(`"isa": null`), and `views_isa.py` is not in this repository.

FinFETs: SkyWater 130 nm is a planar process. The page's FinFET drawing is a
labelled comparison sketch (`illustrative` badge), not part of the chip.

## Pipeline

| stage | tool | needs | output |
|---|---|---|---|
| A | `docs/tools/views_synth.py <sc_hd dir>` | Yosys 0.33, the sky130 PDK, KLayout | `docs/views/netlist.json`, `docs/views/cells.json` |
| B | `docs/tools/views_build.py` | Python only | `docs/site/data/views.json`, `docs/site/pages/views.html` |
| site | `docs/tools/build_site.py` | Python only | `docs/site/views.html` |

Regenerate after an RTL change (stage A needs the PDK, so it runs locally):

    python3 docs/tools/views_synth.py $PDK_ROOT/sky130A/libs.ref/sky130_fd_sc_hd
    python3 docs/tools/views_build.py
    python3 docs/tools/build_site.py
    make -C test views

## How each view is checked (`make -C test views`, also `.github/workflows/views.yaml`)

Measured 2026-11-23 in the cloud container (Yosys 0.33, KLayout 0.30.14,
Icarus 12.0, Playwright 1.63.0 / Chromium):

| link | command | result |
|---|---|---|
| layout == transistors | `python3 docs/tools/views_lvs.py` | 65 cells, 615 transistors matched, 0 mismatches |
| (independent) | `python3 test/views/mini_lvs.py` | 65 cells, 615 transistors: every channel's type, W, L matches SPICE, 0 mismatches |
| transistors == liberty gate | `python3 docs/tools/views_switch.py` | 65 cells, 2,126 input states, 0 mismatches |
| gates == RTL | `make -C test views-lockstep` | 6 runs × 200,000 clocks; three with random 3-clock resets (17, 12 and 10 of them); all 24 output and enable pins equal every clock |
| diagram == behaviour | `python3 test/views/fsm_check.py` | 1,200,000 per-clock state samples, 0 errors; tp_uart_rx 10/10 edges, 4/4 states |
| page links | `python3 test/views/check_views.py` | 12,664 references, 0 errors, build is deterministic |
| page in a browser | `node test/views/page_test.js` | 167 checks: page simulator equals Python on all 2,148 states node by node; all 58 groups draw; every link, keyboard, light/dark, reduced motion, no-JS fallback |
| mutants | `python3 test/views/mutants.py` | 14 mutants (the 3 instruction-table mutants do not apply), 17 check-failures expected, 17 caught, 0 survived; the gate swap is caught at clock 5,046 of a 200,000-clock run, the inverted transmit bit at clock 4,612 |

### The lockstep bench

`test/views/tb_lockstep.sv` drives both copies with what a host really
sends, on `ui_in[3]` at the chip's 434 clocks a bit: pings, register reads,
register writes with four data bytes, stray bytes (which get a NAK), and
start-bit glitches shorter than half a bit (which must be ignored). The gaps
between commands are random, sometimes shorter than the reply. The capture
pins toggle at random.

Without resets the runs took 9 of the receiver's 10 diagram edges: the one
missing was S_DATA to S_IDLE, which only a reset causes. The three `RESETS`
runs take it, so the diagram is fully covered.

## Decisions and findings

- **One state machine, not two.** Yosys's `fsm` pass extracted and recoded
  `tp_uart_rx.state` (2 bits → 4 one-hot flip-flops). It did not extract
  `tp_host_uart.state` ("Users of register don't seem to benefit from
  recoding"), so that register is drawn as ordinary gates, not as a diagram.
  The page shows what synthesis made.
- **Hierarchical synthesis costs 15% here.** The page keeps the module
  hierarchy so a gate can be traced to its module: 24,553.5 µm², 2,871 cells.
  Flattened (`make -C test area`, re-measured 2026-11-23): 21,322 µm², 2,529
  cells. Same Yosys, same liberty, same 58 banned cells. On Tiqora the gap is
  4%; not investigated further. The page states the hierarchical number.
- **The state-encoding regex needed `\s+`.** Yosys pads the state index in
  its encoding table; the first parse of this chip found the receiver with 0
  states. Fixed in `views_synth.py` in both repositories.
- **Bugs this port found in the shared page**, fixed in both repositories:
  only the 2-pixel lines of a transistor symbol took a click (on `a211oi_1`
  the centre hit the background); and in Tiqora the connections box for a
  module inside a generate block (`g_cpu.u_core`) could not be opened. The
  connections check now wants exactly one working box per submodule, not "at
  least 3".
- **The mutant baseline now includes lockstep.** Before a mutant counts as
  caught by lockstep, the unmutated copy must pass both lockstep runs.

## Not covered

- The layout view shows standard cells, not the routed chip (that is the
  Physical design page).
- No timing, power or analog behaviour; no claim about silicon.
- Bulk terminals are left out of LVS (every PMOS body is VPB, every NMOS
  body VNB in these cells).
