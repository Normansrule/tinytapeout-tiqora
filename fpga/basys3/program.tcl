# program.tcl — load build/tiqora_serial_basys3.bit into a Basys 3 over USB (JTAG).
# The board loses it at power-off; that is fine for testing.
set here [file normalize [file dirname [info script]]]
set bit  "$here/build/tiqora_serial_basys3.bit"
if {![file exists $bit]} { puts "ERROR: $bit not found. Run `make bit` first."; exit 1 }
open_hw_manager
connect_hw_server
open_hw_target
set dev [lindex [get_hw_devices xc7a35t*] 0]
if {$dev eq ""} { puts "ERROR: no XC7A35T found. Is the Basys 3 plugged in and switched on?"; exit 1 }
current_hw_device $dev
set_property PROGRAM.FILE $bit $dev
program_hw_devices $dev
close_hw_manager
puts "programmed. Talk to it at 115200 baud: python3 ../../sw/tpctl.py --port <port> ping"
