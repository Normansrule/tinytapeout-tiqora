// tb_tour.sv — the explorer's guided tours, recorded from the real RTL.
//
//   cd test && make tour
//
// Drives the submitted top, tt_um_normansrule_tiqora_serial, from its pins
// only, at the silicon's own 434 clocks per bit (115,200 baud at 50 MHz),
// the way a host on the demo board's USB serial port does: ping, configure
// capture, read the time, arm a deadline, catch an edge, read the event,
// then two things a host can get wrong: an unknown command and a command cut
// off half way. Every step is checked. +TRACE=file writes one line per clock
// on which any traced signal changes (the timebase is recorded but does not
// count as a change); docs/tools/traces.py turns it into the explorer's
// fixtures.
`default_nettype none
`timescale 1ns/1ps

module tb_tour;
    localparam int DIV = 434, CLK_NS = 20, BIT_NS = DIV * CLK_NS;
    reg        clk = 1'b0, rst_n = 1'b0, ena = 1'b1;
    reg  [7:0] ui_in = 8'h08;                  // RX (ui_in[3]) idles high
    reg  [7:0] uio_in = 8'h00;
    wire [7:0] uo_out, uio_out, uio_oe;
    always #(CLK_NS/2) clk = ~clk;

    tt_um_normansrule_tiqora_serial dut (
        .ui_in(ui_in), .uo_out(uo_out), .uio_in(uio_in),
        .uio_out(uio_out), .uio_oe(uio_oe), .ena(ena), .clk(clk), .rst_n(rst_n));

    integer errors = 0, checks = 0;
    task chk(input cond, input [8*72:1] msg);
        begin
            checks = checks + 1;
            if (cond) $display("  ok    %0s", msg);
            else begin errors = errors + 1; $display("  FAIL  %0s", msg); end
        end
    endtask

    // ---------------------------------------------------------------- trace
    integer cycle = -4, fd = 0;
    reg [8*256:1] tracefile;
    reg [127:0] last = 128'd0, cur;
    always @(negedge clk) if (fd != 0) begin
        cur = {rst_n, ui_in, uo_out, uio_out, dut.u_soc.u_host.state, dut.u_soc.u_host.count,
               dut.u_soc.u_host.rx_valid, dut.u_soc.u_host.rx_data, dut.u_soc.u_host.tx_busy,
               dut.u_soc.u_host.reg_req, dut.u_soc.u_host.reg_addr, dut.u_soc.u_sync.u_fifo.count,
               dut.u_soc.u_sync.u_cmp.armed, dut.u_soc.u_sync.fifo_ovf};
        if (cur != last || cycle == -4)
            $fwrite(fd, "%0d %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",
                cycle, rst_n, ui_in, uo_out, uio_out[1], uio_out[7:6], uio_out[4:2], uio_out[5], dut.u_soc.u_host.state, dut.u_soc.u_host.count,
                dut.u_soc.u_host.rx_valid, dut.u_soc.u_host.rx_data, dut.u_soc.u_host.tx_busy,
                dut.u_soc.u_host.reg_req, dut.u_soc.u_host.reg_addr, dut.u_soc.u_sync.u_fifo.count,
                dut.u_soc.u_sync.u_cmp.armed, dut.u_soc.u_sync.fifo_ovf, dut.u_soc.u_sync.now,
                dut.u_soc.u_sync.u_cmp.deadline[0]);
        last = cur;
    end
    always @(posedge clk) if (rst_n) cycle <= cycle + 1;

    // ---------------------------------------------------------------- host
    task send_byte(input [7:0] b);
        integer i;
        begin
            ui_in[3] = 1'b0; #(BIT_NS);
            for (i = 0; i < 8; i = i + 1) begin ui_in[3] = b[i]; #(BIT_NS); end
            ui_in[3] = 1'b1; #(BIT_NS);
        end
    endtask

    // receive one byte from uo_out[4], or time out after `bits` bit times
    task recv_byte(output [7:0] b, output ok, input integer bits);
        integer i, waited;
        begin
            ok = 1'b0; waited = 0; b = 8'h00;
            while (uo_out[4] === 1'b1 && waited < bits * DIV) begin @(posedge clk); waited = waited + 1; end
            if (uo_out[4] === 1'b0) begin
                #(BIT_NS / 2);
                for (i = 0; i < 8; i = i + 1) begin #(BIT_NS); b[i] = uo_out[4]; end
                #(BIT_NS);
                ok = (uo_out[4] === 1'b1);
            end
        end
    endtask

    task write_reg(input [3:0] a, input [31:0] v, output [7:0] r, output ok);
        begin
            send_byte(8'h01); send_byte({4'h0, a});
            send_byte(v[7:0]); send_byte(v[15:8]); send_byte(v[23:16]); send_byte(v[31:24]);
            recv_byte(r, ok, 40);
        end
    endtask

    task read_reg(input [3:0] a, output [31:0] v, output ok);
        reg [7:0] b0, b1, b2, b3; reg k0, k1, k2, k3;
        begin
            send_byte(8'h02); send_byte({4'h0, a});
            recv_byte(b0, k0, 40); recv_byte(b1, k1, 40); recv_byte(b2, k2, 40); recv_byte(b3, k3, 40);
            v = {b3, b2, b1, b0}; ok = k0 && k1 && k2 && k3;
        end
    endtask

    // ---------------------------------------------------------------- pin monitor
    integer trig_rise = -1, trig_width = 0, evtp = 0;
    reg [31:0] at_rise_now, at_rise_deadline;
    always @(negedge clk) if (rst_n) begin
        if (uo_out[0] && trig_rise < 0) begin
            trig_rise = cycle;
            at_rise_now = dut.u_soc.u_sync.now; at_rise_deadline = dut.u_soc.u_sync.u_cmp.deadline[0];
        end
        if (uo_out[0]) trig_width = trig_width + 1;
        if (uo_out[7]) evtp = evtp + 1;
    end

    // watchdog: a design that never answers must fail, not hang
    initial begin
        #(20_000_000);
        $display("  FAIL  watchdog: the tour did not finish in 20,000,000 ns");
        $display("TOUR TRACE FAILED");
        $finish;
    end

    reg [7:0] r, r2; reg ok, ok2;
    reg [31:0] t0, ev, st;
    integer edge_cycle;
    initial begin
        if ($value$plusargs("TRACE=%s", tracefile)) fd = $fopen(tracefile, "w");
        if (fd != 0) $fwrite(fd, "cycle rst_n ui_in uo_out act evq evch eved h_state h_count rx_valid rx_data tx_busy reg_req reg_addr qcount armed ovf now deadline0\n");
        repeat (4) @(posedge clk);
        rst_n = 1'b1;
        repeat (20) @(posedge clk);

        send_byte(8'h03); recv_byte(r, ok, 40); recv_byte(r2, ok2, 40);
        chk(ok && ok2 && r == 8'h5A && r2 == 8'h01, "ping 0x03 answers 0x5A, version 0x01");

        write_reg(4'h3, 32'h0000_0001, r, ok);
        chk(ok && r == 8'h06, "write CFG = 1 (capture channel 0, rising) answers ACK 0x06");

        read_reg(4'h0, t0, ok);
        chk(ok && t0 != 0, "read TIME returns the timebase, least significant byte first");

        write_reg(4'h4, t0 + 32'd60000, r, ok);
        chk(ok && r == 8'h06, "write CMP0 = TIME + 60000 answers ACK");
        while (trig_rise < 0) @(posedge clk);
        repeat (20) @(posedge clk);
        chk(at_rise_now == at_rise_deadline && at_rise_deadline == t0 + 32'd60000,
            "TRIG0 (uo_out[0]) rises on exactly the deadline tick");
        chk(trig_width == 8, "TRIG0 pulse is 8 ticks wide at the pin");

        @(posedge clk); ui_in[0] = 1'b1; edge_cycle = cycle;
        repeat (6) @(posedge clk);
        chk(uo_out[3] === 1'b1 && evtp == 1 && uio_out[7:6] == 2'd1 && uio_out[4:2] == 3'd0 && uio_out[5] === 1'b1,
            "edge on CAP0: EVT high, one EVTP pulse, EVQ = 1, EVCH = 0, EVED = 1");
        read_reg(4'h1, ev, ok);
        chk(ok && ev[31] == 1'b0 && ev[30:28] == 3'd0 && ev[27] == 1'b1 && uo_out[3] === 1'b0,
            "read EVENT pops it: channel 0, rising; EVT goes low");
        $display("        event timestamp %0d, pin raised at cycle %0d", ev[26:0], edge_cycle);

        send_byte(8'h7E); recv_byte(r, ok, 40);
        chk(ok && r == 8'h15, "unknown command 0x7E answers NAK 0x15");

        // a write cut off after its address and one data byte: no timeout,
        // so the port keeps waiting for the other three
        send_byte(8'h01); send_byte(8'h07); send_byte(8'h20);
        recv_byte(r, ok, 40);
        chk(!ok && dut.u_soc.u_host.state == 3'd2, "truncated write: no reply; the port waits for data bytes");
        send_byte(8'h03); recv_byte(r, ok, 40);
        chk(!ok, "a ping sent now is taken as a data byte: still no reply");
        rst_n = 1'b0; repeat (4) @(posedge clk); rst_n = 1'b1; repeat (20) @(posedge clk);
        send_byte(8'h03); recv_byte(r, ok, 40); recv_byte(r2, ok2, 40);
        chk(ok && r == 8'h5A, "after reset the port answers a ping again");

        read_reg(4'h2, st, ok);
        chk(ok && st[6] == 1'b0, "read STAT after reset: no overflow, queue empty");

        if (fd != 0) $fclose(fd);
        $display("%0d checks, %0d failures", checks, errors);
        if (errors == 0) $display("TOUR TRACE PASSED");
        else             $display("TOUR TRACE FAILED");
        $finish;
    end
endmodule
