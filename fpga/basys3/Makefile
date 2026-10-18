# fpga/basys3/Makefile — Tiqora-Serial on a Digilent Basys 3 (Artix-7 XC7A35T)
#   make sim         simulate the whole board design, driven like a PC drives it (~2 min)
#   make bit         build the bitstream with Vivado (WebPACK / ML Standard is free for this part)
#   make prog        program the board over USB
#   make resources   Yosys synthesis for Xilinx 7-series: LUT / FF count
SRC = ../../src
RTL = $(SRC)/tp_pkg.sv $(SRC)/sync/sync_timebase.sv $(SRC)/sync/sync_capture.sv \
      $(SRC)/sync/sync_event_fifo.sv $(SRC)/sync/sync_compare.sv $(SRC)/sync/sync_unit.sv \
      $(SRC)/uart/tp_uart_rx.sv $(SRC)/uart/tp_uart_tx.sv $(SRC)/uart/tp_host_uart.sv \
      $(SRC)/tp_sync_soc.sv $(SRC)/tt_um_normansrule_tiqora_serial.sv
.PHONY: sim bit prog resources clean
sim:
	@iverilog -g2012 -o tb_basys3.vvp -s tb_basys3 $(RTL) basys3_top.sv tb_basys3.sv 2>&1 | grep -v 'sorry:' || true
	@test -f tb_basys3.vvp
	vvp -n tb_basys3.vvp | grep -v "^VCD"
bit:
	vivado -mode batch -nojournal -nolog -source build.tcl
prog:
	vivado -mode batch -nojournal -nolog -source program.tcl
resources:
	@echo 'read_verilog -sv -DSYNTHESIS $(RTL) basys3_top.sv' > /tmp/tps_xc7.ys
	@echo 'synth_xilinx -family xc7 -top basys3_top -flatten' >> /tmp/tps_xc7.ys
	@echo 'stat' >> /tmp/tps_xc7.ys
	yosys -q -l /tmp/tps_xc7.log -s /tmp/tps_xc7.ys >/dev/null; python3 resources.py /tmp/tps_xc7.log
clean:
	rm -rf *.vvp build
