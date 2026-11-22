// sync_tap.sv — record the timing unit's ports from inside a whole chip.
//
// tb_sync_ref.sv drives sync_unit on its own with random inputs. This module
// instead watches the sync_unit that sits inside a real chip while a real
// front end drives it: Tiqora's CPU (Xpulse instructions) or Tiqora-Serial's
// UART host port (register writes and reads). It writes the same trace
// format as tb_sync_ref.sv, so test/sync_model.py replays the inputs the
// front end really produced and compares every output, clock for clock.
// The two chips are then checked against one shared reference model: a
// difference in how either front end uses the unit shows up as a model
// mismatch in that chip's trace.
//
// The bench connects the ports with hierarchical references to its
// sync_unit instance and turns the tap on with +SYNCTAP=<file>. Without the
// plusarg it writes nothing.
//
// Sampling: every rising clock edge, before the edge updates any flip-flop
// (the RTL uses nonblocking assignments), so each line holds the inputs and
// outputs of the clock that is ending, as tb_sync_ref.sv writes them.
// Recording starts at the first clock with reset high, because the model
// starts from reset. Operands of an instruction or a register access that
// is not happening are don't-cares: unknown (x) bits there are written as 0.
// Anything unknown that the unit does use is written as x, and the model
// then fails the trace.
//
// This file is identical in Tiqora and Tiqora-Serial (docs/shared_timing.sha256).
`default_nettype none
`timescale 1ns/1ps

module sync_tap #(
    parameter int NCH   = 8,
    parameter int NCMP  = 2,
    parameter int DEPTH = 2,
    parameter int PTRW  = 1,
    parameter int FRACW = 24,
    parameter int FILTW = 0,
    parameter int PWW   = 16
) (
    input wire            clk,
    input wire            rst,
    input wire [NCH-1:0]  cap,
    input wire            t_valid,
    input wire [2:0]      t_op,
    input wire [6:0]      t_sub,
    input wire [31:0]     t_rs1,
    input wire [31:0]     t_rs2,
    input wire            reg_req,
    input wire [3:0]      reg_addr,
    input wire            reg_we,
    input wire [31:0]     reg_wdata,
    input wire [NCMP-1:0] trig,
    input wire            evt_pending,
    input wire            ovf,
    input wire [31:0]     t_rdata,
    input wire [31:0]     t_now,
    input wire [31:0]     reg_rdata,
    input wire [31:0]     status,
    input wire [31:0]     head
);

    // unknown bits -> 0, for operands the unit ignores this clock
    function automatic [31:0] dc(input [31:0] v);
        integer b;
        begin
            for (b = 0; b < 32; b = b + 1)
                dc[b] = (v[b] === 1'b1);
        end
    endfunction

    integer fd = 0, lines = 0;
    reg     started = 1'b0;
    reg     [1023:0] path;

    initial begin
        if ($value$plusargs("SYNCTAP=%s", path)) begin
            fd = $fopen(path, "w");
            $fdisplay(fd, "# NCH=%0d NCMP=%0d DEPTH=%0d PTRW=%0d FRACW=%0d FILTW=%0d PWW=%0d SEED=0",
                      NCH, NCMP, DEPTH, PTRW, FRACW, FILTW, PWW);
        end
    end

    reg        v_valid, v_req;
    reg [2:0]  v_op;
    reg [6:0]  v_sub;
    reg [31:0] v_rs1, v_rs2, v_wdata;
    reg [3:0]  v_addr;
    reg        v_we;

    always @(posedge clk) if (fd != 0) begin
        if (rst === 1'b1) started = 1'b1;
        if (started) begin
            v_valid = (t_valid === 1'b1);
            v_op    = v_valid ? t_op  : dc({29'd0, t_op});
            v_sub   = v_valid ? t_sub : dc({25'd0, t_sub});
            v_rs1   = v_valid ? t_rs1 : dc(t_rs1);
            v_rs2   = v_valid ? t_rs2 : dc(t_rs2);
            v_req   = (reg_req === 1'b1);
            v_addr  = v_req ? reg_addr  : dc({28'd0, reg_addr});
            v_we    = v_req ? reg_we    : (reg_we === 1'b1);
            v_wdata = (v_req && reg_we === 1'b1) ? reg_wdata : dc(reg_wdata);
            $fdisplay(fd, "%0d %h %0d %0d %0d %h %h %0d %0d %0d %h | %h %0d %0d %h %h %h %h %h",
                      rst, cap, v_valid, v_op, v_sub, v_rs1, v_rs2,
                      v_req, v_addr, v_we, v_wdata,
                      trig, evt_pending, ovf, t_rdata, t_now, reg_rdata, status, head);
            lines = lines + 1;
        end
    end

    final if (fd != 0) $fclose(fd);

endmodule
