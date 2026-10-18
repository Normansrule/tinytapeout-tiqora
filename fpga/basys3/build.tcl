# build.tcl — Tiqora-Serial bitstream for the Digilent Basys 3 (XC7A35T-1CPG236C),
# Vivado non-project mode. Run from this directory:
#     vivado -mode batch -source build.tcl
# or simply `make bit`. Vivado ML Standard (free) supports this part.
set here [file normalize [file dirname [info script]]]
set root [file normalize "$here/../.."]
set part xc7a35tcpg236-1
set out  "$here/build"
file mkdir $out


set rtl {
    src/tp_pkg.sv src/sync/sync_timebase.sv src/sync/sync_capture.sv
    src/sync/sync_event_fifo.sv src/sync/sync_compare.sv src/sync/sync_unit.sv
    src/uart/tp_uart_rx.sv src/uart/tp_uart_tx.sv src/uart/tp_host_uart.sv
    src/tp_sync_soc.sv src/tt_um_normansrule_tiqora_serial.sv fpga/basys3/basys3_top.sv
}
foreach f $rtl { read_verilog -sv "$root/$f" }
read_xdc "$here/basys3.xdc"

synth_design -top basys3_top -part $part
opt_design
place_design
phys_opt_design
route_design

report_utilization    -file "$out/utilization.txt"
report_timing_summary -file "$out/timing.txt"
set wns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
puts "worst setup slack at 50 MHz: $wns ns"
if {$wns < 0} {
    puts "ERROR: timing not met; see $out/timing.txt"
    exit 1
}
write_bitstream -force "$out/tiqora_serial_basys3.bit"
puts "wrote $out/tiqora_serial_basys3.bit — program it with: make prog"
