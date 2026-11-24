// sync_compare.sv — deadline -> trigger pulse, with zero software in the path.
//
// Arm a channel with an absolute timebase value. When the timebase reaches
// it, the output pin goes high for PW ticks and the channel disarms. The
// output edge lands on the exact clock the deadline is met, so the jitter
// between the programmed time and the pin edge is zero, not "one interrupt
// latency". That is the number that matters when this fires a camera shutter
// or a laser-scanner sync line.
//
// The comparison is a signed difference so an armed deadline survives the
// timebase rolling over.
//
// `late` is sticky: it goes high the first time a channel fires from its
// deadline on a tick other than the one programmed (the deadline had
// already passed when it was armed, a TADJ step jumped over it, or a rate
// correction skipped the tick before it), and only reset clears it, the
// same rule as the event queue's overflow flag.
`default_nettype none

module sync_compare #(
    parameter int NCMP = 2,
    parameter int PWW  = 16,
    // Channels 0 .. NARM-1 take deadlines; the rest are pulse-only (fired
    // by PULSE alone) and carry no deadline register, subtractor or LATE
    // compare. Tiqora-Serial's third trigger has no CMP register, so it
    // builds with NARM = 2 and saves that logic.
    parameter int NARM = NCMP
) (
    input  wire  logic             clk,
    input  wire  logic             rst,
    input  wire  logic [31:0]      now,
    // arm: one-hot-ish write of a deadline into channel `sel`
    input  wire  logic             arm_we,
    input  wire  logic [31:0]      arm_time,
    input  wire  logic [1:0]       arm_sel,
    // direct fire, bypassing the deadline compare
    input  wire  logic             pulse_we,
    input  wire  logic [NCMP-1:0]  pulse_mask,
    // pulse width in ticks
    input  wire  logic             pw_we,
    input  wire  logic [31:0]      pw_in,
    output logic [NCMP-1:0]        trig,
    output logic [NCMP-1:0]        armed,
    output logic                   late
);

    logic [PWW-1:0] pw;
    logic [31:0]    arm_time_m1;
    assign arm_time_m1 = arm_time - 32'd1;
    (* mem2reg *) logic [31:0]    deadline_m1 [NCMP-1:0];
    (* mem2reg *) logic [PWW-1:0] pulse_cnt [NCMP-1:0];
    logic [NCMP-1:0] miss;

    genvar i;
    generate
    for (i = 0; i < NCMP; i = i + 1) begin : g_cmp

        logic reached, fire;

        // Fire one tick early, because the trigger output is registered:
        // that makes the pin edge land on exactly the tick that was
        // programmed instead of one after it.
        //
        // The test is signed(now + 1 - deadline) >= 0. For speed the channel
        // stores deadline - 1 (deadline_m1) instead, decremented once when it
        // is armed, so every clock's compare is a single subtraction of two
        // registers: the timebase increment used to sit in series with it, on
        // one of the slowest paths in the chip. Same result for every value,
        // wrap included: (now + 1) - d == now - (d - 1) modulo 2^32. An
        // earlier rewrite as `now - deadline >= -1` was measured worse (a
        // 32-input AND tree per channel), so the subtraction stays.
        if (i < NARM) begin : g_dl
            assign reached = ($signed(now - deadline_m1[i]) >= 0);
            // On time means now == deadline - 1: the pin edge lands on the
            // programmed tick. An equality of the two registers keeps this
            // off the subtractor, on one of the slowest paths in the chip.
            assign miss[i] = armed[i] && reached && (now != deadline_m1[i]);

            always_ff @(posedge clk) begin
                if (rst) begin
                    armed[i]       <= 1'b0;
                    deadline_m1[i] <= 32'hFFFF_FFFF;
                end else if (arm_we && (arm_sel == i[1:0])) begin
                    deadline_m1[i] <= arm_time_m1;
                    armed[i]       <= 1'b1;
                end else if (armed[i] && reached) begin
                    armed[i]       <= 1'b0;
                end
            end
        end else begin : g_pulse_only
            // constant flip-flops: synthesis removes them
            assign reached = 1'b0;
            assign miss[i] = 1'b0;
            always_ff @(posedge clk) begin
                armed[i]       <= 1'b0;
                deadline_m1[i] <= 32'hFFFF_FFFF;
            end
        end

        assign fire = (armed[i] && reached) || (pulse_we && pulse_mask[i]);

        always_ff @(posedge clk) begin
            if (rst) begin
                pulse_cnt[i] <= '0;
            end else begin
                if (fire)                        pulse_cnt[i] <= pw;
                else if (pulse_cnt[i] != '0)     pulse_cnt[i] <= pulse_cnt[i] - 1'b1;
            end
        end

        assign trig[i] = (pulse_cnt[i] != '0);
    end
    endgenerate

    always_ff @(posedge clk) begin
        if (rst)        late <= 1'b0;
        else if (|miss) late <= 1'b1;
    end

    always_ff @(posedge clk) begin
        if (rst)        pw <= {{(PWW-4){1'b0}}, 4'd8};   // 8 ticks by default
        else if (pw_we) pw <= pw_in[PWW-1:0];
    end

    wire _unused = &{1'b0, pw_in[31:PWW], 1'b0};

endmodule : sync_compare
