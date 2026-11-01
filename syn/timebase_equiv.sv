// timebase_equiv.sv — formal check that sync_timebase's carry look-ahead
// changes nothing: the reference below is the timebase as it was written
// before (carry computed in the same clock), and the property is that both
// produce the same `now` on every clock from reset, for every input sequence.
// Run: yosys -s syn/timebase_equiv.ys (from the repository root).
`default_nettype none

module timebase_equiv (
    input  wire logic        clk,
    input  wire logic        rst,
    input  wire logic        rate_we,
    input  wire logic [31:0] rate_in,
    input  wire logic        adj_we,
    input  wire logic [31:0] adj_in,
    output logic             ok_now,     // proven always 1
    // compared with the timebase's own registers by the .ys script, which
    // makes the proof inductive (Yosys cannot read hierarchical names here)
    output logic [23:0]      ref_frac,
    output logic [23:0]      ref_rate_mag,
    output logic             ref_rate_neg,
    output logic             ref_carry   // the look-ahead flop must equal this
);
    localparam int FRACW = 24;

    logic [31:0] now_dut;
    sync_timebase #(.FRACW(FRACW)) dut (
        .clk(clk), .rst(rst), .rate_we(rate_we), .rate_in(rate_in),
        .adj_we(adj_we), .adj_in(adj_in), .now(now_dut));

    // reference: the pre-look-ahead timebase
    logic [FRACW-1:0] frac, rate_mag;
    logic             rate_neg;
    logic [FRACW:0]   frac_sum;
    logic [31:0]      now, step;
    assign frac_sum = {1'b0, frac} + {1'b0, rate_mag};
    always_comb begin
        if (rate_neg) step = frac_sum[FRACW] ? 32'd0 : 32'd1;
        else          step = frac_sum[FRACW] ? 32'd2 : 32'd1;
    end
    always_ff @(posedge clk) begin
        if (rst) begin
            now <= 32'd0; frac <= '0; rate_mag <= '0; rate_neg <= 1'b0;
        end else begin
            if (rate_we) begin
                rate_mag <= rate_in[FRACW-1:0]; rate_neg <= rate_in[31]; frac <= '0;
            end else frac <= frac_sum[FRACW-1:0];
            if (adj_we) now <= now + adj_in + 32'd1;
            else        now <= now + step;
        end
    end

    assign ok_now       = (now_dut == now);
    assign ref_frac     = frac;
    assign ref_rate_mag = rate_mag;
    assign ref_rate_neg = rate_neg;
    assign ref_carry    = frac_sum[FRACW];
endmodule
