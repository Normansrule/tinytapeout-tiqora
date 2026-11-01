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
    logic [FRACW-1:0] frac_sum;
    logic [FRACW+1:0] frac_sum2;
    logic             frac_co;
    logic [31:0]      step;

    // Carry look-ahead, for speed. frac_co is the carry out of frac + rate_mag,
    // the one that adds or drops a tick, and computing it in the same clock as
    // `now + step` put a 24-bit carry chain in series with the 32-bit timebase
    // increment: the slowest path in the chip (sky130 slow corner). Instead the
    // carry is computed a clock early into a flip-flop, so `now` sees a register.
    //   frac + rate_mag     = frac_co * 2^FRACW + frac_next
    //   frac_next + rate_mag >= 2^FRACW  <=>  frac + 2*rate_mag >= (1 + frac_co) * 2^FRACW
    // frac + 2*rate_mag < 3 * 2^FRACW, so its top two bits (0, 1 or 2) decide:
    // the next carry is set exactly when they exceed today's carry. After reset
    // or a rate write frac is 0, and 0 + rate_mag never carries, so the
    // register starts at 0. Same ticks on the same clocks as computing it
    // directly (syn/timebase_equiv.ys proves it); costs one adder and one flop.
    assign frac_sum  = frac + rate_mag;
    assign frac_sum2 = {2'b00, frac} + {1'b0, rate_mag, 1'b0};

    // Both candidates are computed from registers and the write strobe only
    // picks one at the end: a late adj_we (it is decoded from the instruction)
    // then selects a finished sum instead of steering an adder's input.
    // The adjust sum is a carry-select adder: both possible upper halves are
    // formed alongside the lower half and its carry picks one, so the longest
    // carry chain is 16 bits instead of 32 (one more 16-bit adder of area).
    logic [31:0] now_adj, now_step;
    logic [16:0] adj_lo;
    logic [15:0] adj_hi0, adj_hi1;
    assign adj_lo   = {1'b0, now[15:0]} + {1'b0, adj_in[15:0]} + 17'd1;
    assign adj_hi0  = now[31:16] + adj_in[31:16];
    assign adj_hi1  = now[31:16] + adj_in[31:16] + 16'd1;
    assign now_adj  = {adj_lo[16] ? adj_hi1 : adj_hi0, adj_lo[15:0]};
    assign now_step = now + step;

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
            frac_co  <= 1'b0;
        end else begin
            if (rate_we) begin
                rate_mag <= rate_in[FRACW-1:0];
                rate_neg <= rate_in[31];
                frac     <= '0;
                frac_co  <= 1'b0;
            end else begin
                frac     <= frac_sum;
                frac_co  <= (frac_sum2[FRACW+1:FRACW] > {1'b0, frac_co});
            end

            // A step and a tick in the same clock both apply, so a TADJ can
            // never swallow a tick.
            now <= adj_we ? now_adj : now_step;
        end
    end

    // rate_in[30:FRACW] is reserved: the sign is bit 31, the magnitude is
    // the low FRACW bits. Only the top two bits of frac_sum2 are needed.
    wire _unused = &{1'b0, rate_in[30:FRACW], frac_sum2[FRACW-1:0], 1'b0};

endmodule : sync_timebase
