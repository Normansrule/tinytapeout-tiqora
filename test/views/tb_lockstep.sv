// tb_lockstep.sv — the RTL and its sky130 gate netlist, side by side, clock by clock.
//
// Two copies of Tiqora-Serial get the same input pins. One is the RTL
// (src/*.sv). The other is the gate netlist the views page draws
// (docs/views/netlist.json, turned back into Verilog by test/views/netlist_v.py
// with every module renamed G_*; its cells are modelled from the liberty
// functions that views_switch.py has checked against the transistors).
//
// The serial input (ui_in[3]) carries real host commands at the chip's baud
// (434 clocks a bit): pings, reads and writes of random sync registers, plus
// stray bytes and short glitches that look like a start bit and are not.
// The capture pins (ui_in[7:4], ui_in[2:0], uio_in[0]) toggle at random.
//
// Every clock, all 24 output and output-enable pins must match. Any
// difference is a failure, reported with the clock it happened on.
//
// It also writes, every clock, the serial receiver's RTL state before and
// after and the gate side's one-hot flip-flops to +FSMLOG=, so
// test/views/fsm_check.py can check each step against the state diagram.
//
//   +CYCLES=<n>  +SEED=<n>  +FSMLOG=<file>
//   +RESETS (also pull rst_n low for 3 clocks at random moments, about once
//   every 16,384 clocks)
`default_nettype none
`timescale 1ns/1ps

module tb_lockstep;
    localparam int BIT = 434;            // clocks per bit, the top level's DIV
    reg clk = 1'b0, rst_n = 1'b0, ena = 1'b1;
    reg [7:0] ui_in = 8'h08;             // serial line idles high
    reg [7:0] uio_in = 8'h00;
    always #5 clk = ~clk;

    wire [7:0] r_uo, r_uio_out, r_uio_oe, g_uo, g_uio_out, g_uio_oe;
    tt_um_normansrule_tiqora_serial r (.ui_in(ui_in), .uo_out(r_uo), .uio_in(uio_in), .uio_out(r_uio_out),
                                       .uio_oe(r_uio_oe), .ena(ena), .clk(clk), .rst_n(rst_n));
    G_tt_um_normansrule_tiqora_serial g (.ui_in(ui_in), .uo_out(g_uo), .uio_in(uio_in), .uio_out(g_uio_out),
                                         .uio_oe(g_uio_oe), .ena(ena), .clk(clk), .rst_n(rst_n));

    // the serial receiver's state: 2 RTL bits, 4 one-hot gate flip-flops
    // (synthesis re-encoded it; fsm_check.py checks the hot one is the RTL state's)
    wire [1:0] r_rx = r.u_soc.u_host.u_rx.state;
    wire [3:0] g_rx = g.u_soc.u_host.u_rx.state;

    integer cycles, seed, sseed, fd, cyc, mism, steps, resets, hold, sent;
    reg [1023:0] fsmlog;
    reg [1:0] last_rx;
    reg done = 1'b0;

    // ---------------- the host: commands on ui_in[3] ----------------
    task send_byte(input [7:0] b);
        integer i;
        begin
            ui_in[3] = 1'b0; repeat (BIT) @(posedge clk);
            for (i = 0; i < 8; i = i + 1) begin ui_in[3] = b[i]; repeat (BIT) @(posedge clk); end
            ui_in[3] = 1'b1; repeat (BIT) @(posedge clk);
            sent = sent + 1;
        end
    endtask
    initial begin : host
        integer kind, k;
        sent = 0;
        if (!$value$plusargs("SEED=%d", sseed)) sseed = 1;
        sseed = sseed * 7 + 3;           // its own stream, so pin noise does not shift it
        wait (rst_n === 1'b1);
        repeat (50) @(posedge clk);
        while (!done) begin
            kind = $random(sseed) & 7;
            case (kind)
                0, 1: send_byte(8'h03);                                   // ping
                2, 3: begin send_byte(8'h02); send_byte($random(sseed) % 11); end   // read a register
                4, 5: begin                                               // write a register
                    send_byte(8'h01); send_byte($random(sseed) % 11);
                    for (k = 0; k < 4; k = k + 1) send_byte($random(sseed));
                end
                6: send_byte($random(sseed));                             // a stray byte: NAK
                default: begin                                            // a glitch shorter than half a bit
                    ui_in[3] = 1'b0; repeat (($random(sseed) & 127) + 1) @(posedge clk); ui_in[3] = 1'b1;
                end
            endcase
            repeat (($random(sseed) & 16383) + BIT) @(posedge clk);       // let the reply go out, sometimes not
        end
    end

    // ---------------- the clock-by-clock comparison ----------------
    initial begin
        if (!$value$plusargs("CYCLES=%d", cycles)) cycles = 200000;
        if (!$value$plusargs("SEED=%d", seed)) seed = 1;
        fd = 0;
        if ($value$plusargs("FSMLOG=%s", fsmlog)) fd = $fopen(fsmlog, "w");
        repeat (20) @(posedge clk);
        rst_n = 1'b1;
        mism = 0; steps = 0; resets = 0; hold = 0;
        last_rx = r_rx;
        for (cyc = 0; cyc < cycles; cyc = cyc + 1) begin
            @(negedge clk);
            if ({r_uo, r_uio_out, r_uio_oe} !== {g_uo, g_uio_out, g_uio_oe}) begin
                mism = mism + 1;
                if (mism <= 5)
                    $display("  MISMATCH clock %0d: rtl uo=%h uio=%h oe=%h rx=%0d | gates uo=%h uio=%h oe=%h rx=%b",
                             cyc, r_uo, r_uio_out, r_uio_oe, r_rx, g_uo, g_uio_out, g_uio_oe, g_rx);
            end
            if (fd != 0) $fwrite(fd, "tp_uart_rx %0d %0d %b\n", last_rx, r_rx, g_rx);
            if (last_rx !== r_rx) steps = steps + 1;
            last_rx = r_rx;
            // capture pins wiggle at random (never ui_in[3], the serial line)
            if (($random(seed) & 63) == 0) begin
                ui_in[7:4] = $random(seed); ui_in[2:0] = $random(seed); uio_in[0] = $random(seed);
            end
            if (hold > 0) begin
                hold = hold - 1;
                if (hold == 0) rst_n = 1'b1;
            end else if ($test$plusargs("RESETS") && ($random(seed) & 16383) == 0) begin
                rst_n = 1'b0; hold = 3; resets = resets + 1;
            end
        end
        done = 1'b1;
        if (fd != 0) $fclose(fd);
        $display("lockstep: %0d clocks, %0d host bytes sent, %0d receiver state changes, %0d mid-run resets, %0d mismatches",
                 cycles, sent, steps, resets, mism);
        if (mism == 0) $display("LOCKSTEP PASSED");
        else           $display("LOCKSTEP FAILED");
        $finish;
    end
endmodule
