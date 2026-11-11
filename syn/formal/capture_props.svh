// capture_props.svh — spliced into a scratch copy of src/sync/sync_capture.sv
// (syn/formal/run.sh). A ghost history `F_H(k) holds the pin as sampled k+1
// clocks ago (cleared by reset, like the synchroniser). Then:
// K1 (FILTW = 0, both chips): the filtered level is the pin two clocks ago and an
//    edge is reported exactly three clocks after the pin moved; the latency is
//    constant, which is what lets a timestamp be calibrated.
// K2 (FILTW > 0): the level changes only after FILTW+1 agreeing samples, so a
//    glitch of FILTW samples or fewer never makes an event, and a level that
//    holds that long always gets through.
// K3: an event only on an enabled channel, with the polarity the channel asked for.
    logic f_past_ok = 1'b0;
    logic [(FILTW+4)*NCH-1:0] f_h;      // a flat shift register, not a memory
    `define F_H(k) f_h[(k)*NCH +: NCH]
    always @(posedge clk) begin
        f_past_ok <= 1'b1;
        f_h <= rst ? '0 : {f_h[(FILTW+3)*NCH-1:0], pin};
    end
    initial assume (rst);
    always @(*) if (!f_past_ok) assume (rst);
    logic [NCH-1:0] f_all1, f_all0;
    always @(*) begin
        f_all1 = '1; f_all0 = '1;
        for (int j = 0; j <= FILTW; j++) begin
            f_all1 = f_all1 &  `F_H(3+j);
            f_all0 = f_all0 & ~`F_H(3+j);
        end
    end
    always @(posedge clk) if (f_past_ok) begin
        assert (sync0 == `F_H(0) && sync1 == `F_H(1));
        if (FILTW == 0) begin
            assert (level == `F_H(1));                                   // K1
            assert (evt_rise == (`F_H(1) & ~`F_H(2)));                    // K1
            assert (stable_q == `F_H(2));
        end else begin
            if ($past(rst)) assert (stable == '0);
            else assert (stable == (f_all1 | ($past(stable) & ~f_all0)));   // K2
            assert (stable_q == ($past(rst) ? '0 : $past(stable)));
        end
        assert ((evt & ~en) == '0);                                     // K3
        assert (evt == (en & (both ? (stable ^ stable_q)                // K3
                                   : ((fall & ~stable & stable_q) | (~fall & stable & ~stable_q)))));
    end
    // induction needs the filter's sample window tied to the same history
    generate if (FILTW > 0) for (genvar c = 0; c < NCH; c++) begin : f_win
        for (genvar j = 0; j <= FILTW; j++) begin : f_s
            always @(posedge clk) if (f_past_ok) assert (g_lane[c].g_filt.shift[j] == f_h[(2+j)*NCH + c]);
        end
    end endgenerate
