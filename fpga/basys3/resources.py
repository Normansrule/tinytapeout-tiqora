#!/usr/bin/env python3
"""resources.py — FPGA resources for Tiqora on the Basys 3's XC7A35T,
from a Yosys `synth_xilinx` log (see `make resources`). Vivado's own report
(build/utilization.txt after `make bit`) is the final word; Yosys packs a
little differently, so expect the numbers to move by a few percent."""
import re, sys
log = open(sys.argv[1]).read()
stat = log[log.rfind("Number of cells"):] if "Number of cells" in log else log
cells = {}
for m in re.finditer(r"^\s+(\d+)\s+(\S+)\s*$|^\s+(\S+)\s+(\d+)\s*$", stat, re.M):
    n, name = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
    cells[name] = cells.get(name, 0) + int(n)
lut = sum(v for k, v in cells.items() if re.fullmatch(r"LUT[1-6]", k))
lutram = sum(v for k, v in cells.items() if k.startswith(("RAM32", "RAM64", "RAM128", "RAM256", "SRL")))
ff = sum(v for k, v in cells.items() if k in ("FDRE", "FDSE", "FDCE", "FDPE"))
b36 = cells.get("RAMB36E1", 0); b18 = cells.get("RAMB18E1", 0)
cap = {"LUT": 20800, "FF": 41600, "BRAM36": 50}
print("Tiqora-Serial on the XC7A35T (Basys 3), Yosys synth_xilinx estimate:")
print(f"  LUTs           {lut:6,d} of {cap['LUT']:,}   ({100 * lut / cap['LUT']:.1f}%)" + (f"  + {lutram} as distributed RAM/SRL" if lutram else ""))
print(f"  flip-flops     {ff:6,d} of {cap['FF']:,}   ({100 * ff / cap['FF']:.1f}%)")
print(f"  block RAM      {b36 + b18 / 2:6.1f} of {cap['BRAM36']} (36 Kb)   ({100 * (b36 + b18 / 2) / cap['BRAM36']:.1f}%)")
print(f"  carry chains   {cells.get('CARRY4', 0):6,d}    DSP slices {cells.get('DSP48E1', 0)}")
