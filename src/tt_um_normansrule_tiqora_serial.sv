// tt_um_normansrule_tiqora_serial.sv — Tiny Tapeout submission top for
// Tiqora-Serial, the serially-controlled timestamping and trigger unit.
//
// The serial port sits on the Tiny Tapeout recommended UART pins, RX on
// ui_in[3] and TX on uo_out[4]. On the Tiny Tapeout demo board the onboard
// RP2040 bridges those two pins to the board's USB-C port, so you plug the
// board into a computer and talk to the chip — no external adapter.
//
// Pin map
// -------
//   ui_in[0]   CAP0     capture input
//   ui_in[1]   CAP1     capture input
//   ui_in[2]   CAP2     capture input
//   ui_in[3]   RX       serial receive from the host  (DEDICATED)
//   ui_in[4]   CAP3     capture input
//   ui_in[5]   CAP4     capture input
//   ui_in[6]   CAP5     capture input
//   ui_in[7]   CAP6     capture input
//
//   uo_out[0]  TRIG0    deadline trigger output
//   uo_out[1]  TRIG1    deadline trigger output
//   uo_out[2]  TRIG2    deadline trigger output
//   uo_out[3]  EVT      event queue not empty
//   uo_out[4]  TX       serial transmit to the host   (DEDICATED)
//   uo_out[5]  OVF      event queue overflowed (sticky)
//   uo_out[6]  HB       heartbeat, timebase bit 23
//   uo_out[7]  EVTP     one-clock pulse on each captured event
//
//   uio[0]     CAP7     capture input                 (input)
//   uio[1]     ACT      serial activity               (output)
//   uio[4:2]   EVCH     channel of the queued event   (output)
//   uio[5]     EVED     edge of the queued event      (output)
//   uio[7:6]   EVQ      event queue occupancy         (output)
//
// Serial: 8N1, no flow control, baud = clk_hz / 434, which is 115200 at a
// 50 MHz tile clock.
`default_nettype none

module tt_um_normansrule_tiqora_serial (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);

    wire rst = ~rst_n;

    // capture channels skip ui_in[3], which is the serial input, and take
    // the eighth channel from the bidirectional bank
    wire [7:0] cap = {uio_in[0], ui_in[7:4], ui_in[2:0]};

    wire [2:0] trig;
    wire       evt_pending, evt_pulse, ovf, heartbeat;
    wire       uart_tx, uart_active;
    wire [2:0] ev_chan;
    wire       ev_edge;
    wire [1:0] ev_count;

    tp_sync_soc #(
        .NCH(8), .NCMP(3), .DEPTH(2), .PTRW(1),
        .FRACW(24), .FILTW(0), .PWW(16), .DIV(434), .DIVW(9)
    ) u_soc (
        .clk        (clk),
        .rst        (rst),
        .cap_pin    (cap),
        .trig_pin   (trig),
        .evt_pending(evt_pending),
        .evt_pulse  (evt_pulse),
        .ovf_pin    (ovf),
        .heartbeat  (heartbeat),
        .uart_rx    (ui_in[3]),
        .uart_tx    (uart_tx),
        .uart_active(uart_active),
        .ev_chan    (ev_chan),
        .ev_edge    (ev_edge),
        .ev_count   (ev_count)
    );

    assign uo_out[0] = trig[0];
    assign uo_out[1] = trig[1];
    assign uo_out[2] = trig[2];
    assign uo_out[3] = evt_pending;
    assign uo_out[4] = uart_tx;
    assign uo_out[5] = ovf;
    assign uo_out[6] = heartbeat;
    assign uo_out[7] = evt_pulse;

    // uio[0] is an input (CAP7); the other seven are driven out
    assign uio_oe       = 8'b1111_1110;
    assign uio_out[0]   = 1'b0;
    assign uio_out[1]   = uart_active;
    assign uio_out[4:2] = ev_chan;
    assign uio_out[5]   = ev_edge;
    assign uio_out[7:6] = ev_count;

    wire _unused = &{1'b0, ena, uio_in[7:1], 1'b0};

endmodule : tt_um_normansrule_tiqora_serial
