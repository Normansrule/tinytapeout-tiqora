// compare_equiv.sv — formal check that sync_compare's stored deadline - 1
// changes nothing: the reference below is the comparator as it was written
// before (it stored the deadline and compared now + 1 against it), and the
// property is that both drive the same trigger and armed outputs on every
// clock from reset, for every input sequence, wrap-around included.
// Run: yosys -s syn/compare_equiv.ys (from the repository root).
`default_nettype none

module compare_equiv (
    input  wire logic        clk,
    input  wire logic        rst,
    input  wire logic [31:0] now,
    input  wire logic        arm_we,
    input  wire logic [31:0] arm_time,
    input  wire logic [1:0]  arm_sel,
    input  wire logic        pulse_we,
    input  wire logic [1:0]  pulse_mask,
    input  wire logic        pw_we,
    input  wire logic [31:0] pw_in,
    output logic             ok_out,      // proven always 1
    // compared with the comparator's own registers by the .ys script, which
    // makes the proof inductive
    output logic [31:0]      ref_dm1_0,
    output logic [31:0]      ref_dm1_1,
    output logic [15:0]      ref_pw,
    output logic [15:0]      ref_cnt0,
    output logic [15:0]      ref_cnt1
);
    localparam int NCMP = 2, PWW = 16;

    logic [NCMP-1:0] trig_dut, armed_dut;
    sync_compare #(.NCMP(NCMP), .PWW(PWW)) dut (
        .clk(clk), .rst(rst), .now(now), .arm_we(arm_we), .arm_time(arm_time),
        .arm_sel(arm_sel), .pulse_we(pulse_we), .pulse_mask(pulse_mask),
        .pw_we(pw_we), .pw_in(pw_in), .trig(trig_dut), .armed(armed_dut));

    // reference: the comparator before the change
    logic [PWW-1:0]  pw;
    logic [31:0]     deadline0, deadline1;
    logic [PWW-1:0]  cnt0, cnt1;
    logic [NCMP-1:0] armed;
    logic            reached0, reached1, fire0, fire1;
    assign reached0 = ($signed((now + 32'd1) - deadline0) >= 0);
    assign reached1 = ($signed((now + 32'd1) - deadline1) >= 0);
    assign fire0 = (armed[0] && reached0) || (pulse_we && pulse_mask[0]);
    assign fire1 = (armed[1] && reached1) || (pulse_we && pulse_mask[1]);
    always_ff @(posedge clk) begin
        if (rst) begin
            armed <= '0; deadline0 <= '0; deadline1 <= '0; cnt0 <= '0; cnt1 <= '0;
            pw <= 16'd8;
        end else begin
            if (arm_we && arm_sel == 2'd0) begin deadline0 <= arm_time; armed[0] <= 1'b1; end
            else if (armed[0] && reached0) armed[0] <= 1'b0;
            if (arm_we && arm_sel == 2'd1) begin deadline1 <= arm_time; armed[1] <= 1'b1; end
            else if (armed[1] && reached1) armed[1] <= 1'b0;
            if (fire0) cnt0 <= pw; else if (cnt0 != '0) cnt0 <= cnt0 - 1'b1;
            if (fire1) cnt1 <= pw; else if (cnt1 != '0) cnt1 <= cnt1 - 1'b1;
            if (pw_we) pw <= pw_in[PWW-1:0];
        end
    end

    assign ok_out    = (trig_dut == {cnt1 != '0, cnt0 != '0}) && (armed_dut == armed);
    assign ref_pw    = pw;
    assign ref_cnt0  = cnt0;
    assign ref_cnt1  = cnt1;
    assign ref_dm1_0 = deadline0 - 32'd1;
    assign ref_dm1_1 = deadline1 - 32'd1;
endmodule
