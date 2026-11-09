// compare_props.svh — formal properties spliced into a scratch copy of
// src/sync/sync_compare.sv just before `endmodule` (syn/formal/run.sh); the
// RTL file itself is not edited. Proven for every input sequence by
// k-induction (yosys-smtbmc + z3), for every deadline and all 2^32 values of now.
//   P1 an armed channel whose deadline is reached fires on the next clock and
//      disarms, unless re-armed in that clock: no deadline is ever missed;
//   P2 a pin only rises because of a reached deadline or a direct pulse;
//   P3 a pulse lasts exactly PW clocks: the counter reloads or counts down by one;
//   P4 (FREE_RUN: now advances one tick per clock) for a deadline armed at
//      least 2 ticks and less than 2^31 ticks ahead, the pin rises on exactly
//      the programmed tick, now == deadline, across the 2^32 wrap. (Armed
//      closer than that, or in the past, it fires on the next clock: P1.)
// F_DL(i) maps the RTL's stored deadline back to the programmed one, so the
// same properties check both storage schemes (deadline, or deadline - 1).
`ifdef F_STORES_DM1
`define F_DL(i) (deadline_m1[i] + 32'd1)
`else
`define F_DL(i) (deadline[i])
`endif
    logic f_past_ok = 1'b0;
    always @(posedge clk) f_past_ok <= 1'b1;
    initial assume (rst);
`ifdef FREE_RUN
    always @(posedge clk) if (f_past_ok && !$past(rst)) assume (now == $past(now) + 32'd1);
`endif
    generate for (i = 0; i < NCMP; i = i + 1) begin : f
        wire f_arm   = arm_we && (arm_sel == i[1:0]);
        wire f_pulse = pulse_we && pulse_mask[i];
        // The programmed deadline as software wrote it, and whether it was
        // armed at least 2 ticks ahead: P4 is stated against arm_time, not
        // against however the RTL chooses to store it.
        logic [31:0] f_dl    = 32'd0;
        logic        f_ahead = 1'b0;
        always @(posedge clk)
            if (rst) f_ahead <= 1'b0;
            else if (f_arm) begin
                f_dl    <= arm_time;
                f_ahead <= $signed(arm_time - now) >= 32'sd2;
            end
        always @(posedge clk) if (f_past_ok && !rst) begin
            if ($past(rst)) begin
                assert (!armed[i] && !trig[i]);
            end else begin
                // the RTL holds exactly the deadline software programmed
                if (armed[i]) assert (`F_DL(i) == f_dl);
`ifdef FREE_RUN
                // an in-time deadline stays ahead of now until it fires
                if (armed[i] && f_ahead) assert ($signed(f_dl - now) >= 32'sd1);
`endif
                // P1
                if ($past(armed[i] && g_cmp[i].reached && !f_arm)) begin
                    assert (!armed[i]);
                    assert (pulse_cnt[i] == $past(pw));
                end
                // P2
                if (trig[i] && !$past(trig[i]))
                    assert ($past(armed[i] && g_cmp[i].reached) || $past(f_pulse));
                // P3
                if ($past(armed[i] && g_cmp[i].reached) || $past(f_pulse))
                    assert (pulse_cnt[i] == $past(pw));
                else if ($past(pulse_cnt[i]) != '0)
                    assert (pulse_cnt[i] == $past(pulse_cnt[i]) - 1'b1);
                else
                    assert (pulse_cnt[i] == '0);
`ifdef FREE_RUN
                // P4
                if (trig[i] && !$past(trig[i]) && !$past(f_pulse) && $past(f_ahead))
                    assert (now == $past(f_dl));
`endif
            end
        end
    end endgenerate
