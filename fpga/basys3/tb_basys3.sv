// tb_basys3.sv — Tiqora-Serial on the simulated Basys 3, driven the way a
// PC drives the real board: bytes over the USB serial pins at 115,200 baud
// (434 clocks per bit at 50 MHz), buttons, and the LEDs watched.
`default_nettype none
`timescale 1ns/1ps
module tb_basys3;
    localparam int DIV = 434;
    reg clk = 0, btnC = 0, btnL = 0, btnR = 0, btnU = 0, btnD = 0, RsRx = 1;
    reg [15:0] sw = 16'h0000;
    wire [15:0] led; wire [6:0] seg; wire dp; wire [3:0] an; wire RsTx;
    always #5 clk = ~clk;
    basys3_top dut (.clk(clk), .btnC(btnC), .btnL(btnL), .btnR(btnR), .btnU(btnU), .btnD(btnD),
                    .sw(sw), .led(led), .seg(seg), .dp(dp), .an(an), .RsRx(RsRx), .RsTx(RsTx));

    integer errors = 0, checks = 0;
    task chk(input cond, input [8*80:1] msg);
        begin checks = checks + 1;
              if (cond) $display("  ok    %0s", msg); else begin errors = errors + 1; $display("  FAIL  %0s", msg); end end
    endtask

    reg [7:0] rx_buf [0:255]; integer rx_n = 0;
    always begin : pc_receiver
        integer i; reg [7:0] b;
        @(posedge dut.clk50);
        if (dut.rst_n && RsTx === 1'b0) begin
            repeat (DIV / 2) @(posedge dut.clk50);
            for (i = 0; i < 8; i = i + 1) begin repeat (DIV) @(posedge dut.clk50); b[i] = RsTx; end
            repeat (DIV) @(posedge dut.clk50);
            rx_buf[rx_n % 256] = b; rx_n = rx_n + 1;
        end
    end
    task send(input [7:0] b);
        integer i;
        begin RsRx = 0; repeat (DIV) @(posedge dut.clk50);
              for (i = 0; i < 8; i = i + 1) begin RsRx = b[i]; repeat (DIV) @(posedge dut.clk50); end
              RsRx = 1; repeat (DIV) @(posedge dut.clk50); end
    endtask
    task await(input integer n);                 // wait until n more reply bytes have arrived
        integer start, t; begin start = rx_n; t = 0;
              while (rx_n < start + n && t < 40 * DIV) begin repeat (100) @(posedge dut.clk50); t = t + 100; end end
    endtask
    function [31:0] last32; input integer dummy;
        last32 = {rx_buf[(rx_n - 1) % 256], rx_buf[(rx_n - 2) % 256], rx_buf[(rx_n - 3) % 256], rx_buf[(rx_n - 4) % 256]};
    endfunction
    task read_reg(input [7:0] aa, output [31:0] v);
        begin send(8'h02); send(aa); await(4); v = last32(0); end
    endtask
    task write_reg(input [7:0] aa, input [31:0] d, output ok);
        begin send(8'h01); send(aa); send(d[7:0]); send(d[15:8]); send(d[23:16]); send(d[31:24]);
              await(1); ok = (rx_buf[(rx_n - 1) % 256] == 8'h06); end
    endtask

    reg [31:0] t1, t2, st, ev; reg ok; reg saw_trig;
    always @(posedge dut.clk50) if (dut.led[0] === 1'b1) saw_trig = 1'b1;
    initial begin
        saw_trig = 1'b0;
        $display("\n=== Tiqora-Serial on the Basys 3 (simulated board, 115200 baud) ===");
        while (dut.rst_n !== 1'b1) @(posedge dut.clk50);
        repeat (100) @(posedge dut.clk50);
        send(8'h03); await(2);
        chk(rx_buf[0] == 8'h5A && rx_buf[1] == 8'h01, "ping over the USB serial pins answers 5A 01");
        read_reg(8'd0, t1); read_reg(8'd0, t2);
        chk(t2 > t1, "the timebase advances between two reads");
        $display("        TIME read twice: %0d, then %0d (%0d ticks apart)", t1, t2, t2 - t1);
        write_reg(8'd3, 32'h0000_0008, ok);
        chk(ok, "CFG write (capture channel 3, rising edge) acknowledged with 06");
        saw_trig = 1'b0;
        btnL = 1; repeat (2000) @(posedge dut.clk50); btnL = 0;
        read_reg(8'd2, st);
        chk((st & 32'hF) >= 1, "pressing BTNL queued an event");
        read_reg(8'd1, ev);
        chk(ev[30:28] == 3'd3 && ev[27] == 1'b1, "the event is channel 3 (BTNL), rising edge");
        $display("        event word %08h: channel %0d, %s, timestamp %0d", ev, ev[30:28], ev[27] ? "rising" : "falling", ev[26:0]);
        chk(ev[26:0] > t2[26:0], "and is timestamped after the earlier TIME reads");
        write_reg(8'd10, 32'h0000_0001, ok);
        repeat (2000) @(posedge dut.clk50);
        chk(ok && saw_trig, "PULSE fires trigger 0, seen on LED 0");
        $display("\n%0d checks, %0d failures", checks, errors);
        if (errors == 0) $display("BASYS 3 SIMULATION PASSED\n"); else $display("BASYS 3 SIMULATION FAILED\n");
        if (errors != 0) $fatal(1, "Basys 3 simulation failed");   // nonzero exit for make and CI
        $finish;
    end
endmodule
