// timebase_props.svh — spliced into a scratch copy of src/sync/sync_timebase.sv
// (syn/formal/run.sh). T1: with no TADJ step and no rate trim since reset, now
// advances by exactly one tick per clock, which is FREE_RUN's assumption in
// compare_props.svh. T2: a TADJ step never swallows the clock's own tick.
    logic f_past_ok = 1'b0;
    logic f_trimmed = 1'b0;   // a non-zero rate was ever written
    always @(posedge clk) begin
        f_past_ok <= 1'b1;
        if (rst) f_trimmed <= 1'b0;
        else if (rate_we && rate_in[FRACW-1:0] != '0) f_trimmed <= 1'b1;
    end
    initial assume (rst);
    always @(posedge clk) if (f_past_ok && !rst) begin
        if ($past(rst)) assert (now == 32'd0);
        else begin
            if (!$past(adj_we) && !$past(f_trimmed) && !f_trimmed) assert (now == $past(now) + 32'd1);
            if ($past(adj_we)) assert (now == $past(now) + $past(adj_in) + 32'd1);
            if (!f_trimmed) assert (rate_mag == '0);
        end
    end
