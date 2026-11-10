// fifo_props.svh — spliced into a scratch copy of src/sync/sync_event_fifo.sv
// (syn/formal/run.sh). A ghost reference queue (f_q0 = head, f_q1, f_n) follows
// every push and pop. Q1: the hardware is that queue: same count, and the head
// it shows is the oldest event not yet popped, so events come out complete and
// in arrival order. Q2: overflow is set exactly when an event was dropped (a
// push into a full queue, or `lost`), so no event disappears silently.
// Written for DEPTH == 2, the depth both chips build; deeper queues fail the
// first assertion rather than pass by accident.
    logic        f_past_ok = 1'b0;
    logic [31:0] f_q0, f_q1;
    logic [PTRW:0] f_n;
    logic        f_drop;
    always @(posedge clk) begin
        f_past_ok <= 1'b1;
        if (rst) begin
            f_n <= '0; f_drop <= 1'b0;
        end else begin
            if ((push && f_n == 2) || lost) f_drop <= 1'b1;
            case ({push && f_n != 2, pop && f_n != 0})
                2'b10: begin
                    if (f_n == 0) f_q0 <= wdata; else f_q1 <= wdata;
                    f_n <= f_n + 1'b1;
                end
                2'b01: begin f_q0 <= f_q1; f_n <= f_n - 1'b1; end
                2'b11: begin
                    if (f_n == 1) f_q0 <= wdata;
                    else begin f_q0 <= f_q1; f_q1 <= wdata; end
                end
                default: ;
            endcase
        end
    end
    initial assume (rst);
    always @(*) if (!f_past_ok) assume (rst);   // induction may not start before a reset
    always @(*) if (f_past_ok && !rst) begin
        assert (DEPTH == 2);
        assert (count == f_n && f_n <= 2);
        assert (empty == (f_n == 0) && full == (f_n == 2));
        if (f_n != 0) assert (rdata == f_q0);                     // Q1: head
        if (f_n == 2) assert (mem[~rptr] == f_q1);               // Q1: the next one
        assert (wptr == rptr + f_n[0]);                          // pointer invariant
        assert (overflow == f_drop);                             // Q2
    end
