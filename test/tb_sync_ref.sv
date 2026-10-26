// tb_sync_ref.sv — the timing unit against its reference model, cycle by cycle.
//
// Drives random pins, Xpulse instructions and register accesses into
// sync_unit, and writes every input and every output of every clock to a
// trace file. test/sync_model.py replays the inputs through a Python model
// of the same unit and compares all outputs. The bench itself checks
// nothing; the verdict comes from the model.
//
// This file, sync_model.py and src/sync/*.sv are identical in Tiqora and
// Tiqora-Serial (docs/shared_timing.sha256).
//
//   python3 sync_model.py --suite    (compiles this bench three ways and checks each trace)
`default_nettype none
`timescale 1ns/1ps

module tb_sync_ref;

    parameter int NCH   = 8;
    parameter int NCMP  = 2;
    parameter int DEPTH = 2;
    parameter int PTRW  = 1;
    parameter int FRACW = 24;
    parameter int FILTW = 0;
    parameter int PWW   = 16;

    reg              clk = 1'b0, rst = 1'b1;
    reg  [NCH-1:0]   cap = '0;
    reg              t_valid = 1'b0;
    reg  [2:0]       t_op = 3'd0;
    reg  [6:0]       t_sub = 7'd0;
    reg  [31:0]      t_rs1 = 32'd0, t_rs2 = 32'd0;
    reg              reg_req = 1'b0, reg_we = 1'b0;
    reg  [3:0]       reg_addr = 4'd0;
    reg  [31:0]      reg_wdata = 32'd0;

    wire [NCMP-1:0]  trig;
    wire             evt_pending, ovf;
    wire [31:0]      t_rdata, t_now, reg_rdata, status, head;

    sync_unit #(
        .NCH(NCH), .NCMP(NCMP), .DEPTH(DEPTH), .PTRW(PTRW),
        .FRACW(FRACW), .FILTW(FILTW), .PWW(PWW)
    ) dut (
        .clk(clk), .rst(rst),
        .cap_pin(cap), .trig_pin(trig), .evt_pending(evt_pending), .ovf_pin(ovf),
        .t_valid(t_valid), .t_op(t_op), .t_sub(t_sub), .t_rs1(t_rs1), .t_rs2(t_rs2),
        .t_rdata(t_rdata), .t_now(t_now),
        .reg_req(reg_req), .reg_addr(reg_addr), .reg_we(reg_we),
        .reg_wdata(reg_wdata), .reg_rdata(reg_rdata),
        .status_out(status), .head_out(head)
    );

    always #5 clk = ~clk;

    integer seed;
    // one random word from the seeded generator (+SEED= changes every run)
    function automatic [31:0] rnd;
        rnd = $random(seed);
    endfunction

    // A value for an operand: mostly something that makes the operation do
    // something visible soon, sometimes anything at all.
    function automatic [31:0] operand(input [3:0] kind);
        reg [31:0] r;
        begin
            r = rnd();
            case (kind)
                4'd0: operand = (r[3:0] == 0) ? rnd() : t_now + (r[7:0] % 48);  // deadline
                4'd1: operand = (r[2:0] == 0) ? rnd() : (r[4] ? -(r % 9) : (r % 9)); // adjust
                4'd2: operand = (r[1:0] == 0) ? rnd() : (r[3] ? 32'h8000_0000 : 0) | (r >> 20); // rate
                4'd3: operand = (r[2:0] == 0) ? rnd() : (r % 12);                // pulse width
                default: operand = rnd();
            endcase
        end
    endfunction

    integer fd, cycles, n, quiet, phase;
    reg [31:0] r;
    reg        was_rst = 1'b0;

    initial begin
        if (!$value$plusargs("SEED=%d", seed))     seed = 1;
        if (!$value$plusargs("CYCLES=%d", cycles)) cycles = 20000;
        fd = $fopen("sync_ref_trace.txt", "w");
        $fdisplay(fd, "# NCH=%0d NCMP=%0d DEPTH=%0d PTRW=%0d FRACW=%0d FILTW=%0d PWW=%0d SEED=%0d",
                  NCH, NCMP, DEPTH, PTRW, FRACW, FILTW, PWW, seed);

        for (n = 0; n < cycles; n = n + 1) begin
            @(negedge clk);
            // Three kinds of stretch, 300 clocks each. Busy: single flips
            // often, several channels at once sometimes. Quiet: the queue
            // drains, so overflow is reached from empty again and again.
            // Burst: a few channels at once, then often one more edge before
            // the backlog drains, with marks and pops racing them and resets
            // often enough that the overflow flag is usually clear.
            phase = (n / 300) % 3;
            quiet = (phase == 1);

            // reset: the first three clocks, then rarely (often in bursts)
            rst = (n < 3) || (rnd() % ((phase == 2) ? 60 : 400) == 0);

            r = rnd();
            if (phase == 2) begin
                if (r[3:0] == 0)       cap = cap ^ ((1 << (r[10:8] % NCH)) | (1 << (r[14:12] % NCH)));
                else if (r[6:4] == 0)  cap = cap ^ (1 << (r[18:16] % NCH));
            end else if (quiet) begin
                if (r[6:0] == 0)   cap = cap ^ (1 << (r[10:8] % NCH));
            end else begin
                if (r[3:0] == 0)       cap = cap ^ (1 << (r[10:8] % NCH));
                else if (r[8:4] == 0)  cap = cap ^ rnd();
            end

            // an Xpulse instruction about one clock in six
            r = rnd();
            t_valid = (phase != 0) ? (r % 3 == 0) : (r % 6 == 0);
            t_op    = (quiet && r[15:14] != 0) ? 3'b001                     // quiet: mostly TPOP
                    : (phase == 2 && r[15:14] != 0) ? (r[16] ? 3'b001 : 3'b110) // burst: TPOP, TMARK
                    : rnd();
            t_sub   = (r[12:10] == 0) ? rnd() : (rnd() % 4);
            case (t_op)
                3'b100:  t_rs1 = operand(0);                                    // TARM
                3'b111:  t_rs1 = (t_sub == 0) ? operand(1) : (t_sub == 1) ? operand(2)
                               : (t_sub == 3) ? operand(3) : rnd();          // TCTL
                default: t_rs1 = rnd();
            endcase
            t_rs2 = rnd();

            // a register access about one clock in eight
            r = rnd();
            reg_req   = (r % 8 == 0);
            reg_we    = r[5];
            reg_addr  = rnd();
            case (reg_addr)
                4'h4, 4'h5: reg_wdata = operand(0);
                4'h7:       reg_wdata = operand(3);
                4'h8:       reg_wdata = operand(1);
                4'h9:       reg_wdata = operand(2);
                default:    reg_wdata = rnd();
            endcase

            // a burst stretch turns every channel back on straight after a
            // reset (reset clears the enables), with random edge selection
            if (phase == 2 && was_rst && !rst) begin
                t_valid   = 1'b0;
                reg_req   = 1'b1;
                reg_we    = 1'b1;
                reg_addr  = 4'h3;                                         // CFG
                reg_wdata = {15'd0, r[16], r[15:8], 8'hFF};
            end
            was_rst = rst;

            // sample just before the rising edge: inputs and every output
            #4;
            $fdisplay(fd, "%0d %h %0d %0d %0d %h %h %0d %0d %0d %h | %h %0d %0d %h %h %h %h %h",
                      rst, cap, t_valid, t_op, t_sub, t_rs1, t_rs2,
                      reg_req, reg_addr, reg_we, reg_wdata,
                      trig, evt_pending, ovf, t_rdata, t_now, reg_rdata, status, head);
        end
        $fclose(fd);
        $display("trace: %0d clocks written to sync_ref_trace.txt", cycles);
        $finish;
    end
endmodule
