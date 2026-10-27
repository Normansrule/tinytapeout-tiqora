// sync_event_fifo.sv — the shared timestamped event queue.
//
// One queue for all channels rather than one capture register per channel.
// Two reasons, and the second is the important one:
//
//   area  : eight 32-bit capture registers is 256 flip-flops, which is most
//           of a 1x1 tile. A 2-deep shared queue is 64.
//   order : a shared queue preserves the ORDER of events across channels.
//           Per-channel registers do not, and cross-channel ordering is
//           exactly what you are trying to measure when you sync an inertial
//           measurement unit against an encoder against a camera shutter.
//
// Entry format (see the README for the bit table):
//   [31]    source  0 = hardware capture, 1 = software TMARK
//   [30:28] channel (hardware) or tag (software)
//   [27]    edge    1 = rising
//   [26:0]  timestamp, low 27 bits of the timebase
`default_nettype none

module sync_event_fifo #(
    parameter int DEPTH = 2,
    parameter int PTRW  = 1              // $clog2(DEPTH)
) (
    input  wire  logic        clk,
    input  wire  logic        rst,
    input  wire  logic        push,
    input  wire  logic [31:0] wdata,
    input  wire  logic        pop,
    input  wire  logic        lost,      // an event dropped before the queue
    output logic [31:0]       rdata,     // head, valid while !empty
    output logic              empty,
    output logic              full,
    output logic [PTRW:0]     count,
    output logic              overflow   // sticky, cleared only by reset
);

    logic [31:0]   mem [DEPTH-1:0];
    logic [PTRW:0] cnt;
    logic [PTRW-1:0] rptr, wptr;

    assign empty = (cnt == '0);
    assign full  = (cnt == (PTRW+1)'(DEPTH));
    assign count = cnt;
    assign rdata = mem[rptr];

    logic do_push, do_pop;
    assign do_push = push && !full;
    assign do_pop  = pop  && !empty;

    always_ff @(posedge clk) begin
        if (rst) begin
            cnt      <= '0;
            rptr     <= '0;
            wptr     <= '0;
            overflow <= 1'b0;
        end else begin
            if (do_push) begin
                mem[wptr] <= wdata;
                wptr      <= (wptr == PTRW'(DEPTH-1)) ? '0 : (wptr + 1'b1);
            end
            if (do_pop)
                rptr <= (rptr == PTRW'(DEPTH-1)) ? '0 : (rptr + 1'b1);

            unique case ({do_push, do_pop})
                2'b10:   cnt <= cnt + 1'b1;
                2'b01:   cnt <= cnt - 1'b1;
                default: cnt <= cnt;
            endcase

            // a push that finds the queue full is a lost event, and so is
            // one dropped on the way in: say so
            if ((push && full) || lost) overflow <= 1'b1;
        end
    end

endmodule : sync_event_fifo
