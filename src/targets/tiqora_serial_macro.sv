// tiqora_serial_macro.sv — Tiqora-Serial as a plain-pin hard macro, for any chip.
//
// The Tiny Tapeout top (tt_um_normansrule_tiqora_serial) packs the pins
// into the tile's ui/uo/uio buses. Every other tape-out target (a general
// sky130 macro, Caravel, Openframe, gf180) starts from this module instead:
// the same tp_sync_soc with the same parameters, with every signal on its
// own named pin. targets/README.md lists the targets; syn/targets/tapeout.py
// builds their configurations.
//
// Contract
//   - Identical behaviour to the Tiny Tapeout top, pin for pin, every clock:
//     test/tb_targets.sv runs both in lockstep (make targets).
//   - Serial: 8N1, baud = clk_hz / 434 (115200 at 50 MHz), as on Tiny Tapeout.
//   - No technology cells: the target's PDK and library come from its
//     target file (targets/*.toml).
//
// Cost: nothing beyond tp_sync_soc.
`default_nettype none

module tiqora_serial_macro (
`ifdef USE_POWER_PINS
    inout  wire       vccd1,           // 1.8 V core supply (Caravel naming)
    inout  wire       vssd1,           // core ground
`endif
    input  wire       clk,
    input  wire       rst_n,
    input  wire [7:0] cap_in,          // capture channels 0-7
    output wire [2:0] trig_out,        // deadline triggers
    output wire       evt_pending,     // event queue not empty
    output wire       evt_pulse,       // one clock per captured event
    output wire       ovf,             // queue overflowed (sticky)
    output wire       heartbeat,       // timebase bit 23
    input  wire       uart_rx,         // host serial in
    output wire       uart_tx,         // host serial out
    output wire       uart_active,     // serial activity
    output wire [2:0] ev_chan,         // head event: channel
    output wire       ev_edge,         // head event: edge
    output wire [1:0] ev_count         // queue occupancy
);
    tp_sync_soc #(
        .NCH(8), .NCMP(3), .DEPTH(2), .PTRW(1),
        .FRACW(24), .FILTW(0), .PWW(16), .DIV(434), .DIVW(9)
    ) u_soc (
        .clk        (clk),
        .rst        (~rst_n),
        .cap_pin    (cap_in),
        .trig_pin   (trig_out),
        .evt_pending(evt_pending),
        .evt_pulse  (evt_pulse),
        .ovf_pin    (ovf),
        .heartbeat  (heartbeat),
        .uart_rx    (uart_rx),
        .uart_tx    (uart_tx),
        .uart_active(uart_active),
        .ev_chan    (ev_chan),
        .ev_edge    (ev_edge),
        .ev_count   (ev_count)
    );
endmodule : tiqora_serial_macro
