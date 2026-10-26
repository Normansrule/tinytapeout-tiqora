// tb_proto.sv — the host port's framing and command handling, at the pins.
//
// tb_uart.sv shows the protocol works when the host behaves. This bench
// checks what happens when the line or the host does not:
//
//   framing   a byte with a low stop bit is dropped; a glitch shorter than
//             half a bit is not a start bit
//   commands  every byte other than 0x01, 0x02, 0x03 gets exactly one NAK,
//             and the port is ready for the next command afterwards
//   commit    a write reaches the registers in one clock, with all 32 bits,
//             only after its sixth byte; a partial frame commits nothing
//   address   only the low four bits of the address byte are decoded;
//             unmapped offsets read as zero and a write to one touches nothing
//   late      bytes that arrive while the chip is still replying are ignored
//   loss      a third edge into the 2-deep queue is dropped and raises the
//             sticky overflow flag; the two queued events read back in order
//   reconnect a host that vanishes mid-command leaves the port waiting for
//             the rest (the next command is eaten as data); reset recovers
//             it with nothing committed and the queue and flag cleared
//
// Every check is printed with its result, and the run ends with a count.
// Run with:  make proto
`default_nettype none
`timescale 1ns/1ps

module tb_proto;

    localparam int DIV     = 16;
    localparam int DIVW    = 6;
    localparam int CLK_NS  = 20;
    localparam int BIT_NS  = DIV * CLK_NS;

    reg        clk = 1'b0, rst = 1'b1;
    reg        rx  = 1'b1;
    reg  [7:0] cap = 8'h00;

    wire [2:0] trig;
    wire       evt_pending, evt_pulse, ovf, heartbeat;
    wire       tx, uart_active;
    wire [2:0] ev_chan;
    wire       ev_edge;
    wire [1:0] ev_count;

    integer errors = 0, checks = 0;

    task chk(input cond, input string name);
        begin
            checks = checks + 1;
            if (!cond) begin
                errors = errors + 1;
                $display("  FAIL  %0s", name);
            end else
                $display("  ok    %0s", name);
        end
    endtask

    always #(CLK_NS/2) clk = ~clk;

    tp_sync_soc #(
        .NCH(8), .NCMP(3), .DEPTH(2), .PTRW(1),
        .FRACW(24), .FILTW(0), .DIV(DIV), .DIVW(DIVW)
    ) dut (
        .clk(clk), .rst(rst),
        .cap_pin(cap), .trig_pin(trig),
        .evt_pending(evt_pending), .evt_pulse(evt_pulse), .ovf_pin(ovf),
        .heartbeat(heartbeat),
        .uart_rx(rx), .uart_tx(tx), .uart_active(uart_active),
        .ev_chan(ev_chan), .ev_edge(ev_edge), .ev_count(ev_count)
    );

    // ---- host side: one 8N1 byte; `stop` = 0 sends a framing error ----
    task send_raw(input [7:0] b, input stop);
        integer i;
        begin
            rx = 1'b0;
            #(BIT_NS);
            for (i = 0; i < 8; i = i + 1) begin
                rx = b[i];
                #(BIT_NS);
            end
            rx = stop;
            #(BIT_NS);
            rx = 1'b1;
            #(BIT_NS/2);
        end
    endtask

    task send_byte(input [7:0] b);
        send_raw(b, 1'b1);
    endtask

    // ---- host side: an always-listening receiver (see tb_uart.sv) ----
    reg [7:0] rxq [0:1023];
    integer   rxq_wr = 0, rxq_rd = 0;

    initial begin : rx_monitor
        reg [7:0] b;
        integer   k;
        forever begin
            wait (tx === 1'b0);
            #(BIT_NS/2);
            if (tx === 1'b0) begin
                for (k = 0; k < 8; k = k + 1) begin
                    #(BIT_NS);
                    b[k] = tx;
                end
                #(BIT_NS);
                if (tx === 1'b1) begin
                    rxq[rxq_wr % 1024] = b;
                    rxq_wr = rxq_wr + 1;
                end
            end
        end
    end

    // Wait until the chip has nothing left to send and its TX line has been
    // quiet for `bits` bit times, then return how many reply bytes arrived.
    // (Not `uart_active`: that stays high while a frame is half received.)
    task settle(input integer bits, output integer n);
        integer quiet, guard;
        begin
            quiet = 0; guard = 0;
            while (quiet < bits && guard < 2000) begin
                #(BIT_NS);
                guard = guard + 1;
                if (dut.u_host.tx_busy || dut.u_host.state == 3'd3 || dut.u_host.state == 3'd4 ||
                    tx !== 1'b1) quiet = 0;
                else quiet = quiet + 1;
            end
            if (guard >= 2000) $display("  FAIL  the chip never went quiet");
            n = rxq_wr - rxq_rd;
        end
    endtask

    function automatic [7:0] pop_rx();
        pop_rx = rxq[rxq_rd % 1024];
        rxq_rd = rxq_rd + 1;
    endfunction

    task drop_rx();
        rxq_rd = rxq_wr;
    endtask

    // ---- the register port, watched from inside ----
    integer     req_count = 0;
    reg  [3:0]  last_addr;
    reg         last_we;
    reg  [31:0] last_wdata;
    integer     strobes = 0;     // any write strobe or pop inside the sync unit

    always @(posedge clk) if (!rst) begin
        if (dut.u_host.reg_req) begin
            req_count  = req_count + 1;
            last_addr  = dut.u_host.reg_addr;
            last_we    = dut.u_host.reg_we;
            last_wdata = dut.u_host.reg_wdata;
        end
        if (dut.u_sync.arm_we || dut.u_sync.pulse_we || dut.u_sync.pw_we ||
            dut.u_sync.cfg_we || dut.u_sync.adj_we  || dut.u_sync.rate_we ||
            dut.u_sync.fifo_pop)
            strobes = strobes + 1;
    end

    task do_ping(output logic good);
        integer n;
        reg [7:0] a, b;
        begin
            send_byte(8'h03);
            settle(4, n);
            good = 1'b0;
            if (n == 2) begin
                a = pop_rx(); b = pop_rx();
                good = (a === 8'h5A) && (b === 8'h01);
            end else drop_rx();
        end
    endtask

    task do_read(input [7:0] abyte, output [31:0] d, output logic good);
        integer n;
        begin
            send_byte(8'h02);
            send_byte(abyte);
            settle(4, n);
            good = (n == 4);
            d = 32'hxxxx_xxxx;
            if (good) begin
                d[7:0] = pop_rx(); d[15:8] = pop_rx(); d[23:16] = pop_rx(); d[31:24] = pop_rx();
            end else drop_rx();
        end
    endtask

    task do_write(input [7:0] abyte, input [31:0] d, output logic good);
        integer n;
        begin
            send_byte(8'h01);
            send_byte(abyte);
            send_byte(d[7:0]); send_byte(d[15:8]); send_byte(d[23:16]); send_byte(d[31:24]);
            settle(4, n);
            good = (n == 1) && (rxq[rxq_rd % 1024] === 8'h06);
            drop_rx();
        end
    endtask

    logic       ok, ok2;
    integer     seed = 1;      // +SEED=n to change; printed at the start
    integer     n, i, nak_bad, req0, str0, bad;
    reg  [31:0] v, d;
    reg  [7:0]  b;

    initial begin
        $dumpfile("tb_proto.vcd");
        $dumpvars(0, tb_proto);
        $display("\n=== Tiqora-Serial host port: framing and bad input ===");
        if ($value$plusargs("SEED=%d", seed)) ;
        $display("  random seed %0d", seed);
        repeat (8) @(posedge clk);
        rst = 1'b0;
        #(BIT_NS * 2);

        do_ping(ok);
        chk(ok, "a ping after reset answers 5A 01");

        // -------------------------------------------------------------
        $display("\n[framing]");
        send_raw(8'h03, 1'b0);                     // ping with a low stop bit
        settle(30, n);
        chk(n == 0 && dut.u_host.state == 3'd0, "a byte with a low stop bit is dropped, no reply");
        do_ping(ok);
        chk(ok, "and the next good ping answers normally");

        rx = 1'b0; #(BIT_NS * 4 / 10); rx = 1'b1;  // a 0.4-bit glitch
        settle(30, n);
        chk(n == 0 && dut.u_host.state == 3'd0, "a glitch shorter than half a bit is not a start bit");

        // -------------------------------------------------------------
        $display("\n[unknown commands]");
        nak_bad = 0;
        req0 = req_count;
        for (i = 0; i < 256; i = i + 1) begin
            if (i < 1 || i > 3) begin
                send_byte(i[7:0]);
                settle(3, n);
                if (n != 1 || rxq[rxq_rd % 1024] !== 8'h15) nak_bad = nak_bad + 1;
                drop_rx();
            end
        end
        chk(nak_bad == 0, "all 253 other command bytes get exactly one NAK (0x15) each");
        chk(req_count == req0, "and none of them reaches the registers");
        do_ping(ok);
        chk(ok, "the port takes a ping straight after the sweep");

        // -------------------------------------------------------------
        $display("\n[commit]");
        req0 = req_count;
        send_byte(8'h01); send_byte(8'h07); send_byte(8'hAA); send_byte(8'hBB);
        settle(30, n);
        chk(req_count == req0, "a write that stops after 2 of 4 data bytes commits nothing");
        chk(n == 0, "and sends no reply");
        send_byte(8'hCC); send_byte(8'hDD);
        settle(4, n);
        chk(n == 1 && rxq[rxq_rd % 1024] === 8'h06, "the two missing bytes complete it: ACK");
        drop_rx();
        chk(req_count == req0 + 1 && last_we && last_addr == 4'h7 && last_wdata == 32'hDDCC_BBAA,
            "one register access, one clock, all 32 bits (PW = 0xDDCCBBAA)");

        req0 = req_count;
        bad = 0;
        for (i = 0; i < 8; i = i + 1) begin
            d = $random(seed);
            do_write(8'h07, d, ok);
            if (!ok || last_wdata !== d) bad = bad + 1;
        end
        chk(bad == 0 && req_count == req0 + 8, "8 random writes: 8 accesses, each with the exact word sent");
        do_write(8'h07, 32'd64, ok);               // put the pulse width back

        // -------------------------------------------------------------
        $display("\n[address]");
        bad = 0;
        for (i = 3; i < 16; i = i + 1) begin
            do_read(i[7:0], v, ok);
            if (!ok || v !== 32'd0) bad = bad + 1;
        end
        chk(bad == 0, "reads of offsets 3..15 (write-only or unmapped) return 0");

        str0 = strobes;
        bad = 0;
        for (i = 6; i < 16; i = i + 1) begin
            if (i == 6 || i > 10) begin
                do_write(i[7:0], 32'hFFFF_FFFF, ok);
                if (!ok) bad = bad + 1;
            end
        end
        chk(bad == 0, "writes to unmapped offsets 6, 11..15 are acknowledged");
        chk(strobes == str0, "and none of them touches a register inside the sync unit");

        do_read(8'h20, v, ok);                     // 0x20: low nibble 0, SR_TIME
        chk(ok && v !== 32'd0 && last_addr == 4'h0,
            "only the low four address bits are decoded: 0x20 reads the timebase");

        // -------------------------------------------------------------
        $display("\n[late commands]");
        send_byte(8'h02); send_byte(8'h00);         // read TIME: a 4-byte reply
        // Send a ping while that reply is still on the wire.
        #(BIT_NS * 12);
        req0 = req_count;
        send_byte(8'h03);
        settle(4, n);
        chk(n == 4, "a ping sent during a 4-byte reply is ignored: 4 bytes come back, not 6");
        drop_rx();
        do_ping(ok);
        chk(ok, "the port is ready for the next command afterwards");

        // -------------------------------------------------------------
        $display("\n[queue loss]");
        do_write(8'h03, 32'h0000_0007, ok);        // CFG: CAP0..2, rising edges
        @(negedge clk) cap[0] = 1'b1;
        repeat (50) @(negedge clk);
        cap[1] = 1'b1;
        repeat (50) @(negedge clk);
        cap[2] = 1'b1;
        repeat (50) @(negedge clk);
        chk(ok && ovf === 1'b1 && ev_count == 2'd2,
            "three edges into the 2-deep queue: two queued, overflow pin high");
        do_read(8'h02, v, ok);
        chk(ok && v[1:0] == 2'd2 && v[5] && v[6], "STAT agrees: count 2, full, overflow");
        do_read(8'h01, v, ok);
        do_read(8'h01, d, ok2);
        chk(ok && ok2 && v[31:27] == 5'b0_000_1 && d[31:27] == 5'b0_001_1 &&
            d[26:0] - v[26:0] == 27'd50,
            "the two oldest read back in order: CAP0 then CAP1, rising, 50 ticks apart");
        do_read(8'h01, v, ok);
        chk(ok && v === 32'd0, "a third read returns 0: the CAP2 edge was dropped, not delayed");
        do_read(8'h02, v, ok);
        chk(ok && v[4] && v[6] && ovf === 1'b1,
            "the queue is empty and overflow stays set until reset");

        // -------------------------------------------------------------
        $display("\n[reconnection]");
        req0 = req_count;
        send_byte(8'h01); send_byte(8'h07); send_byte(8'hAA); send_byte(8'hBB);
        settle(30, n);                              // the host goes away here
        send_byte(8'h03);                           // and comes back with a ping
        settle(30, n);
        chk(n == 0 && req_count == req0,
            "a ping after a cut write is taken as its fifth byte: no reply, nothing written");
        @(negedge clk) rst = 1'b1;
        repeat (4) @(negedge clk);
        rst = 1'b0;
        #(BIT_NS * 2);
        do_ping(ok);
        chk(ok && req_count == req0, "after reset the next ping answers 5A 01 and the cut write never lands");
        do_read(8'h02, v, ok);
        chk(ok && v[4] && !v[6] && ovf === 1'b0, "reset also empties the queue and clears overflow");

        $display("\n%0d checks, %0d failures", checks, errors);
        if (errors == 0) $display("SERIAL PROTOCOL PASSED\n");
        else             $display("SERIAL PROTOCOL FAILED\n");
        $finish;
    end

endmodule
