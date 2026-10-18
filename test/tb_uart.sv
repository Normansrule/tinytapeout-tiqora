// tb_uart.sv — drive the 1x1 tile the way a host on a USB-C serial
// bridge does: bytes in on RX, bytes out on TX, nothing else.
//
// This is the test that decides whether the 1x1 build is a real chip or
// an empty tile. Everything the part can do has to come through these
// two pins.
//
// Run with:  make uart
`default_nettype none
`timescale 1ns/1ps

module tb_uart;

    // A short bit period keeps the simulation quick. The silicon default
    // is 434 clocks per bit, which is 115200 baud at 50 MHz; the protocol
    // does not care and neither does this test.
    localparam int DIV     = 16;
    localparam int DIVW    = 6;
    localparam int CLK_NS  = 20;                 // 50 MHz
    localparam int BIT_NS  = DIV * CLK_NS;

    localparam logic [3:0] SR_TIME  = 4'h0;
    localparam logic [3:0] SR_EVENT = 4'h1;
    localparam logic [3:0] SR_STAT  = 4'h2;
    localparam logic [3:0] SR_CFG   = 4'h3;
    localparam logic [3:0] SR_CMP0  = 4'h4;
    localparam logic [3:0] SR_PW    = 4'h7;
    localparam logic [3:0] SR_RATE  = 4'h9;
    localparam logic [3:0] SR_PULSE = 4'hA;

    reg        clk = 1'b0, rst = 1'b1;
    reg        rx  = 1'b1;                        // idle high
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

    // ---- host side: send a byte, 8N1 ----
    task send_byte(input [7:0] b);
        integer i;
        begin
            rx = 1'b0;                            // start
            #(BIT_NS);
            for (i = 0; i < 8; i = i + 1) begin
                rx = b[i];                        // least significant first
                #(BIT_NS);
            end
            rx = 1'b1;                            // stop
            #(BIT_NS);
            #(BIT_NS/2);                          // a little idle
        end
    endtask

    // ---- host side: an always-listening receiver ----
    //
    // A real USB-to-UART bridge receives independently of transmitting,
    // and the chip is full duplex: it begins its reply the moment it has
    // sampled the host's stop bit, while the host is still finishing that
    // stop bit. A receiver that only starts listening after the host has
    // finished sending misses the reply's start bit. So this runs in the
    // background, exactly like the bridge, and fills a queue.
    reg [7:0] rxq [0:255];
    integer   rxq_wr = 0, rxq_rd = 0;

    initial begin : rx_monitor
        reg [7:0] b;
        integer   k;
        forever begin
            wait (tx === 1'b0);                   // start bit
            #(BIT_NS/2);                          // centre of the start bit
            if (tx === 1'b0) begin
                for (k = 0; k < 8; k = k + 1) begin
                    #(BIT_NS);
                    b[k] = tx;                    // least significant first
                end
                #(BIT_NS);                        // centre of the stop bit
                if (tx === 1'b1) begin
                    rxq[rxq_wr % 256] = b;
                    rxq_wr = rxq_wr + 1;
                end
            end
        end
    end

    task recv_byte(output [7:0] b, output logic ok);
        integer guard;
        begin
            b = 8'h00;
            ok = 1'b0;
            guard = 0;
            while (rxq_rd >= rxq_wr && guard < 200) begin
                #(BIT_NS);
                guard = guard + 1;
            end
            if (rxq_rd < rxq_wr) begin
                b = rxq[rxq_rd % 256];
                rxq_rd = rxq_rd + 1;
                ok = 1'b1;
            end
        end
    endtask

    // ---- pin watchers ----
    // A trigger pulse is 64 ticks; one serial transaction is about a
    // thousand. Sampling the pin after the ACK arrives would look long
    // after the pulse ended, so the pins are watched continuously.
    wire [31:0] now = dut.u_sync.now;
    reg  [2:0]  trig_seen = 3'b000;
    reg  [2:0]  trig_q    = 3'b000;
    reg  [31:0] trig0_rise_tick = 32'hFFFF_FFFF;
    reg         trig0_rise_seen = 1'b0;

    always @(posedge clk) begin
        trig_q    <= trig;
        trig_seen <= trig_seen | trig;
        if (trig[0] && !trig_q[0] && !trig0_rise_seen) begin
            trig0_rise_tick <= now;
            trig0_rise_seen <= 1'b1;
        end
    end

    task host_write(input [3:0] a, input [31:0] d);
        reg [7:0] r; logic ok;
        begin
            send_byte(8'h01);
            send_byte({4'h0, a});
            send_byte(d[7:0]);
            send_byte(d[15:8]);
            send_byte(d[23:16]);
            send_byte(d[31:24]);
            recv_byte(r, ok);
            chk(ok && r === 8'h06, $sformatf("write reg %0d acknowledged", a));
        end
    endtask

    task host_read(input [3:0] a, output [31:0] d);
        reg [7:0] b0, b1, b2, b3; logic o0, o1, o2, o3;
        begin
            send_byte(8'h02);
            send_byte({4'h0, a});
            recv_byte(b0, o0);
            recv_byte(b1, o1);
            recv_byte(b2, o2);
            recv_byte(b3, o3);
            d = {b3, b2, b1, b0};
            if (!(o0 && o1 && o2 && o3))
                $display("        read reg %0d: missing reply bytes", a);
        end
    endtask

    reg [7:0]  r0, r1;
    logic      ok0, ok1;
    reg [31:0] v, t_a, t_b, ev;
    integer    i;

    initial begin
        $dumpfile("tb_uart.vcd");
        $dumpvars(0, tb_uart);
        $display("\n=== Tiqora-Serial serial host port ===");

        repeat (8) @(posedge clk);
        rst = 1'b0;
        #(BIT_NS * 2);

        // -------------------------------------------------------------
        $display("\n[link]");
        send_byte(8'h03);                          // PING
        recv_byte(r0, ok0);
        recv_byte(r1, ok1);
        chk(ok0 && r0 === 8'h5A, "ping returns the magic byte");
        chk(ok1 && r1 === 8'h01, "ping returns the protocol version");

        send_byte(8'hFF);                          // nonsense
        recv_byte(r0, ok0);
        chk(ok0 && r0 === 8'h15, "an unknown command is refused with NAK");

        // -------------------------------------------------------------
        $display("\n[the timebase is reachable]");
        host_read(SR_TIME, t_a);
        #(BIT_NS * 20);
        host_read(SR_TIME, t_b);
        chk(t_b > t_a, "the timebase advances between two reads");
        chk(t_a != 32'd0, "the timebase is running, not stuck at zero");

        // -------------------------------------------------------------
        $display("\n[configuration round trip]");
        host_write(SR_CFG, 32'h0000_00FF);         // enable all 8 channels
        host_write(SR_PW,  32'h0000_0040);         // 64-tick trigger pulse
        host_read(SR_STAT, v);
        chk(v[4] === 1'b1, "status says the event queue is empty");
        chk(v[6] === 1'b0, "status says no overflow");

        // -------------------------------------------------------------
        $display("\n[capture an event and read it back over serial]");
        @(negedge clk); cap[3] = 1'b1;             // rising edge on CAP3
        repeat (8) @(posedge clk);
        chk(evt_pending === 1'b1, "the capture reached the queue");
        chk(ev_chan === 3'd3, "the exposed head-of-queue channel is CAP3");
        chk(ev_edge === 1'b1, "the exposed head-of-queue edge is rising");

        host_read(SR_STAT, v);
        chk(v[3:0] === 4'd1, "status reports one queued event");

        host_read(SR_EVENT, ev);
        $display("        event word = %08x", ev);
        chk(ev[31] === 1'b0, "the event came from hardware capture");
        chk(ev[30:28] === 3'd3, "the event is on channel 3");
        chk(ev[27] === 1'b1, "the event is a rising edge");
        chk(ev[26:0] !== 27'd0, "the event carries a timestamp");

        host_read(SR_STAT, v);
        chk(v[4] === 1'b1, "reading the event register popped it");

        // -------------------------------------------------------------
        $display("\n[fire a trigger from the host]");
        trig_seen = 3'b000;
        host_write(SR_PULSE, 32'h0000_0005);       // channels 0 and 2
        chk(trig_seen[0] === 1'b1, "TRIG0 fired");
        chk(trig_seen[2] === 1'b1, "TRIG2 fired");
        chk(trig_seen[1] === 1'b0, "TRIG1 stayed low: the mask was 0b101");

        // -------------------------------------------------------------
        $display("\n[arm a deadline from the host]");
        // far enough out that it cannot fire during the serial traffic
        // that arms and inspects it
        repeat (200) @(posedge clk);
        trig0_rise_seen = 1'b0;
        host_read(SR_TIME, t_a);
        host_write(SR_CMP0, t_a + 32'd8000);
        host_read(SR_STAT, v);
        chk(v[8] === 1'b1, "compare channel 0 reports armed");
        chk(!trig0_rise_seen, "it has not fired early");

        // now wait for it and check the one claim this chip exists for
        begin : wait_fire
            integer g;
            g = 0;
            while (!trig0_rise_seen && g < 20000) begin
                @(posedge clk);
                g = g + 1;
            end
        end
        chk(trig0_rise_seen, "the armed deadline fired");
        chk(trig0_rise_tick === t_a + 32'd8000,
            "it fired on the exact programmed tick, armed over serial");
        if (trig0_rise_tick !== t_a + 32'd8000)
            $display("        fired at %0d, programmed %0d",
                     trig0_rise_tick, t_a + 32'd8000);
        host_read(SR_STAT, v);
        chk(v[8] === 1'b0, "the channel disarmed after firing");

        // -------------------------------------------------------------
        $display("\n[discipline the clock from the host]");
        host_write(SR_RATE, 32'h0080_0000);        // +0.5 tick per clock
        host_read(SR_TIME, t_a);
        for (i = 0; i < 400; i = i + 1) @(posedge clk);
        host_read(SR_TIME, t_b);
        chk((t_b - t_a) > 32'd400,
            "TRATE over serial makes the timebase outrun the clock");

        $display("\n%0d checks, %0d failures", checks, errors);
        if (errors == 0) $display("SERIAL HOST PORT PASSED\n");
        else             $display("SERIAL HOST PORT FAILED\n");
        $finish;
    end

endmodule
