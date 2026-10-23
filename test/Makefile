# Makefile — test and check Tiqora-Serial.
#
#   make            cocotb + Icarus, the Tiny Tapeout standard flow
#   make sim        the self-checking Icarus testbenches (no cocotb needed)
#   make lint       Verilator -Wall
#   make synth      Yosys elaboration and flip-flop count
#   make area LIB=/path/to/sky130_fd_sc_hd__tt_025C_1v80.lib
#                   REAL sky130 cell area against every tile size

SIM ?= icarus
TOPLEVEL_LANG ?= verilog
SRC = ../src

RTL  = $(SRC)/tp_pkg.sv
RTL += $(SRC)/sync/sync_timebase.sv
RTL += $(SRC)/sync/sync_capture.sv
RTL += $(SRC)/sync/sync_event_fifo.sv
RTL += $(SRC)/sync/sync_compare.sv
RTL += $(SRC)/sync/sync_unit.sv
RTL += $(SRC)/uart/tp_uart_rx.sv
RTL += $(SRC)/uart/tp_uart_tx.sv
RTL += $(SRC)/uart/tp_host_uart.sv
RTL += $(SRC)/tp_sync_soc.sv
RTL += $(SRC)/tt_um_normansrule_tiqora_serial.sv

# cocotb: RTL by default; `make GATES=yes` runs the same tests on the
# gate-level netlist that Tiny Tapeout's CI copies in after hardening.
ifneq ($(GATES),yes)
SIM_BUILD        = sim_build/rtl
VERILOG_SOURCES  = $(RTL) tb.v
else
SIM_BUILD        = sim_build/gl
COMPILE_ARGS    += -DGL_TEST -DFUNCTIONAL -DUSE_POWER_PINS -DSIM -DUNIT_DELAY=\#1
VERILOG_SOURCES  = $(PDK_ROOT)/sky130A/libs.ref/sky130_fd_sc_hd/verilog/primitives.v
VERILOG_SOURCES += $(PDK_ROOT)/sky130A/libs.ref/sky130_fd_sc_hd/verilog/sky130_fd_sc_hd.v
VERILOG_SOURCES += $(PWD)/gate_level_netlist.v tb.v
endif
COMPILE_ARGS += -g2012
TOPLEVEL = tb
COCOTB_TEST_MODULES = test

.PHONY: sim lint synth area uart tour clean-sim explorer

sim: uart tour shared docs
	@echo ""
	@echo "all testbenches finished — check for FAILED above"

uart:
	iverilog -g2012 -o tb_uart.vvp -s tb_uart $(RTL) tb_uart.sv
	vvp tb_uart.vvp

# The explorer's guided tours, recorded from this RTL at the submitted top's pins
# at 115,200 baud: every narrated step checked, the trace written to
# tour_trace.txt for docs/tools/traces.py.
tour:
	@iverilog -g2012 -o tb_tour.vvp -s tb_tour $(RTL) tb_tour.sv > tb_tour.log 2>&1 || { cat tb_tour.log; exit 1; }
	vvp -n tb_tour.vvp +TRACE=tour_trace.txt > tour_out.txt; s=$$?; cat tour_out.txt; [ $$s -eq 0 ] && grep -q "TOUR TRACE PASSED" tour_out.txt

# Two waivers, both deliberate:
#   IMPORTSTAR   file-scope `import tp_pkg::*;` is the only import form
#                Yosys's native frontend parses, and Yosys hardens the chip.
#   UNUSEDPARAM  tp_pkg is shared with the full chip and carries the RV32I
#                and Xpulse constants its core needs. This build has no
#                core, so it intentionally uses none of them.
# One waiver: tp_pkg is shared with the full chip and carries the RV32I
# and Xpulse constants its core needs. This build has no core, so it
# intentionally uses none of them.
lint:
	verilator --lint-only -Wall -Wno-UNUSEDPARAM --timing $(RTL) --top-module tt_um_normansrule_tiqora_serial

synth:
	cd .. && yosys -s syn/synth_check.ys
	@grep -E "DFF|cells" ../syn/stat.txt | head -20

area:
	cd .. && bash syn/area_sky130.sh $(LIB)

clean-sim:
	rm -f *.vvp *.vcd

COCOTB_MAKEFILES := $(shell cocotb-config --makefiles 2>/dev/null)
ifneq ($(COCOTB_MAKEFILES),)
include $(COCOTB_MAKEFILES)/Makefile.sim
endif

# every link, image, make target and script the docs mention must exist
docs:
	cd .. && python3 docs/tools/check_docs.py
	cd .. && python3 docs/tools/progress.py --check
	cd .. && python3 docs/tools/check_site.py
	cd .. && python3 docs/tools/die_map.py --check
	cd .. && python3 docs/tools/motion.py --check

# the explorer site: atlas against the RTL (needs Yosys), tours against a fresh
# simulation, then the site itself
explorer:
	@if command -v yosys > /dev/null; then cd .. && python3 docs/tools/atlas.py --check; else echo "explorer: yosys not found, atlas check skipped"; fi
	cd .. && python3 docs/tools/traces.py --check
	cd .. && python3 docs/tools/check_site.py

# The timing unit (src/sync/*.sv) is shared, byte for byte, between Tiqora and
# Tiqora-Serial. docs/shared_timing.sha256 is identical in both repositories;
# editing one copy without updating both manifests fails here.
shared:
	cd .. && sha256sum -c --quiet docs/shared_timing.sha256 && echo "shared timing unit: 5 files match the manifest"
