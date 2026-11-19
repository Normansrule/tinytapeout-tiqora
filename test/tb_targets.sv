// tb_targets.sv — every tape-out target's top, in lockstep with the Tiny
// Tapeout top.
//
// Four copies of the chip get the same host commands on the serial line,
// the same capture inputs, clock and reset:
//
//   ref  tt_um_normansrule_tiqora_serial   the Tiny Tapeout submission
//   mac  tiqora_serial_macro               sky130-macro and gf180-macro
//   car  user_project_wrapper              caravel-sky130 (generated)
//   opf  openframe_project_wrapper         openframe-sky130 (generated)
//
// Each target's pins are read back through its own pin map (the pad numbers
// below are the ones in targets/*.toml) and compared with the reference
// every clock, from the third clock of reset on. One differing clock fails
// the run. Pad rules are checked too: input pads are never driven, output
// pads always are, and an Openframe pad that drives is in a driving mode.
//
// The bench also proves the comparison saw real work: the chip answered
// on TX, a trigger fired, events were captured.
//
// Run with:  make targets   (+SEED=n)
`default_nettype none
`timescale 1ns/1ps

module tb_targets;

    localparam int DIV    = 434;           // the silicon baud divisor
    localparam int CLK_NS = 20;
    localparam int BIT_NS = DIV * CLK_NS;

    reg        clk = 1'b0, rst_n = 1'b0, rx = 1'b1;
    reg  [7:0] cap = 8'h00;
    always #(CLK_NS/2) clk = ~clk;

    integer errors = 0, checks = 0, mism = 0, cyc = 0;
    integer tx_edges = 0, trig_edges = 0, evt_pulses = 0;

    task chk(input cond, input string name);
        begin
            checks = checks + 1;
            if (!cond) begin
                errors = errors + 1;
                $display("  FAIL  %0s", name);
            end else
                $display("  ok    %0s", name);
        end
    endtask

    // ref: the Tiny Tapeout top
    wire [7:0] r_uo, r_uio_out, r_uio_oe;
    wire [7:0] r_ui     = {cap[6:3], rx, cap[2:0]};
    wire [7:0] r_uio_in = {7'b0, cap[7]};
    tt_um_normansrule_tiqora_serial ref_dut (
        .ui_in(r_ui), .uo_out(r_uo), .uio_in(r_uio_in), .uio_out(r_uio_out), .uio_oe(r_uio_oe),
        .ena(1'b1), .clk(clk), .rst_n(rst_n));

    // mac: the plain macro, packed into the Tiny Tapeout order for comparison
    wire [2:0] m_trig, m_chan;
    wire [1:0] m_cnt;
    wire m_pend, m_pulse, m_ovf, m_hb, m_tx, m_act, m_edge;
    tiqora_serial_macro mac_dut (
        .clk(clk), .rst_n(rst_n), .cap_in(cap), .trig_out(m_trig), .evt_pending(m_pend),
        .evt_pulse(m_pulse), .ovf(m_ovf), .heartbeat(m_hb), .uart_rx(rx), .uart_tx(m_tx),
        .uart_active(m_act), .ev_chan(m_chan), .ev_edge(m_edge), .ev_count(m_cnt));
    wire [7:0] m_uo  = {m_pulse, m_hb, m_ovf, m_tx, m_pend, m_trig};
    wire [7:0] m_uio = {m_cnt, m_edge, m_chan, m_act, 1'b0};

    // car: Caravel, pads from targets/caravel-sky130.toml
    wire [37:0] c_io_out, c_io_oeb;
    wire [37:0] c_io_in = {6'b0, 7'b0, rx, 8'h00, cap, 8'h00};
    user_project_wrapper car_dut (
        .wb_clk_i(clk), .wb_rst_i(~rst_n), .wbs_stb_i(1'b0), .wbs_cyc_i(1'b0), .wbs_we_i(1'b0),
        .wbs_sel_i(4'h0), .wbs_dat_i(32'h0), .wbs_adr_i(32'h0), .wbs_ack_o(), .wbs_dat_o(),
        .la_data_in(128'h0), .la_data_out(), .la_oenb({128{1'b1}}),
        .io_in(c_io_in), .io_out(c_io_out), .io_oeb(c_io_oeb), .analog_io(),
        .user_clock2(1'b0), .user_irq());
    wire [7:0] c_uo  = c_io_out[23:16];
    wire [7:0] c_uio = {c_io_out[31:25], 1'b0};

    // opf: Openframe, pads from targets/openframe-sky130.toml
    wire [43:0] o_out, o_oeb, o_ind, o_dm2, o_dm1, o_dm0;
    reg  [43:0] o_in;
    always @* begin
        o_in = 44'h0;
        o_in[5] = rx;
        o_in[23:16] = cap;
        o_in[38] = clk;
    end
    openframe_project_wrapper opf_dut (
        .porb_h(1'b1), .porb_l(1'b1), .por_l(1'b0), .resetb_h(rst_n), .resetb_l(rst_n),
        .mask_rev(32'h0), .gpio_in(o_in), .gpio_in_h(44'h0), .gpio_out(o_out), .gpio_oeb(o_oeb),
        .gpio_inp_dis(o_ind), .gpio_ib_mode_sel(), .gpio_vtrip_sel(), .gpio_slow_sel(),
        .gpio_holdover(), .gpio_analog_en(), .gpio_analog_sel(), .gpio_analog_pol(),
        .gpio_dm2(o_dm2), .gpio_dm1(o_dm1), .gpio_dm0(o_dm0), .analog_io(), .analog_noesd_io(),
        .gpio_loopback_one({44{1'b1}}), .gpio_loopback_zero(44'h0));
    wire [7:0] o_uo  = {o_out[30], o_out[29], o_out[28], o_out[6], o_out[27], o_out[26], o_out[25], o_out[24]};
    wire [7:0] o_uio = {o_out[37:32], o_out[31], 1'b0};

    // ---------------------------------------------------------------
    // the comparison
    // ---------------------------------------------------------------
    task automatic cmp(input string who, input [7:0] uo, input [7:0] uio);
        if (uo !== r_uo || uio !== {r_uio_out[7:1], 1'b0}) begin
            mism = mism + 1;
            if (mism <= 5)
                $display("  FAIL  cycle %0d %0s: uo %02x/%02x uio %02x/%02x (target/ref)",
                         cyc, who, uo, r_uo, uio, r_uio_out);
        end
    endtask

    integer pad_rule_fail = 0, clk_n = 0, k;
    always @(posedge clk) clk_n <= clk_n + 1;
    always @(negedge clk) if (clk_n >= 3) begin
        cmp("sky130/gf180 macro", m_uo, m_uio);
        cmp("caravel",            c_uo, c_uio);
        cmp("openframe",          o_uo, o_uio);
        if (r_uio_oe !== 8'hFE) pad_rule_fail = pad_rule_fail + 1;
        // Caravel: inputs 8-15 and 24 undriven, outputs 16-23 and 25-31 driven
        if (c_io_oeb[15:8] !== 8'hFF || c_io_oeb[24] !== 1'b1 ||
            c_io_oeb[23:16] !== 8'h00 || c_io_oeb[31:25] !== 7'h00) pad_rule_fail = pad_rule_fail + 1;
        // Openframe: inputs 5, 16-23, 38 undriven with input on; outputs driven
        if (o_oeb[5] !== 1'b1 || o_oeb[23:16] !== 8'hFF || o_oeb[38] !== 1'b1 ||
            o_oeb[6] !== 1'b0 || o_oeb[37:24] !== 14'h0) pad_rule_fail = pad_rule_fail + 1;
        if ({o_ind[5], o_ind[23:16], o_ind[38]} !== 10'h0) pad_rule_fail = pad_rule_fail + 1;
        for (k = 0; k < 44; k = k + 1)
            if (o_oeb[k] === 1'b0 && {o_dm2[k], o_dm1[k], o_dm0[k]} !== 3'b110) pad_rule_fail = pad_rule_fail + 1;
    end

    // activity, measured on the reference
    reg tx_q = 1'b1, trig_q = 1'b0;
    always @(posedge clk) begin
        tx_q <= r_uo[4];
        trig_q <= r_uo[0];
        if (tx_q && !r_uo[4]) tx_edges = tx_edges + 1;
        if (r_uo[0] && !trig_q) trig_edges = trig_edges + 1;
        if (r_uo[7]) evt_pulses = evt_pulses + 1;
    end

    task send_byte(input [7:0] b);
        integer i;
        begin
            rx = 1'b0; #(BIT_NS);
            for (i = 0; i < 8; i = i + 1) begin rx = b[i]; #(BIT_NS); end
            rx = 1'b1; #(BIT_NS);
        end
    endtask

    task host_write(input [3:0] a, input [31:0] d);
        begin
            send_byte(8'h01); send_byte({4'h0, a});
            send_byte(d[7:0]); send_byte(d[15:8]); send_byte(d[23:16]); send_byte(d[31:24]);
            #(12 * BIT_NS);                       // the reply
        end
    endtask

    // random edges on the capture pins
    integer seed = 1;
    always @(posedge clk) if (rst_n && ($random(seed) % 997 == 0)) cap <= $random(seed);

    initial begin
        if (!$value$plusargs("SEED=%d", seed)) seed = 1;
        $display("\n=== tape-out targets in lockstep with the Tiny Tapeout top, seed %0d ===", seed);
        repeat (20) @(posedge clk);
        rst_n = 1'b1;
        #(2 * BIT_NS);
        send_byte(8'h03); #(12 * BIT_NS);         // PING
        host_write(4'h3, 32'h0000_00FF);          // CFG: all eight channels
        host_write(4'h7, 32'h0000_0040);          // PW: 64-tick pulses
        host_write(4'hA, 32'h0000_0005);          // PULSE: triggers 0 and 2
        send_byte(8'h02); send_byte(8'h02); #(48 * BIT_NS);   // read STAT
        send_byte(8'h02); send_byte(8'h01); #(48 * BIT_NS);   // pop an EVENT
        send_byte(8'hFF); #(12 * BIT_NS);         // nonsense: one NAK
        $display("  clocks %0d, TX start bits %0d, TRIG0 rising edges %0d, event pulses %0d",
                 clk_n, tx_edges, trig_edges, evt_pulses);
        chk(tx_edges >= 10, "the chip answered the host on TX");
        chk(trig_edges >= 1, "TRIG0 pulsed");
        chk(evt_pulses >= 1, "events were captured");
        chk(mism == 0, "every target matched the Tiny Tapeout top on every clock");
        chk(pad_rule_fail == 0, "pad rules held on every clock (directions, Openframe modes)");
        if (errors == 0) $display("tb_targets: %0d checks PASSED", checks);
        else             $display("tb_targets: %0d of %0d checks FAILED", errors, checks);
        $finish;
    end
endmodule
