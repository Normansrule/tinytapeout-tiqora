// sync_timebase.sv — the monotonic clock everything else is measured against.
//
// This is the part of Tiqora that makes it a clock rather than a counter.
// Three things act on it:
//
//   free run : +1 tick per core clock. One tick is one clock period, so the
//              resolution is 15.6 ns at 64 MHz and 20 ns at 50 MHz.
//   rate     : a fractional accumulator FRACW bits wide. Each clock it adds
//              |rate|; on overflow the timebase takes an extra tick (rate
//              positive) or skips one (rate negative). With FRACW = 24 the
//              adjustment resolution is 2^-24 tick/clock, about 0.06 parts
//              per million, fine enough to discipline against an external
//              pulse-per-second reference.
//   step     : TADJ adds a signed value in one clock, for the coarse jump
//              you make once at startup before you start slewing.
//
// Slewing with `rate` rather than stepping matters for robotics: a stepped
// clock can make a timestamp go backwards, and every filter downstream of it
// then sees a negative time delta.
`default_nettype none

module sync_timebase #(
    parameter int FRACW = 24
) (
    input  wire  logic        clk,
    input  wire  logic        rst,
    // rate discipline: bit 31 is the sign, bits FRACW-1:0 the magnitude
    input  wire  logic        rate_we,
    input  wire  logic [31:0] rate_in,
    // one-shot signed step
    input  wire  logic        adj_we,
    input  wire  logic [31:0] adj_in,
    output logic [31:0]       now
);

    logic [FRACW-1:0] frac, rate_mag;
    logic             rate_neg;
    logic [FRACW:0]   frac_sum;
    logic             frac_co;
    logic [31:0]      step;

    assign frac_sum = {1'b0, frac} + {1'b0, rate_mag};
    assign frac_co  = frac_sum[FRACW];

    // +2 speeds the clock up by one tick, 0 slows it by one tick
    always_comb begin
        if (rate_neg) step = frac_co ? 32'd0 : 32'd1;
        else          step = frac_co ? 32'd2 : 32'd1;
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            now      <= 32'd0;
            frac     <= '0;
            rate_mag <= '0;
            rate_neg <= 1'b0;
        end else begin
            if (rate_we) begin
                rate_mag <= rate_in[FRACW-1:0];
                rate_neg <= rate_in[31];
                frac     <= '0;
            end else begin
                frac <= frac_sum[FRACW-1:0];
            end

            // A step and a tick in the same clock both apply, so a TADJ can
            // never swallow a tick.
            if (adj_we) now <= now + adj_in + 32'd1;
            else        now <= now + step;
        end
    end

    // rate_in[30:FRACW] is reserved: the sign is bit 31, the magnitude is
    // the low FRACW bits.
    wire _unused = &{1'b0, rate_in[30:FRACW], 1'b0};

endmodule : sync_timebase
